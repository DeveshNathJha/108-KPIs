r"""
sql_engine.py  (v6 — Datetime Fix & Disposition Normalization)
─────────────────────────────────────────────────────────────────────────────
108 Ambulance KPI — SQL Correlation Engine

Key fix (v6): Both data files use M/D/YYYY (US/ISO) format.
  dayfirst=True was treating Apr-01 as Jan-04, completely breaking
  the time-window join and producing near-zero served-call counts.
"""

import sqlite3
import warnings
import pandas as pd
import numpy as np

_CORRELATION_SQL = """
-- STEP 3: PROBABILISTIC CORRELATION (TIME + PHONE)
WITH PotentialMatches AS (
    SELECT
        c.*,
        t.Trip_Connected_Time,
        t.Scene_Arrival_Time,
        t.Case_ID,
        t.Disease,
        t.Vehicle_No,
        t.Trip_District,
        t.Location_Category,
        t.Response_Time_Mins, 
        ((JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c.Call_Start_Time)) * 1440) AS Time_Gap_Mins,
        ABS((JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c.Call_Start_Time)) * 1440) AS Abs_Time_Gap_Mins
        
    FROM CleanedCalls c
    LEFT JOIN CleanedTrips t ON c.Clean_Phone = t.Trip_Clean_Phone
    AND ABS((JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c.Call_Start_Time)) * 1440) <= 90
),

-- STEP 4: BEST-MATCH SELECTION (TRIP-CENTRIC)
BestCallForTrip AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY Case_ID
            ORDER BY Abs_Time_Gap_Mins ASC
        ) AS Trip_Rank,
        COUNT(Case_ID) OVER (
            PARTITION BY Call_ID
        ) AS Candidate_Match_Count
    FROM PotentialMatches
    WHERE Case_ID IS NOT NULL
),

ServedTrips AS (
    SELECT * FROM BestCallForTrip WHERE Trip_Rank = 1
),

-- STEP 5: FINAL CORRELATED DATASET
CorrelatedCalls AS (
    SELECT
        c.Call_ID, 
        c.Call_Start_Time, 
        c.Clean_Phone, 
        c.Final_Disposition                                            AS Agent_Disposition,
        COALESCE(t.Trip_District, c.Call_District)                     AS Final_District,
        c.Call_District, 
        c.Is_Eligible, 
        c.Call_Pickup_Time_Sec,
        c.AHT_Secs,
        c.Call_Seq_Per_Phone,
        c.Total_Calls_From_Phone,
        COALESCE(t.Candidate_Match_Count, 0)                           AS Candidate_Match_Count,
        
        t.Case_ID, 
        t.Trip_Connected_Time, 
        t.Scene_Arrival_Time,
        t.Disease, t.Vehicle_No, t.Trip_District, t.Location_Category,
        t.Response_Time_Mins, 
        t.Abs_Time_Gap_Mins,
        t.Time_Gap_Mins,
        
        CASE WHEN t.Case_ID IS NOT NULL THEN 'Served' ELSE 'Not Served' END AS Service_Status,

        CASE
            WHEN t.Abs_Time_Gap_Mins <= 60  THEN 'High'
            WHEN t.Abs_Time_Gap_Mins <= 90  THEN 'Medium'
            WHEN t.Case_ID IS NOT NULL     THEN 'Low'
            ELSE 'No Match'
        END                                                              AS Match_Confidence,

        ROUND(
            (JULIANDAY(t.Scene_Arrival_Time) - JULIANDAY(c.Call_Start_Time)) * 1440,
            2
        )                                                                AS Scene_Arrival_TAT_Mins,

        CASE
            WHEN t.Location_Category = 'Urban'
                 AND t.Response_Time_Mins > 0
                 AND t.Response_Time_Mins <= 15 THEN 1
            ELSE 0
        END                                                              AS Urban_SLA_Met,

        CASE
            WHEN t.Location_Category = 'Rural'
                 AND t.Response_Time_Mins > 0
                 AND t.Response_Time_Mins <= 30 THEN 1
            ELSE 0
        END                                                              AS Rural_SLA_Met,

        CASE
            WHEN t.Location_Category = 'Urban'
                 AND t.Response_Time_Mins > 0
                 AND t.Response_Time_Mins <= 25 THEN 1
            ELSE 0
        END                                                              AS Urban_ART_Met,

        CASE
            WHEN t.Location_Category = 'Rural'
                 AND t.Response_Time_Mins > 0
                 AND t.Response_Time_Mins <= 40 THEN 1
            ELSE 0
        END                                                              AS Rural_ART_Met

    FROM CleanedCalls c
    LEFT JOIN ServedTrips t ON c.Call_ID = t.Call_ID
)

SELECT * FROM CorrelatedCalls
"""

def _fast_datetime_parse(series: pd.Series) -> pd.Series:
    """Optimized datetime parsing for mixed formats.
    
    IMPORTANT: Both data files use M/D/YYYY / M/D/YY (US format).
    dayfirst=False ensures '4/1/2026' is parsed as April 1, not January 4.
    format='mixed' handles the two variants (4/1/2026 vs 4/1/26) efficiently.
    """
    return pd.to_datetime(series, errors='coerce', format='mixed', dayfirst=False).dt.strftime('%Y-%m-%d %H:%M:%S')

def _parse_duration(series: pd.Series) -> pd.Series:
    """Fast conversion of HH:MM:SS to seconds."""
    s = series.astype(str).str.strip()
    mask = s.str.match(r'^\d{2}:\d{2}:\d{2}$')
    
    res = pd.Series(0.0, index=series.index)
    if mask.any():
        valid = s[mask]
        res[mask] = (
            valid.str.slice(0, 2).astype(float) * 3600 +
            valid.str.slice(3, 5).astype(float) * 60 +
            valid.str.slice(6, 8).astype(float)
        )
    return res

def _find_col(df: pd.DataFrame, candidates: list, default_series: pd.Series) -> pd.Series:
    """Finds a column in df matching any candidate name case-insensitively,
    standardizing spaces and underscores. If not found, returns default_series.
    """
    for c in df.columns:
        c_clean = str(c).strip().lower().replace('_', ' ').replace('  ', ' ')
        for cand in candidates:
            cand_clean = str(cand).strip().lower().replace('_', ' ').replace('  ', ' ')
            if cand_clean == c_clean:
                return df[c]
    return default_series

def _parse_raw_datetime(df: pd.DataFrame, time_candidates: list, date_candidates: list, default_series: pd.Series) -> pd.Series:
    time_series = _find_col(df, time_candidates, None)
    if time_series is None or time_series.empty:
        return default_series
        
    date_series = _find_col(df, date_candidates, None)
    if date_series is None or date_series.empty or date_series.isna().all():
        # Fallback if no date column is found
        return pd.to_datetime(time_series, errors='coerce', format='mixed', dayfirst=False).dt.strftime('%Y-%m-%d %H:%M:%S')
        
    d_str = pd.to_datetime(date_series, errors='coerce').dt.strftime('%Y-%m-%d')
    
    def _extract_time_str(x):
        if pd.isna(x) or str(x).strip() in ('', 'nan', 'None', '\\N', 'N/A'):
            return None
        if isinstance(x, str):
            parts = x.strip().split()
            t_part = parts[-1] if parts else ''
            if ':' in t_part:
                return t_part
            return None
        if hasattr(x, 'strftime'):
            return x.strftime('%H:%M:%S')
        return None
        
    t_str = time_series.apply(_extract_time_str)
    combined = np.where(t_str.isna() | pd.isna(d_str), None, d_str + ' ' + t_str)
    return pd.Series(pd.to_datetime(combined, errors='coerce'), index=df.index).dt.strftime('%Y-%m-%d %H:%M:%S')

def run_correlation(raw_df: pd.DataFrame, hits_df: pd.DataFrame) -> pd.DataFrame:
    # ── Pandas Preprocessing for Speed ──
    # Cleaned Tripps
    raw = pd.DataFrame()
    
    # Define fallback series of correct length
    raw_default = pd.Series(index=raw_df.index)
    hits_default = pd.Series(index=hits_df.index)
    
    raw['Trip_Clean_Phone'] = _find_col(raw_df, ['CALLER NO', 'Phone Number', 'Phone', 'Mobile'], raw_default).astype(str).str.replace(' ', '', regex=False).str[-10:]
    raw['Trip_Connected_Time'] = _parse_raw_datetime(raw_df, ['Agrent CONNECTED TIME', 'Agent Connected Time', 'Connected Time', 'Connect Time'], ['Date', 'date'], raw_default)
    raw['Trip_Assigned_Time'] = _parse_raw_datetime(raw_df, ['assigned_time', 'assigned time', 'assign time'], ['Date', 'date'], raw_default)
    raw['Scene_Arrival_Time'] = _parse_raw_datetime(raw_df, ['scene_arrival_time', 'scene arrival time', 'scene arrival', 'arrival time'], ['Date', 'date'], raw_default)
    raw['Case_ID'] = _find_col(raw_df, ['Case ID', 'Case No', 'Case Number'], raw_default).astype(str)
    raw['Disease'] = _find_col(raw_df, ['DISEASE', 'disease', 'condition'], raw_default).astype(str)
    raw['Vehicle_No'] = _find_col(raw_df, ['Vehicle No', 'Vehicle Number', 'Registration No', 'Registration Number'], raw_default).astype(str)
    
    district = _find_col(raw_df, ['District', 'Distict'], raw_default).astype(str).str.strip()
    raw['Trip_District'] = np.where(district.isin(['', '\\N', 'nan', 'NaN', 'None', 'NULL', 'Other', 'other', 'unknown']), 'Unknown', district)
    
    loc_type = _find_col(raw_df, ['Location Type', 'Location Category', 'Location_Category', 'Area Type'], raw_default).astype(str)
    raw['Location_Category'] = np.where(loc_type.str.contains('Urban', na=False), 'Urban', 
                               np.where(loc_type.str.contains('Rural', na=False), 'Rural', 'Unknown'))
                               
    rt_sec = (pd.to_datetime(raw['Scene_Arrival_Time']) - pd.to_datetime(raw['Trip_Assigned_Time'])).dt.total_seconds()
    # Correct for midnight crossovers
    rt_sec = np.where(rt_sec < -43200, rt_sec + 86400, rt_sec)
    # Floor small negative lag to 0, filter out large outliers (>300 mins or still negative) as np.nan
    raw['Response_Time_Mins'] = np.where((rt_sec >= -60) & (rt_sec < 0), 0,
                                np.where((rt_sec >= 0) & (rt_sec <= 18000), rt_sec / 60.0, np.nan))
    
    raw = raw.dropna(subset=['Trip_Connected_Time']).replace({'nan': None, 'NaT': None})

    # Cleaned Calls
    hits = pd.DataFrame()
    # 1. Extract ALL columns first before any dropna/sort
    hits['Call_Start_Time_Raw'] = _find_col(hits_df, ['Call Start Time', 'Start Time', 'Call Start'], hits_default)
    hits['Clean_Phone'] = _find_col(hits_df, ['Phone Number', 'Phone', 'Mobile', 'CALLER NO'], hits_default).astype(str).str.replace(' ', '', regex=False).str[-10:]
    
    q_dur = _parse_duration(_find_col(hits_df, ['QUEUE Duration', 'QUEUE Time', 'Queue duration'], hits_default))
    r_dur = _parse_duration(_find_col(hits_df, ['RING Duration', 'RING Time', 'Ring duration'], hits_default))
    hits['Call_Pickup_Time_Sec'] = q_dur + r_dur

    _connect_raw = _find_col(hits_df, ['Call Connect Time', 'Connect Time', 'Call Connect'], hits_default)
    _end_raw     = _find_col(hits_df, ['Call End Time', 'End Time', 'Call End'], hits_default)
    _connect_ts  = pd.to_datetime(_connect_raw, errors='coerce', format='mixed', dayfirst=False)
    _end_ts      = pd.to_datetime(_end_raw,     errors='coerce', format='mixed', dayfirst=False)
    _aht_secs    = (_end_ts - _connect_ts).dt.total_seconds()
    hits['AHT_Secs'] = _aht_secs.where((_aht_secs > 0) & (_aht_secs < 7200), other=np.nan)
    
    agent_disp = _find_col(hits_df, ['Agent Disposition', 'Agent_Disposition', 'Disposition'], hits_default).astype(str).str.strip()
    dialer_disp = _find_col(hits_df, ['Dialer Disposition', 'Dialer_Disposition'], hits_default).astype(str).str.strip()

    def _normalize_disp(s: pd.Series) -> pd.Series:
        return s.str.replace(' ', '', regex=False).str.replace('-', '', regex=False)

    agent_disp_norm  = _normalize_disp(agent_disp)
    dialer_disp_norm = _normalize_disp(dialer_disp)

    _blank = agent_disp_norm.isin(['', 'N', 'nan', ''])
    hits['Final_Disposition'] = np.where(
        agent_disp.isin(['', '---', '\\N', 'nan']),
        dialer_disp_norm,
        agent_disp_norm
    )

    dist = _find_col(hits_df, ['District', 'Distict'], hits_default).astype(str).str.strip()
    hits['Call_District'] = np.where(dist.isin(['', '\\N', 'nan', 'NaN', 'None', 'NULL', 'Other', 'other', 'unknown']), 'Unknown', dist)

    eligible_vals = {
        'EmergencyCall', 'InterFacilityTransfer', 'NonEmergencyCall',
        'InterState', 'CriticalCare', 'Neonatal', 'EMTToERO',
    }
    hits['Is_Eligible'] = np.where(
        hits['Final_Disposition'].isin(eligible_vals) | (dialer_disp_norm == 'COMPLETED'),
        1, 0
    )
    
    # 2. Parse timestamps and clean up
    hits['Call_Start_Time'] = _fast_datetime_parse(hits['Call_Start_Time_Raw'])
    hits = hits.dropna(subset=['Call_Start_Time']).sort_values('Call_Start_Time').reset_index(drop=True)
    hits['Call_ID'] = hits.index + 1
    
    # 3. Backfill missing districts based on phone number history
    known_districts = hits[hits['Call_District'] != 'Unknown'].groupby('Clean_Phone')['Call_District'].first()
    hits['Call_District'] = np.where(
        hits['Call_District'] == 'Unknown',
        hits['Clean_Phone'].map(known_districts).fillna('Unknown'),
        hits['Call_District']
    )
    
    # Window functions
    hits['Call_Seq_Per_Phone'] = hits.groupby('Clean_Phone').cumcount() + 1
    hits['Total_Calls_From_Phone'] = hits.groupby('Clean_Phone')['Clean_Phone'].transform('count')
    
    hits = hits.drop(columns=['Call_Start_Time_Raw']).replace({'nan': None, 'NaT': None})

    # ── Fast Indexed SQLite JOIN ──
    conn = sqlite3.connect(':memory:')
    try:
        raw.to_sql('CleanedTrips', conn, index=False, if_exists='replace')
        hits.to_sql('CleanedCalls', conn, index=False, if_exists='replace')
        
        # Build indexes
        conn.execute("CREATE INDEX idx_raw_phone ON CleanedTrips(Trip_Clean_Phone)")
        conn.execute("CREATE INDEX idx_hits_phone ON CleanedCalls(Clean_Phone)")
        conn.execute("CREATE INDEX idx_raw_time ON CleanedTrips(Trip_Connected_Time)")
        conn.execute("CREATE INDEX idx_hits_time ON CleanedCalls(Call_Start_Time)")
        
        result = pd.read_sql_query(_CORRELATION_SQL, conn)
    finally:
        conn.close()

    return result
