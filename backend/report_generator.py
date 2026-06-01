import pandas as pd
import numpy as np
import io
import re
import datetime
import warnings
import sql_engine

# --- STRICT EQUIPMENT CONFIGURATIONS ---
EQUIPMENTS_BLS = [
    'Cervical Collar', 'D Type Oxygen Cylinder', 'Defibrillator Cum Cardiac Monitor',
    'Double Head Immobilizer', 'EMT Shears', 'Endotracheal Tube (Uncuffed)',
    'Flowmeter', 'Glucometer', 'Guaze Cutter', 'Humidifier Bottel', 'Kidney Tray',
    'Laryngoscope', 'Margils Forcep', 'Multipara Monitor with Neonatal & Paediatric modes and attachment',
    'Nebulizer Machine', 'Needle cum Syringe Destroyer.', 'Pneumatic Splints',
    'Portable Oxygen Cylinder', 'Pulse Oximeter', 'Rescue Equipment', 'Rescue Shears',
    'Scoop Stretcher', 'Search Light', 'Spine Board', 'Stethoscope', 'Suction Machine (Electric)',
    'Suction Machine (Hand Held)', 'Syringe Pump', 'Thermometer (Digital)', 'Toothed Forceps',
    'Tranport Incubator'
]

EQUIPMENTS_ALS = EQUIPMENTS_BLS + [
    'Artery Forceps', 'Artificial Manual Breathing unit', 'Auto Loader - Collapsible stretcher',
    'B Type Oxygen Cylinder'
]

EQUIPMENTS_NEONATAL = EQUIPMENTS_ALS + [
    'Transport Ventilator (Portable)', 'Wheel Chair'
]

TYPO_CORRECTIONS = {
    "JH01FL0390": "JH01FL0396",
    "JH01FL3802": "JH01FL3082"
}

def clean_vehicle_number(val):
    if pd.isna(val):
        return ""
    clean = re.sub(r'[^A-Z0-9]', '', str(val).upper().strip())
    return TYPO_CORRECTIONS.get(clean, clean)

def _get_applicable_equipments(v_type):
    v_type_str = str(v_type).upper().strip()
    if 'NEO' in v_type_str:
        return EQUIPMENTS_NEONATAL
    elif 'ALS' in v_type_str:
        return EQUIPMENTS_ALS
    else:
        return EQUIPMENTS_BLS

def generate_excel(master_df: pd.DataFrame, raw_df: pd.DataFrame, eq_df: pd.DataFrame, calls_df: pd.DataFrame, hoto_only: bool = False) -> tuple[bytes, str]:
    """Core KPI report generator producing detailed vehicle, daily call, and district summary sheets."""
    # 1. Run Correlation
    corr_df = sql_engine.run_correlation(raw_df, calls_df)
    
    if hoto_only:
        hoto_vehicles = set()
        master_clean_col = 'Registration No.'
        
        # Scan master_df columns dynamically to be extremely robust
        for col in master_df.columns:
            if 'registration' in str(col).lower() or 'reg' in str(col).lower():
                master_clean_col = col
                break
                
        hoto_col = None
        for col in master_df.columns:
            if 'hoto' in str(col).lower():
                hoto_col = col
                break
                
        for idx, row in master_df.iterrows():
            reg_clean = clean_vehicle_number(row.get(master_clean_col, ''))
            if hoto_col:
                hoto_val = str(row.get(hoto_col, '')).strip().upper()
            else:
                hoto_val = str(row.get('HOTO Status', row.get('HOTO or not', ''))).strip().upper()
                
            if hoto_val in ('YES', 'HOTO', 'Y') and reg_clean:
                hoto_vehicles.add(reg_clean)
                
        # Filter master_df
        if master_clean_col in master_df.columns:
            master_df = master_df[master_df[master_clean_col].apply(clean_vehicle_number).isin(hoto_vehicles)]
            
        # Filter raw_df
        if 'Vehicle No' in raw_df.columns:
            raw_df = raw_df[raw_df['Vehicle No'].apply(clean_vehicle_number).isin(hoto_vehicles)]
            
        # Filter corr_df
        if 'Vehicle_No' in corr_df.columns:
            corr_df = corr_df[corr_df['Vehicle_No'].apply(clean_vehicle_number).isin(hoto_vehicles)]
    
    # 2. Clean Equipment Vehicle columns
    eq = eq_df.copy()
    veh_cols = [c for c in eq.columns if 'VEHICLE NUMBER' in c]
    
    def merge_veh_cols(row):
        for col in veh_cols:
            val = str(row.get(col)).strip()
            if val and val != 'nan' and val != 'None' and val != '':
                return clean_vehicle_number(val)
        return ""
        
    eq['Clean_Vehicle_No'] = eq.apply(merge_veh_cols, axis=1)
    eq = eq[eq['Clean_Vehicle_No'] != ""]
    
    if hoto_only:
        eq = eq[eq['Clean_Vehicle_No'].isin(hoto_vehicles)]
    
    # Sort by timestamp and keep LATEST audit per vehicle
    if 'Timestamp' in eq.columns:
        eq['Timestamp'] = pd.to_datetime(eq['Timestamp'], errors='coerce')
        eq = eq.sort_values('Timestamp').groupby('Clean_Vehicle_No').last().reset_index()
    else:
        eq = eq.groupby('Clean_Vehicle_No').last().reset_index()
        
    eq_dict = eq.set_index('Clean_Vehicle_No').to_dict('index')
    
    # 3. Process Sheet 1: Ambulances (Vehicle Level)
    amb_rows = []
    
    # Preprocess Raw Trips for speed
    raw = raw_df.copy()
    raw['Clean_Vehicle_No'] = raw['Vehicle No'].apply(clean_vehicle_number)
    
    # Date Range of dataset
    raw['Parsed_Date'] = pd.to_datetime(raw['Date'], errors='coerce')
    min_date = raw['Parsed_Date'].min()
    max_date = raw['Parsed_Date'].max()
    all_dates = pd.date_range(start=min_date, end=max_date) if pd.notna(min_date) and pd.notna(max_date) else []
    total_days = max(len(all_dates), 1)
    
    # Pre-aggregate Raw Distance, Trips, Dispatch Time, etc. for quick lookup
    raw['Start_ODO'] = pd.to_numeric(raw['Base Start ODO'], errors='coerce')
    raw['End_ODO'] = pd.to_numeric(raw['Base End ODO'], errors='coerce')
    raw['Trip_Distance'] = (raw['End_ODO'] - raw['Start_ODO']).fillna(0)
    
    dispatch_sec = (pd.to_datetime(raw['assigned_time'], errors='coerce', dayfirst=False) - 
                           pd.to_datetime(raw['Agrent CONNECTED TIME'], errors='coerce', dayfirst=False)).dt.total_seconds()
    raw['Dispatch_Sec'] = np.where(dispatch_sec < -43200, dispatch_sec + 86400, np.where(dispatch_sec < 0, 0, dispatch_sec))
                           
    raw_grp = raw.groupby('Clean_Vehicle_No')
    trips_count_map = raw_grp.size().to_dict()
    distance_map = raw_grp['Trip_Distance'].sum().to_dict()
    
    # Calculate days-with-trips > 3 and days-with-trips = 0
    days_gt_3_map = {}
    days_zero_map = {}
    for veh, group in raw_grp:
        group_dates = group['Parsed_Date'].dt.date.value_counts()
        days_gt_3_map[veh] = (group_dates > 3).sum()
        days_zero_map[veh] = total_days - len(group_dates)
        
    avg_dispatch_map = raw_grp['Dispatch_Sec'].mean().to_dict()
    dispatch_gt_180_map = (raw['Dispatch_Sec'] > 180).groupby(raw['Clean_Vehicle_No']).sum().to_dict()
    
    # Correlated Trips Performance Aggregates
    corr_df['Clean_Vehicle_No'] = corr_df['Vehicle_No'].apply(clean_vehicle_number)
    corr_grp = corr_df.groupby('Clean_Vehicle_No')
    
    avg_resp_map = corr_grp['Response_Time_Mins'].mean().to_dict()
    
    # SLA Met calculations
    rural_sla_gt_30 = ((corr_df['Location_Category'] == 'Rural') & (corr_df['Response_Time_Mins'] > 30)).groupby(corr_df['Clean_Vehicle_No']).sum().to_dict()
    urban_sla_gt_15 = ((corr_df['Location_Category'] == 'Urban') & (corr_df['Response_Time_Mins'] > 15)).groupby(corr_df['Clean_Vehicle_No']).sum().to_dict()
    
    # Master fields maps
    master = master_df.copy()
    master['Clean_Vehicle_No'] = master['Registration No.'].apply(clean_vehicle_number)
    
    # Check what extra master columns are present, but we will explicitly guarantee these three!
    for idx, row in master.iterrows():
        reg = row['Clean_Vehicle_No']
        if not reg:
            continue
            
        v_type = row.get('Type of Vehicle', row.get('Vehicle Type', 'BLS'))
        district = row.get('District', 'Unknown')
        
        trips = trips_count_map.get(reg, 0)
        dist = distance_map.get(reg, 0.0)
        days_gt_3 = days_gt_3_map.get(reg, 0)
        days_zero = days_zero_map.get(reg, total_days if trips == 0 else total_days - 1)
        avg_disp = avg_dispatch_map.get(reg, np.nan)
        disp_gt_180 = dispatch_gt_180_map.get(reg, 0)
        avg_resp = avg_resp_map.get(reg, np.nan)
        rural_fail = rural_sla_gt_30.get(reg, 0)
        urban_fail = urban_sla_gt_15.get(reg, 0)
        
        # Equipment Audit Calculations
        eq_audit = eq_dict.get(reg)
        working, not_working, not_available = 0, 0, 0
        eq_update = 'Not Audited'
        health_pct = 0.0
        
        if eq_audit:
            eq_update = str(eq_audit.get('Timestamp', 'Audited'))[:10]
            applicable = _get_applicable_equipments(v_type)
            
            for item in applicable:
                val = str(eq_audit.get(item)).strip().lower()
                if 'not working' in val or 'malfunctioning' in val:
                    not_working += 1
                elif 'not available' in val or 'absent' in val:
                    not_available += 1
                elif 'working' in val or 'functional' in val:
                    working += 1
            
            tot = len(applicable)
            health_pct = (working / tot * 100) if tot > 0 else 0.0
            
        risk = "Not Audited"
        if eq_audit:
            if health_pct < 70.0:
                risk = f"High Risk ({health_pct:.1f}%) - {not_working + not_available} failed"
            elif health_pct < 90.0:
                risk = f"Medium Risk ({health_pct:.1f}%)"
            else:
                risk = f"Low Risk ({health_pct:.1f}%)"
                
        # Base Row
        amb_row = {
            'District': district,
            'Vehicle Number': row['Registration No.'],
            'Vehicle Type': v_type,
            'Trips Count': trips,
            'Total Distance Travelled': round(dist, 1),
            'No Of Days (>3 Trips)': days_gt_3,
            'No of Days 0 Trips': days_zero,
            'Average Dispatch Time': round(avg_disp, 1) if pd.notna(avg_disp) else 'N/A',
            'Count of Trip > 180 Sec Dispatch Time': disp_gt_180,
            'Average Response Time': round(avg_resp, 2) if pd.notna(avg_resp) else 'N/A',
            'Trips beyond Response Time(Rural)': rural_fail,
            'Trips beyond Response Time(Urban)': urban_fail,
            'Equipments Last Updated On': eq_update,
            'No Of Equipment - Working': working if eq_audit else 'N/A',
            'No Of Equipment – Not Working': not_working if eq_audit else 'N/A',
            'No Of Equipment – Not Available': not_available if eq_audit else 'N/A',
            'Equipment Health %': round(health_pct, 1) if eq_audit else 'N/A',
            'Equipment Risk Level': risk,
            
            # Explicit inclusion of 3 additional columns requested by user
            'GPS': row.get('GPS', 'N/A'),
            'Operational / Non-Operational': row.get('Operational / Non-Operational', row.get('Operational/Non Operational', 'N/A')),
            'HOTO Status': row.get('HOTO Status', row.get('HOTO or not', 'N/A'))
        }
        amb_rows.append(amb_row)
        
    amb_df = pd.DataFrame(amb_rows)
    
    # 4. Sheet 2: Calc_Data (Daily Call Summary - One row per date)
    daily_rows = []
    
    # Group Correlated Calls by Date
    corr_df['Parsed_Date'] = pd.to_datetime(corr_df['Call_Start_Time']).dt.date
    daily_grp = corr_df.groupby('Parsed_Date')
    
    for date, group in daily_grp:
        tot_calls = group['Call_ID'].nunique()
        avg_pickup = group['Call_Pickup_Time_Sec'].mean()
        tot_attended = (group['Service_Status'] == 'Served').sum()
        
        urban_sla = group['Urban_SLA_Met'].sum()
        rural_sla = group['Rural_SLA_Met'].sum()
        urban_art = group['Urban_ART_Met'].sum()
        rural_art = group['Rural_ART_Met'].sum()
        
        # Call Types Count
        group['Clinical_Category'] = group['Disease'].apply(sql_engine.run_correlation.__globals__.get('categorize_disease', lambda x: 'Other'))
        cat_counts = group['Clinical_Category'].value_counts()
        
        daily_row = {
            'Date': date,
            'Total Calls': tot_calls,
            'Avg Call Pickup Time (Sec)': round(avg_pickup, 1) if pd.notna(avg_pickup) else 0,
            'Total Calls Attended': tot_attended,
            'Calls Attended within 15 mins (Urban)': urban_sla,
            'Calls Attended within 30 mins (Rural)': rural_sla,
            'Calls Attended within 25 mins (Urban ART Met)': urban_art,
            'Calls Attended within 40 mins (Rural ART Met)': rural_art
        }
        
        # Add Disease Categories Columns
        from kpi_dashboard import DISEASE_CATEGORIES
        for cat in DISEASE_CATEGORIES.keys():
            daily_row[f'Call Type: {cat}'] = cat_counts.get(cat, 0)
            
        daily_rows.append(daily_row)
        
    daily_df = pd.DataFrame(daily_rows)
    if not daily_df.empty:
        daily_df = daily_df.sort_values('Date')
        
    # 5. Sheet 3: District Summary
    dist_rows = []
    if not amb_df.empty:
        # Group Ambulances by District
        amb_grp = amb_df.groupby('District')
        for dist, group in amb_grp:
            tot_v = group['Vehicle Number'].nunique()
            tot_t = pd.to_numeric(group['Trips Count'], errors='coerce').sum()
            
            resp_m = pd.to_numeric(group['Average Response Time'], errors='coerce')
            avg_resp = resp_m.dropna().mean()
            
            high_risk = group['Equipment Risk Level'].str.contains('High Risk', na=False).sum()
            
            gps_val = group.get('GPS', pd.Series('N/A'))
            gps_ok = gps_val.astype(str).str.upper().str.strip().isin(['YES', 'Y']).sum()
            
            dist_rows.append({
                'District': dist,
                'Total Vehicles': tot_v,
                'Total Trips': tot_t,
                'Average Response Time (Mins)': round(avg_resp, 2) if pd.notna(avg_resp) else 'N/A',
                'High Risk Vehicles (Immediate Action)': high_risk,
                'GPS Installed Vehicles': gps_ok
            })
            
    dist_df = pd.DataFrame(dist_rows)
    
    # 6. Save all Sheets to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        amb_df.to_excel(writer, sheet_name='Ambulances', index=False)
        if not daily_df.empty:
            daily_df.to_excel(writer, sheet_name='Calc_Data', index=False)
        if not dist_df.empty:
            dist_df.to_excel(writer, sheet_name='District Summary', index=False)
            
    date_str = ""
    if pd.notna(min_date) and pd.notna(max_date):
        date_str = f"_{min_date.strftime('%d%b')}_to_{max_date.strftime('%d%b')}"
        
    return output.getvalue(), date_str