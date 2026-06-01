import io
import streamlit as st
import pandas as pd
import numpy as np

import sql_engine   # ← SQL correlation back-end

# ─────────────────────────────────────────────────────────────────────────────
# Disease Categorization (mapped from actual 44 unique DISEASE values in data)
# ─────────────────────────────────────────────────────────────────────────────
DISEASE_CATEGORIES = {
    'Maternal': ['Pregancy related', 'Post delivery'],
    'Trauma (Vehicular)': ['Trauma (Vehicular)', 'Train Accident'],
    'Trauma (Non-Vehicular)': ['Trauma (non Vehicular)', 'HEAD INJURY',
                               'Fire/Burns', 'Assault', 'Suicide attempt', 'Industrial'],
    'Cardiac / Stroke': ['Cardiac/Cardiovascular', 'Stroke/CVA'],
    'Respiratory': ['Respiratory', 'T.B.(Tuberculosis)'],
    'Neonatal / Pediatric': ['Neonatal(upto 1 month)', 'Paediatric(1-12years)',
                             'Infants up to 12 month'],
    'Gastrointestinal': ['Acute Abdomen', 'Vomiting', 'Diarrhoea / Dysentery',
                         'RECTAL BLEEDING', 'Hemorrhoids', 'Liver Problem'],
    'Poisoning / Environmental': ['Accidental Poisoning', 'Animal Attack',
                                  'Heat Stroke', 'Heat Stroke ',
                                  'Environmentals', 'Allergic Reactions'],
    'Chronic / Other Medical': ['KIDNEY FAILURE', 'Anemic diseases', 'Diabetes',
                                'Cancer', 'Convulsions', 'Fevers / Infections',
                                'Mental Health', 'BACKPAIN', 'ENT Related',
                                'Skin Problem', 'HIV AIDS', 'BREAST FEEDING'],
}
# Reverse lookup: disease value → category
_DISEASE_LOOKUP = {}
for cat, values in DISEASE_CATEGORIES.items():
    for v in values:
        _DISEASE_LOOKUP[v] = cat


def categorize_disease(val):
    """Map a raw DISEASE value to its clinical category."""
    if pd.isna(val) or str(val).strip() in ('', '\\N', 'nan', 'None', 'NULL'):
        return 'Unknown'
    val_str = str(val).strip()
    if val_str in _DISEASE_LOOKUP:
        return _DISEASE_LOOKUP[val_str]
    if val_str in ('Others', 'Unconscious', 'Back to Home', 'Other', 'other'):
        return 'Other / Unknown'
    return 'Other / Unknown'


# Required data for KPIs we cannot compute yet (goes into Excel Sheet 2)
REQUIRED_DATA_FOR_REMAINING_KPIS = [
    ['Avg Call pickup within 30s', 'ACD / Ring Time logs ("Call Answered" timestamp)', 'Not available'],
    ['Avg Vehicle Dispatch within 180s', 'Exact "Vehicle Dispatched/Assigned" timestamp', 'Not available'],
    ['Operational Ambulance Rate (<95%)', 'Daily agreed vs actual operational fleet count', 'Not available'],
    ['Medicine/Consumables Expiry/Absence', 'Ambulance inspection/audit records', 'Not available'],
    ['Equipment Non-functioning/Absence', 'Ambulance technical audit records', 'Not available'],
    ['Vehicle Downtime (>36 days/year)', 'Vehicle maintenance / off-road logs', 'Not available'],
    ['Total Average Handling Time (AHT)', 'Call End timestamp / Duration logs', 'Not available'],
    ['Pre-Hospital Care %', 'Clinical care records / Patient Outcome Data', 'Not available'],
    ['Patient Satisfaction', 'Post-trip feedback / Grievances registered', 'Not available'],
]

# ─────────────────────────────────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="108 Ambulance KPI Dashboard",
    layout="wide",
    page_icon=None
)

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .coverage-banner {
        background: linear-gradient(90deg, #1a1a2e 0%, #16213e 100%);
        border-left: 4px solid #0f3460;
        border-radius: 6px;
        padding: 10px 16px;
        margin-bottom: 12px;
        color: #e0e0e0;
        font-size: 0.88rem;
    }
    .coverage-banner span.label  { color: #a0aec0; }
    .coverage-banner span.value  { color: #63b3ed; font-weight: 600; }
    .coverage-banner span.arrow  { color: #68d391; margin: 0 6px; }
    .confidence-badge {
        display: inline-block;
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 2px;
    }
    .kpi-note {
        font-size: 0.78rem;
        color: #718096;
        margin-top: -8px;
        margin-bottom: 6px;
    }
    div[data-testid="metric-container"] {
        background: #0d1117;
        border: 1px solid #21262d;
        border-radius: 8px;
        padding: 12px 16px;
    }
</style>
""", unsafe_allow_html=True)

st.title("108 Ambulance KPI Dashboard")
st.markdown(
    "Upload **Raw Data** and **Call Hits** Excel files — the SQL correlation "
    "engine will match calls to trips, then use the filters to slice insights."
)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Load raw Excel files (minimal preprocessing)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_files(raw_file, hits_file):
    """
    Read both uploads (supports .xlsx and .csv). Only fixes the 'Distict' typo in RawData.
    """
    if raw_file.name.endswith('.csv'):
        raw_df = pd.read_csv(raw_file)
    else:
        raw_df = pd.read_excel(raw_file)
        
    if hits_file.name.endswith('.csv'):
        hits_df = pd.read_csv(hits_file)
    else:
        hits_df = pd.read_excel(hits_file)

    raw_df  = raw_df.rename(columns={'Distict': 'District'}, errors='ignore')
    return raw_df, hits_df


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Run SQL correlation engine (cached — only re-runs if files change)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def run_sql_correlation(raw_file, hits_file):
    """
    Wraps sql_engine.run_correlation() with Streamlit caching.
    Returns correlated_df (one row per call) + post-processed columns.
    """
    raw_df, hits_df = load_files(raw_file, hits_file)
    corr = sql_engine.run_correlation(raw_df, hits_df)

    # Parse Call_Start_Time back to datetime for filtering
    corr['Call_Date'] = pd.to_datetime(corr['Call_Start_Time'], errors='coerce').dt.date

    # Numeric casts
    for col in ['Response_Time_Mins', 'Scene_Arrival_TAT_Mins',
                'Abs_Time_Gap_Mins', 'Time_Gap_Mins']:
        corr[col] = pd.to_numeric(corr[col], errors='coerce')

    for col in ['Is_Eligible', 'Urban_SLA_Met', 'Rural_SLA_Met',
                'Urban_ART_Met', 'Rural_ART_Met',
                'Total_Calls_From_Phone', 'Candidate_Match_Count']:
        corr[col] = pd.to_numeric(corr[col], errors='coerce').fillna(0).astype(int)

    if 'AHT_Secs' in corr.columns:
        corr['AHT_Secs'] = pd.to_numeric(corr['AHT_Secs'], errors='coerce')

    # Remove implausible response times (data errors)
    corr.loc[
        (corr['Response_Time_Mins'] <= 0) | (corr['Response_Time_Mins'] > 300),
        'Response_Time_Mins'
    ] = np.nan

    # Disease categorization — map raw values to clinical categories
    if 'Disease' in corr.columns:
        corr['Disease_Category'] = corr['Disease'].apply(categorize_disease)

    return corr


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Build district scorecard from filtered correlated_df
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def build_district_scorecard(corr_df: pd.DataFrame, viewing_days: int) -> pd.DataFrame:
    """
    Aggregates the correlation-aware correlated_df into a per-district
    KPI scorecard table.
    """
    # Grouping helpers
    g = corr_df.groupby('Final_District')
    
    # --- VOLUME METRICS (Using nunique to handle multi-trip rows from 'Maar Peet' logic) ---
    total_calls       = g['Call_ID'].nunique().rename('Total Calls')
    avg_calls_per_day = (total_calls / max(viewing_days, 1)).round(1).rename('Avg Calls/Day')
    
    eligible_calls    = corr_df[corr_df['Is_Eligible'] == 1].groupby('Final_District')['Call_ID'].nunique().rename('Eligible Calls')
    
    served_calls      = corr_df[corr_df['Service_Status'] == 'Served'].groupby('Final_District')['Call_ID'].nunique().rename('Served Calls')
    
    eligible_served   = corr_df[(corr_df['Is_Eligible'] == 1) & (corr_df['Service_Status'] == 'Served')].groupby('Final_District')['Call_ID'].nunique().rename('Eligible Served')
    
    emergency_calls   = corr_df[corr_df['Agent_Disposition'] == 'EmergencyCall'].groupby('Final_District')['Call_ID'].nunique().rename('Emergency Calls')
    emergency_served  = corr_df[(corr_df['Agent_Disposition'] == 'EmergencyCall') & (corr_df['Service_Status'] == 'Served')].groupby('Final_District')['Call_ID'].nunique().rename('Emergency Served')
    
    # Served Trips (Actual unique Case IDs handled - including multiple per call)
    # Using Trip_District for trip volume, fallback to Final_District
    dist_trips        = corr_df.dropna(subset=['Case_ID']).groupby('Final_District')['Case_ID'].nunique().rename('Served Trips')
    urban_trips       = corr_df[corr_df['Location_Category'] == 'Urban'].dropna(subset=['Case_ID']).groupby('Final_District')['Case_ID'].nunique().rename('Urban Trips')
    rural_trips       = corr_df[corr_df['Location_Category'] == 'Rural'].dropna(subset=['Case_ID']).groupby('Final_District')['Case_ID'].nunique().rename('Rural Trips')
    unknown_loc_trips = corr_df[corr_df['Location_Category'] == 'Unknown'].dropna(subset=['Case_ID']).groupby('Final_District')['Case_ID'].nunique().rename('Unknown Loc Trips')
    
    # --- PERFORMANCE METRICS ---
    # Location masks
    urban_mask = (corr_df['Location_Category'] == 'Urban') & corr_df['Response_Time_Mins'].notna()
    rural_mask = (corr_df['Location_Category'] == 'Rural') & corr_df['Response_Time_Mins'].notna()

    # ART Compliance (Counts) - Urban <= 25m, Rural <= 40m
    overall_art_count = (corr_df['Urban_ART_Met'] + corr_df['Rural_ART_Met']).groupby(corr_df['Final_District']).sum().astype(int).rename('ART Met (Total)')
    p90_art           = g['Response_Time_Mins'].quantile(0.9).round(2).rename('P90 ART (mins)')
    
    urban_art_count = corr_df[urban_mask].groupby('Final_District')['Urban_ART_Met'].sum().astype(int).rename('Urban ART Met (Count)')
    rural_art_count = corr_df[rural_mask].groupby('Final_District')['Rural_ART_Met'].sum().astype(int).rename('Rural ART Met (Count)')

    # SLA Compliance (Counts)
    urban_sla_count = corr_df[urban_mask].groupby('Final_District')['Urban_SLA_Met'].sum().astype(int).rename('Urban SLA Met (Count)')
    rural_sla_count = corr_df[rural_mask].groupby('Final_District')['Rural_SLA_Met'].sum().astype(int).rename('Rural SLA Met (Count)')

    # --- AMBULANCE METRICS ---
    served_only = corr_df[corr_df['Service_Status'] == 'Served']
    if 'Vehicle_No' in served_only.columns:
        active_ambs = served_only.groupby('Final_District')['Vehicle_No'].nunique().rename('Active Ambulances')
        trips_per_veh = (dist_trips / active_ambs.replace(0, np.nan) / max(viewing_days, 1)).round(2).rename('Trips/Vehicle/Day')
    else:
        active_ambs = pd.Series(0, index=total_calls.index, name='Active Ambulances')
        trips_per_veh = pd.Series(0, index=total_calls.index, name='Trips/Vehicle/Day')

    # --- KPI CALCULATIONS ---
    # Conversion %: (Eligible calls that received a dispatched trip) / (Total Eligible Calls)
    elig_conversion_pct = (eligible_served / eligible_calls.replace(0, np.nan) * 100).round(2).rename('Eligible Conversion %')
    emerg_conversion_pct = (emergency_served / emergency_calls.replace(0, np.nan) * 100).round(2).rename('Emergency Conversion %')

    if 'AHT_Secs' in corr_df.columns:
        aht_secs = g['AHT_Secs'].mean().round(1).rename('AHT (secs)')
    else:
        aht_secs = pd.Series(np.nan, index=total_calls.index, name='AHT (secs)')

    # --- CONFIDENCE METRICS ---
    high_conf = (corr_df['Match_Confidence'] == 'High').groupby(corr_df['Final_District']).sum().rename('High Confidence')
    med_conf  = (corr_df['Match_Confidence'] == 'Medium').groupby(corr_df['Final_District']).sum().rename('Med Confidence')

    # --- COMBINE ---
    dist_df = pd.concat([
        total_calls, avg_calls_per_day, emergency_calls, emergency_served, eligible_calls, served_calls, dist_trips,
        urban_trips, rural_trips, unknown_loc_trips,
        elig_conversion_pct, emerg_conversion_pct, aht_secs, active_ambs, trips_per_veh,
        overall_art_count, p90_art, urban_art_count, rural_art_count,
        urban_sla_count, rural_sla_count, high_conf, med_conf
    ], axis=1).fillna(0).reset_index().rename(columns={'index': 'District', 'Final_District': 'District'})

    return dist_df.sort_values('Total Calls', ascending=False)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Daily trend from correlated_df
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def build_daily_trend(corr_df: pd.DataFrame) -> pd.DataFrame:
    trend = corr_df.groupby('Call_Date').agg(
        Total_Calls=('Call_ID', 'count'),
        Served_Calls=('Service_Status', lambda x: (x == 'Served').sum()),
        ART=('Response_Time_Mins', 'mean'),
    ).reset_index()
    trend['ART'] = trend['ART'].round(2)
    trend['Call_Date'] = trend['Call_Date'].astype(str)
    return trend


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — File Upload
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.header("Upload Data Files")
st.sidebar.caption("Upload RawData + CallHits (.xlsx or .csv)")

raw_data_file  = st.sidebar.file_uploader("Raw Data (Trip Details)",      type=["xlsx", "csv"], key="raw")
call_hits_file = st.sidebar.file_uploader("Call Hits (Dispatch Details)", type=["xlsx", "csv"], key="hits")

if st.sidebar.button("🔄 Clear Cache & Reload"):
    st.cache_data.clear()
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Main App
# ─────────────────────────────────────────────────────────────────────────────
if raw_data_file and call_hits_file:
    try:
        with st.spinner("Running SQL correlation engine — this may take ~30s for large files..."):
            corr_df = run_sql_correlation(raw_data_file, call_hits_file)

        if len(corr_df) == 0:
            st.error("Correlation returned 0 rows. Check that Phone Number and timestamp columns are present.")
            st.stop()

        # ── Date range from correlated data ───────────────────────────────────
        valid_date_series = pd.to_datetime(corr_df['Call_Start_Time'], errors='coerce').dropna()
        if valid_date_series.empty:
            st.error("Error: Could not parse any valid Call Start Time dates.")
            st.stop()
            
        file_min_date = valid_date_series.min().date()
        file_max_date = valid_date_series.max().date()
        num_days_in_file = (file_max_date - file_min_date).days + 1

        # ── Sidebar Filters ───────────────────────────────────────────────────
        st.sidebar.markdown("---")
        st.sidebar.header("Filters")

        all_districts = sorted(corr_df['Final_District'].dropna().unique().tolist())
        selected_district = st.sidebar.selectbox("District", ["All Districts"] + all_districts)

        st.sidebar.caption(
            f"File covers **{file_min_date}** to **{file_max_date}** "
            f"({num_days_in_file} day{'s' if num_days_in_file > 1 else ''})"
        )
        selected_date_range = st.sidebar.date_input(
            "Select Date Range",
            value=[file_min_date, file_max_date],
            min_value=file_min_date,
            max_value=file_max_date,
        )

        # ── Apply Filters ─────────────────────────────────────────────────────
        fc = corr_df.copy()

        if selected_district != "All Districts":
            fc = fc[fc['Final_District'] == selected_district]

        if len(selected_date_range) == 2:
            start_date, end_date = selected_date_range
        else:
            start_date = end_date = selected_date_range[0]

        fc = fc[(fc['Call_Date'] >= start_date) & (fc['Call_Date'] <= end_date)]

        # ── Coverage Banner ───────────────────────────────────────────────────
        viewing_days   = (end_date - start_date).days + 1
        district_label = selected_district if selected_district != "All Districts" else "All Districts"
        date_label     = f"{start_date} → {end_date}" if start_date != end_date else str(start_date)

        st.markdown(f"""
        <div class="coverage-banner">
            <span class="label">File coverage: </span>
            <span class="value">{file_min_date} to {file_max_date}</span>
            &nbsp;&nbsp;|&nbsp;&nbsp;
            <span class="label">Viewing: </span>
            <span class="value">{date_label}</span>
            <span class="arrow">({viewing_days} day{'s' if viewing_days > 1 else ''})</span>
            &nbsp;&nbsp;|&nbsp;&nbsp;
            <span class="label">District: </span>
            <span class="value">{district_label}</span>
        </div>
        """, unsafe_allow_html=True)

        # ── KPI Summary Row ───────────────────────────────────────────────────
        st.markdown("---")
        st.header("Key Performance Indicators")

        total_calls      = len(fc)
        served_calls     = (fc['Service_Status'] == 'Served').sum()
        eligible_calls   = (fc['Is_Eligible'] == 1).sum()
        served_trips     = fc['Case_ID'].dropna().nunique()            # unique trip case IDs
        elig_not_served  = ((fc['Is_Eligible'] == 1) & (fc['Service_Status'] == 'Not Served')).sum()
        valid_rt         = fc['Response_Time_Mins'].dropna()
        art              = valid_rt.mean()

        # Conversion %: Eligible calls that got a served trip
        elig_served_n    = ((fc['Is_Eligible'] == 1) & (fc['Service_Status'] == 'Served')).sum()
        elig_conversion_pct   = (elig_served_n / max(eligible_calls, 1)) * 100
        
        emergency_calls_n = (fc['Agent_Disposition'] == 'EmergencyCall').sum()
        emergency_served_n = ((fc['Agent_Disposition'] == 'EmergencyCall') & (fc['Service_Status'] == 'Served')).sum()
        emerg_conversion_pct = (emergency_served_n / max(emergency_calls_n, 1)) * 100

        # Avg calls per day — show both total and eligible
        avg_total_per_day   = total_calls   / max(viewing_days, 1)
        avg_elig_per_day    = eligible_calls / max(viewing_days, 1)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Calls",          f"{total_calls:,}")
        c2.metric("Eligible Calls",       f"{eligible_calls:,}",
                  delta=f"{avg_elig_per_day:.0f}/day", delta_color="off")
        c3.metric("Served Calls",         f"{served_calls:,}")
        c4.metric("Served Trips",         f"{served_trips:,}",
                  help="Unique Case IDs dispatched (1 call can yield multiple trips)")
        art_met_n        = (fc['Urban_ART_Met'] + fc['Rural_ART_Met']).sum()
        c5.metric("ART Met (Calls)", f"{art_met_n:,}", help="Total calls within target (Urban <=25m, Rural <=40m)")

        # NEW: Second KPI row — P90 RT, Genuine Emergency %, Ambulance Utilization
        p90_rt = valid_rt.quantile(0.9) if len(valid_rt) > 0 else np.nan
        genuine_emergency = (
            fc['Agent_Disposition'].isin(['EmergencyCall', 'InterFacilityTransfer',
                                          'NonEmergencyCall', 'InterState'])
        ).sum()
        genuine_pct = (genuine_emergency / max(total_calls, 1) * 100)

        # Ambulance utilization: unique trips per unique vehicle per day
        served_fc_util = fc[fc['Service_Status'] == 'Served']
        if 'Vehicle_No' in served_fc_util.columns and len(served_fc_util) > 0:
            unique_vehicles = served_fc_util['Vehicle_No'].dropna().nunique()
            trips_per_vehicle = served_calls / max(unique_vehicles, 1)
            trips_per_veh_day = trips_per_vehicle / max(viewing_days, 1)
        else:
            unique_vehicles = 0
            trips_per_veh_day = 0

        # AHT calculation
        if 'AHT_Secs' in fc.columns:
            aht_valid = fc['AHT_Secs'].dropna()
            aht_mean_secs = aht_valid.mean()
            if pd.notnull(aht_mean_secs):
                aht_str = f"{aht_mean_secs/60:.1f} min"
            else:
                aht_str = "N/A"
        else:
            aht_str = "N/A"

        d1, d2, d3, d4, d5, d6 = st.columns(6)
        d1.metric("P90 Response Time", f"{p90_rt:.2f} min" if pd.notnull(p90_rt) else "N/A")
        d2.metric("Avg Handling Time", aht_str, help="Agent Talk + Wrap Time (excludes IVR/Queue)")
        d3.metric("Emergency Conv. %",
                  f"{emerg_conversion_pct:.1f}%",
                  delta="Emerg. Served / Emerg. Calls", delta_color="off")
        d4.metric("Ambulances Active", f"{unique_vehicles:,}")
        d5.metric("Trips/Vehicle/Day", f"{trips_per_veh_day:.2f}")
        d6.metric("Eligible Conv. %",
                  f"{elig_conversion_pct:.1f}%",
                  delta="Served / Eligible Calls", delta_color="off")

        st.markdown(
            '<p class="kpi-note">'
            'ART Met = Calls within target (Urban <=25m, Rural <=40m)  |  '
            'AHT = Call End Time - Call Connect Time  |  '
            'Conversion % = Eligible Served / Total Eligible  |  '
            'P90 = 90th percentile response time  |  '
            'Match window: ±90 min  |  '
            'Outliers (≤0 or &gt;300 min) excluded</p>',
            unsafe_allow_html=True
        )

        # ── Match Confidence Row ──────────────────────────────────────────────
        st.markdown("---")
        st.subheader("SQL Correlation Match Quality")
        st.caption(
            "Based on the time gap between call and matched trip (±90 min window). "
            "High = ≤60 min gap, Medium = ≤90 min. Low matches eliminated by window reduction."
        )

        high_ct   = (fc['Match_Confidence'] == 'High').sum()
        med_ct    = (fc['Match_Confidence'] == 'Medium').sum()
        low_ct    = (fc['Match_Confidence'] == 'Low').sum()
        no_match  = (fc['Match_Confidence'] == 'No Match').sum()

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("High Confidence Matches",   f"{high_ct:,}",
                   delta=f"{high_ct/max(total_calls,1)*100:.1f}% of calls", delta_color="normal")
        mc2.metric("Medium Confidence Matches", f"{med_ct:,}",
                   delta=f"{med_ct/max(total_calls,1)*100:.1f}% of calls", delta_color="off")
        mc3.metric("Low Confidence Matches",    f"{low_ct:,}",
                   delta=f"{low_ct/max(total_calls,1)*100:.1f}% of calls", delta_color="inverse")
        mc4.metric("Unmatched Calls",           f"{no_match:,}",
                   delta=f"{no_match/max(total_calls,1)*100:.1f}% of calls", delta_color="inverse")

        # ── SLAs + Case Distribution ──────────────────────────────────────────
        st.markdown("---")
        col_left, col_right = st.columns([1.2, 1])

        with col_left:
            st.subheader("Response Time SLAs")
            served_fc = fc[fc['Service_Status'] == 'Served']

            urban_cases = served_fc[served_fc['Location_Category'] == 'Urban'].dropna(subset=['Response_Time_Mins'])
            rural_cases = served_fc[served_fc['Location_Category'] == 'Rural'].dropna(subset=['Response_Time_Mins'])

            if len(urban_cases) > 0 or len(rural_cases) > 0:
                urban_art_val = urban_cases['Response_Time_Mins'].mean()
                rural_art_val = rural_cases['Response_Time_Mins'].mean()

                ca1, ca2 = st.columns(2)
                ca1.metric(
                    "Urban ART Met (Calls)",
                    f"{int(urban_cases['Urban_ART_Met'].sum()):,}",
                    delta=f"{urban_cases['Urban_ART_Met'].sum()/max(len(urban_cases), 1)*100:.1f}% of Urban",
                    delta_color="normal"
                )
                ca2.metric(
                    "Rural ART Met (Calls)",
                    f"{int(rural_cases['Rural_ART_Met'].sum()):,}",
                    delta=f"{rural_cases['Rural_ART_Met'].sum()/max(len(rural_cases), 1)*100:.1f}% of Rural",
                    delta_color="normal"
                )

                st.markdown("<br>", unsafe_allow_html=True)

                urban_sla_pct = urban_cases['Urban_SLA_Met'].sum() / max(len(urban_cases), 1) * 100
                rural_sla_pct = rural_cases['Rural_SLA_Met'].sum() / max(len(rural_cases), 1) * 100

                cs1, cs2 = st.columns(2)
                cs1.metric("Urban SLA Met (Calls)", f"{int(urban_cases['Urban_SLA_Met'].sum()):,}")
                cs1.caption(f"Target: <=15m | Total: {len(urban_cases):,} | {urban_sla_pct:.1f}% met")

                cs2.metric("Rural SLA Met (Calls)", f"{int(rural_cases['Rural_SLA_Met'].sum()):,}")
                cs2.caption(f"Target: <=30m | Total: {len(rural_cases):,} | {rural_sla_pct:.1f}% met")

                st.markdown("<br>", unsafe_allow_html=True)
                
                # Breakdown
                st.markdown("**ART / SLA Pass-Fail Breakdown**")
                st.markdown(f"""
                - **Urban SLA (<=15m):** {int(urban_cases['Urban_SLA_Met'].sum())} Met &nbsp;|&nbsp; {len(urban_cases) - int(urban_cases['Urban_SLA_Met'].sum())} Missed
                - **Rural SLA (<=30m):** {int(rural_cases['Rural_SLA_Met'].sum())} Met &nbsp;|&nbsp; {len(rural_cases) - int(rural_cases['Rural_SLA_Met'].sum())} Missed
                - **Urban ART (<=25m):** {(urban_cases['Response_Time_Mins'] <= 25).sum()} Met &nbsp;|&nbsp; {(urban_cases['Response_Time_Mins'] > 25).sum()} Missed
                - **Rural ART (<=40m):** {(rural_cases['Response_Time_Mins'] <= 40).sum()} Met &nbsp;|&nbsp; {(rural_cases['Response_Time_Mins'] > 40).sum()} Missed
                """, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                st.markdown("**Call → Trip Conversion**")
                
                st.progress(min(emerg_conversion_pct / 100, 1.0))
                st.caption(f"**Emergency**: {emerg_conversion_pct:.2f}% — {emergency_served_n:,} served from {emergency_calls_n:,} Emergency calls")
                
                st.progress(min(elig_conversion_pct / 100, 1.0))
                st.caption(f"**Eligible**: {elig_conversion_pct:.2f}% — {elig_served_n:,} served from {eligible_calls:,} Eligible calls")
            else:
                st.warning("No served + location-typed cases for this selection.")

        with col_right:
            st.subheader("Case Type Distribution (Categorized)")
            if 'Disease_Category' in fc.columns:
                cat_col = fc['Disease_Category'].dropna()
                cat_col = cat_col[cat_col != 'Unknown']
                total_d = len(cat_col)
                if total_d > 0:
                    cat_counts = cat_col.value_counts().reset_index()
                    cat_counts.columns = ['Category', 'Count']
                    cat_counts['%'] = (cat_counts['Count'] / total_d * 100).round(1)
                    st.dataframe(cat_counts, height=280, use_container_width=True)
                    # Coverage metric
                    mapped = (fc['Disease_Category'] != 'Other / Unknown') & (fc['Disease_Category'] != 'Unknown')
                    mapped_pct = mapped.sum() / max(len(fc), 1) * 100
                    st.caption(f"Categorization coverage: {mapped_pct:.1f}% of served calls mapped to clinical categories")
                else:
                    st.info("No disease data for this selection.")
            elif 'Disease' in fc.columns:
                disease_col = fc['Disease'].dropna()
                disease_col = disease_col[~disease_col.isin(['Other', 'other', 'Unknown', 'nan', 'None'])]
                total_d = len(disease_col)
                if total_d > 0:
                    case_counts = disease_col.value_counts().head(15)
                    case_pct = (case_counts / total_d * 100).round(2).reset_index()
                    case_pct.columns = ['Case Type', 'Percentage (%)']
                    st.dataframe(case_pct, height=280, use_container_width=True)
                else:
                    st.info("No disease data for this selection.")
            else:
                st.info("'DISEASE' column not found in Raw Data.")

            st.markdown("<br>", unsafe_allow_html=True)
            st.subheader("Call Disposition Breakdown")
            if 'Agent_Disposition' in fc.columns:
                disp_col = fc['Agent_Disposition'].dropna()
                total_disp = len(disp_col)
                if total_disp > 0:
                    disp_counts = disp_col.value_counts().reset_index()
                    disp_counts.columns = ['Disposition', 'Count']
                    disp_counts['%'] = (disp_counts['Count'] / total_disp * 100).round(1)
                    st.dataframe(disp_counts, height=200, use_container_width=True)
                else:
                    st.info("No disposition data available.")

        # ── Day-wise Trend ────────────────────────────────────────────────────
        if viewing_days > 1:
            st.markdown("---")
            st.header(f"Day-wise Trend ({start_date} to {end_date})")
            trend_df = build_daily_trend(fc)

            if len(trend_df) > 1:
                t1, t2, t3 = st.columns(3)
                with t1:
                    st.markdown("**Daily Calls Received**")
                    st.line_chart(trend_df[['Call_Date', 'Total_Calls']].dropna().set_index('Call_Date'), use_container_width=True)
                with t2:
                    st.markdown("**Daily Served Trips**")
                    st.line_chart(trend_df[['Call_Date', 'Served_Calls']].dropna().set_index('Call_Date'), use_container_width=True)
                with t3:
                    st.markdown("**Daily Avg Response Time (min)**")
                    st.line_chart(trend_df[['Call_Date', 'ART']].dropna().set_index('Call_Date'), use_container_width=True)

                with st.expander("View Day-wise Data Table"):
                    st.dataframe(
                        trend_df.rename(columns={
                            'Call_Date': 'Date',
                            'Total_Calls': 'Total Calls',
                            'Served_Calls': 'Served Trips',
                            'ART': 'Avg Response Time (min)'
                        }),
                        use_container_width=True
                    )
            else:
                st.info("Not enough day-wise data to plot a trend.")

        # ── District Scorecard ────────────────────────────────────────────────
        st.markdown("---")
        st.header("District-wise Performance Scorecard")
        st.caption(
            f"Correlation-aware KPIs | {date_label} | {district_label} — "
            "Match quality breakdown included."
        )

        if all_districts:
            dist_df = build_district_scorecard(fc, viewing_days)

            if len(dist_df) > 0:
                st.dataframe(
                    dist_df.style.format(
                        {
                            'Avg Calls/Day':      '{:.1f}',
                            'Eligible Conversion %': '{:.2f}%',
                            'Emergency Conversion %': '{:.2f}%',
                            'Service Coverage %': '{:.2f}%',
                            'Active Ambulances':  '{:.0f}',
                            'Trips/Vehicle/Day':  '{:.2f}',
                            'ART Met (Total)':    '{:,}',
                            'Urban ART Met (Count)': '{:,}',
                            'Rural ART Met (Count)': '{:,}',
                            'Avg Urban Delay (mins)': '{:.2f}',
                            'Avg Rural Delay (mins)': '{:.2f}',
                            'Urban SLA Met (Count)': '{:,}',
                            'Rural SLA Met (Count)': '{:,}',
                        },
                        na_rep='—'
                    ),
                    use_container_width=True,
                    height=450,
                )

                buffer = io.BytesIO()
                dl_df = dist_df.copy().reset_index(drop=True)
                dl_df.index = dl_df.index + 1
                with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                    # Sheet 1: District Scorecard
                    dl_df.to_excel(
                        writer, index=True, index_label='S.No.',
                        sheet_name='District Scorecard'
                    )
                    
                    # Sheet 2: Day-wise Trend
                    try:
                        exp_trend_df = build_daily_trend(fc)
                        if len(exp_trend_df) > 0:
                            exp_trend_df.index = exp_trend_df.index + 1
                            exp_trend_df.to_excel(writer, index=True, index_label='S.No.', sheet_name='Day-wise Trend')
                    except Exception:
                        pass
                        
                    # Sheet 3: Call Disposition Breakdown
                    try:
                        if 'Agent_Disposition' in fc.columns:
                            exp_disp_col = fc['Agent_Disposition'].dropna()
                            if len(exp_disp_col) > 0:
                                exp_disp_counts = exp_disp_col.value_counts().reset_index()
                                exp_disp_counts.columns = ['Disposition', 'Count']
                                exp_disp_counts['%'] = (exp_disp_counts['Count'] / len(exp_disp_col) * 100).round(1)
                                exp_disp_counts.index = exp_disp_counts.index + 1
                                exp_disp_counts.to_excel(writer, index=True, index_label='S.No.', sheet_name='Call Disposition Breakdown')
                    except Exception:
                        pass
                        
                    # Sheet 4: Required data for remaining KPIs
                    req_df = pd.DataFrame(
                        REQUIRED_DATA_FOR_REMAINING_KPIS,
                        columns=['KPI', 'Required Data', 'Status']
                    )
                    req_df.index = req_df.index + 1
                    req_df.to_excel(
                        writer, index=True, index_label='S.No.',
                        sheet_name='Remaining KPIs Requirements'
                    )

                st.download_button(
                    label="📥 Download Detailed Reports as Excel",
                    data=buffer.getvalue(),
                    file_name=f"District_KPI_{start_date}_to_{end_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.info("No district data for this filter combination.")

    except Exception as e:
        st.error(f"Error: {e}")
        st.exception(e)

else:
    st.markdown("---")
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        st.info(
            "**How to use this dashboard:**\n\n"
            "1. Upload **Raw Data** (Trip Details) file\n"
            "2. Upload **Call Hits** (Dispatch Details) file\n"
            "3. The SQL engine matches calls to trips automatically\n"
            "4. Use **Date Range** and **District** filters to slice data"
        )
    with col_info2:
        st.success(
            "**Powered by SQL Correlation Engine (v3):**\n\n"
            "- Phone + time-proximity matching (±90 min window)\n"
            "- Smart trip deduplication (road accident safe)\n"
            "- Disposition normalization (merges duplicates)\n"
            "- Disease categorization (10 clinical categories)\n"
            "- High / Medium confidence scoring\n"
            "- SLA flags + P90 response time"
        )
