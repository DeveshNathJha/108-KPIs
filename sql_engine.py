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

def run_correlation(raw_df: pd.DataFrame, hits_df: pd.DataFrame) -> pd.DataFrame:
    # ── Pandas Preprocessing for Speed ──
    # Cleaned Tripps
    raw = pd.DataFrame()
    raw['Trip_Clean_Phone'] = raw_df.get('CALLER NO', pd.Series()).astype(str).str.replace(' ', '', regex=False).str[-10:]
    raw['Trip_Connected_Time'] = _fast_datetime_parse(raw_df.get('Agrent CONNECTED TIME', pd.Series()))
    raw['Trip_Assigned_Time'] = _fast_datetime_parse(raw_df.get('assigned_time', pd.Series()))
    raw['Scene_Arrival_Time'] = _fast_datetime_parse(raw_df.get('scene_arrival_time', pd.Series()))
    raw['Case_ID'] = raw_df.get('Case ID', pd.Series()).astype(str)
    raw['Disease'] = raw_df.get('DISEASE', pd.Series()).astype(str)
    raw['Vehicle_No'] = raw_df.get('Vehicle No', pd.Series()).astype(str)
    
    district = raw_df.get('District', raw_df.get('Distict', pd.Series())).astype(str).str.strip()
    raw['Trip_District'] = np.where(district.isin(['', '\\N', 'nan', 'NaN', 'None', 'NULL', 'Other', 'other', 'unknown']), 'Unknown', district)
    
    loc_type = raw_df.get('Location Type', pd.Series()).astype(str)
    raw['Location_Category'] = np.where(loc_type.str.contains('Urban', na=False), 'Urban', 
                               np.where(loc_type.str.contains('Rural', na=False), 'Rural', 'Unknown'))
                               
    rt_sec = (pd.to_datetime(raw['Scene_Arrival_Time']) - pd.to_datetime(raw['Trip_Assigned_Time'])).dt.total_seconds()
    raw['Response_Time_Mins'] = np.where(rt_sec < -43200, rt_sec + 86400, np.where(rt_sec < 0, 0, rt_sec)) / 60.0
    
    raw = raw.dropna(subset=['Trip_Connected_Time']).replace({'nan': None, 'NaT': None})

    # Cleaned Calls
    hits = pd.DataFrame()
    # 1. Extract ALL columns first before any dropna/sort
    hits['Call_Start_Time_Raw'] = hits_df.get('Call Start Time', pd.Series())
    hits['Clean_Phone'] = hits_df.get('Phone Number', pd.Series()).astype(str).str.replace(' ', '', regex=False).str[-10:]
    
    q_dur = _parse_duration(hits_df.get('QUEUE Duration', pd.Series(index=hits_df.index)))
    r_dur = _parse_duration(hits_df.get('RING Duration', pd.Series(index=hits_df.index)))
    hits['Call_Pickup_Time_Sec'] = q_dur + r_dur

    _connect_raw = hits_df.get('Call Connect Time', pd.Series(index=hits_df.index))
    _end_raw     = hits_df.get('Call End Time',     pd.Series(index=hits_df.index))
    _connect_ts  = pd.to_datetime(_connect_raw, errors='coerce', format='mixed', dayfirst=False)
    _end_ts      = pd.to_datetime(_end_raw,     errors='coerce', format='mixed', dayfirst=False)
    _aht_secs    = (_end_ts - _connect_ts).dt.total_seconds()
    hits['AHT_Secs'] = _aht_secs.where((_aht_secs > 0) & (_aht_secs < 7200), other=np.nan)
    
    agent_disp = hits_df.get('Agent Disposition', pd.Series(index=hits_df.index)).astype(str).str.strip()
    dialer_disp = hits_df.get('Dialer Disposition', pd.Series(index=hits_df.index)).astype(str).str.strip()

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

    dist = hits_df.get('District', pd.Series(index=hits_df.index)).astype(str).str.strip()
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
