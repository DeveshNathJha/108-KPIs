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

_DISEASE_LOOKUP = {}
for cat, values in DISEASE_CATEGORIES.items():
    for v in values:
        _DISEASE_LOOKUP[v] = cat

def categorize_disease(val):
    if pd.isna(val) or str(val).strip() in ('', '\\N', 'nan', 'None', 'NULL'):
        return 'Unknown'
    val_str = str(val).strip()
    if val_str in _DISEASE_LOOKUP:
        return _DISEASE_LOOKUP[val_str]
    return 'Other / Unknown'

TYPO_CORRECTIONS = {
    "JH01FL0390": "JH01FL0396",
    "JH01FL3802": "JH01FL3082"
}

def clean_vehicle_number(val):
    if pd.isna(val):
        return ""
    clean = re.sub(r'[^A-Z0-9]', '', str(val).upper().strip())
    return TYPO_CORRECTIONS.get(clean, clean)

def format_hoto_status(val):
    if pd.isna(val):
        return 'N/A'
    if isinstance(val, (datetime.datetime, pd.Timestamp)):
        return val.strftime('%Y-%m-%d')
    val_str = str(val).strip()
    if val_str.upper() in ('', 'NAN', 'NAT', 'NONE', 'N/A', 'NO', 'N', 'FALSE'):
        return 'N/A'
    if val_str.upper() in ('YES', 'Y', 'HOTO', 'TRUE'):
        return 'YES'
    try:
        dt = pd.to_datetime(val_str, errors='coerce')
        if pd.notna(dt):
            return dt.strftime('%Y-%m-%d')
    except Exception:
        pass
    return val_str

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
    # Pre-calculate dates for HOTO filtering
    temp_raw_dates = pd.to_datetime(raw_df['Date'], errors='coerce') if 'Date' in raw_df.columns else pd.Series(dtype='datetime64[ns]')
    max_date = temp_raw_dates.max()
    min_date = temp_raw_dates.min()
    
    # 0. Find condemnation date column dynamically
    condemn_col = None
    for col in master_df.columns:
        col_lower = str(col).lower()
        if 'condemnation date' in col_lower or 'condemned date' in col_lower or 'damage date' in col_lower or 'retirement date' in col_lower:
            condemn_col = col
            break
            
    # 0. Apply dynamic retirement of fully damaged/retired vehicles
    if pd.notna(min_date):
        min_dt = min_date.tz_localize(None)
        
        master_clean_col = 'Registration No.'
        for col in master_df.columns:
            if 'registration' in str(col).lower() or 'reg' in str(col).lower():
                master_clean_col = col
                break
                
        if condemn_col:
            def is_retired_before_period(row):
                val = row.get(condemn_col)
                if pd.isna(val) or str(val).strip() in ('', '-----', 'nan', 'None'):
                    return False
                try:
                    dt = pd.to_datetime(str(val).strip(), errors='coerce')
                    if pd.notna(dt):
                        return min_dt > dt.tz_localize(None)
                except Exception:
                    pass
                return False
            
            master_df = master_df[~master_df.apply(is_retired_before_period, axis=1)]


    
    # 1. Run Correlation
    corr_df = sql_engine.run_correlation(raw_df, calls_df)
    
    hoto_col = None
    for col in master_df.columns:
        if 'hoto' in str(col).lower():
            hoto_col = col
            break
            
    if hoto_only:
        hoto_vehicles = set()
        master_clean_col = 'Registration No.'
        
        # Scan master_df columns dynamically to be extremely robust
        for col in master_df.columns:
            if 'registration' in str(col).lower() or 'reg' in str(col).lower():
                master_clean_col = col
                break
                
        for idx, row in master_df.iterrows():
            reg_clean = clean_vehicle_number(row.get(master_clean_col, ''))
            if hoto_col:
                hoto_val = str(row.get(hoto_col, '')).strip().upper()
            else:
                hoto_val = str(row.get('HOTO Status', row.get('HOTO or not', ''))).strip().upper()
                
            is_hoto = False
            if hoto_val in ('YES', 'HOTO', 'Y', 'TRUE'):
                is_hoto = True
            elif hoto_val not in ('', 'NAN', 'NAT', 'NONE', 'NO', 'N/A', 'FALSE'):
                # If it's not a negative/empty string, it's likely a valid date string from the excel
                is_hoto = True
                try:
                    # Attempt to parse the HOTO date
                    hoto_dt = pd.to_datetime(row.get(hoto_col if hoto_col else 'HOTO Status'), errors='coerce')
                    # If we successfully parse the date and max_date is available, check if HOTO happened after report period
                    if pd.notna(hoto_dt) and pd.notna(max_date):
                        # Make both naive for comparison
                        if hoto_dt.tz_localize(None) > max_date.tz_localize(None):
                            is_hoto = False
                except Exception:
                    pass
                
            if is_hoto and reg_clean:
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
    if not eq.empty and 'Timestamp' in eq.columns:
        eq['Timestamp'] = pd.to_datetime(eq['Timestamp'], errors='coerce')
        
        # Filter out audits that happened after the report period
        if pd.notna(max_date):
            end_of_period = max_date.replace(hour=23, minute=59, second=59).tz_localize(None)
            def is_valid_audit(ts):
                if pd.isna(ts):
                    return True
                return ts.tz_localize(None) <= end_of_period
            
            mask = eq['Timestamp'].apply(is_valid_audit).astype(bool)
            eq = eq[mask]
            
        if not eq.empty:
            eq = eq.sort_values('Timestamp').groupby('Clean_Vehicle_No').last().reset_index()
    elif not eq.empty:
        eq = eq.groupby('Clean_Vehicle_No').last().reset_index()
        
    eq_dict = eq.set_index('Clean_Vehicle_No').to_dict('index')
    
    # 3. Process Sheet 1: Ambulances (Vehicle Level)
    amb_rows = []
    
    # Preprocess Raw Trips for speed
    raw = raw_df.copy()
    raw['Clean_Vehicle_No'] = raw['Vehicle No'].apply(clean_vehicle_number)
    
    # Date Range of dataset (already calculated above, just re-assigning for raw_df)
    raw['Parsed_Date'] = pd.to_datetime(raw['Date'], errors='coerce')
    all_dates = pd.date_range(start=min_date, end=max_date) if pd.notna(min_date) and pd.notna(max_date) else []
    total_days = max(len(all_dates), 1)
    
    # Pre-aggregate Raw Distance, Trips, Dispatch Time, etc. for quick lookup
    raw['Start_ODO'] = pd.to_numeric(raw['Base Start ODO'], errors='coerce')
    raw['End_ODO'] = pd.to_numeric(raw['Base End ODO'], errors='coerce')
    raw['Trip_Distance'] = (raw['End_ODO'] - raw['Start_ODO']).fillna(0)
    
    raw_default = pd.Series(index=raw.index)
    parsed_assigned = sql_engine._parse_raw_datetime(raw, ['assigned_time', 'assigned time', 'assign time'], ['Date', 'date'], raw_default)
    parsed_connected = sql_engine._parse_raw_datetime(raw, ['Agrent CONNECTED TIME', 'Agent Connected Time', 'Connected Time', 'Connect Time'], ['Date', 'date'], raw_default)
    
    dispatch_sec = (pd.to_datetime(parsed_assigned, errors='coerce') - 
                    pd.to_datetime(parsed_connected, errors='coerce')).dt.total_seconds()
    # Correct for midnight crossovers
    dispatch_sec = np.where(dispatch_sec < -43200, dispatch_sec + 86400, dispatch_sec)
    # Floor small negative lag to 0, filter out large outliers (>3 hours or still negative) as np.nan
    raw['Dispatch_Sec'] = np.where((dispatch_sec >= -60) & (dispatch_sec < 0), 0,
                                   np.where((dispatch_sec >= 0) & (dispatch_sec <= 10800), dispatch_sec, np.nan))
                           
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
                
        # Dynamic status overrides for fully damaged vehicles
        op_status = row.get('Operational / Non-Operational', row.get('Operational/Non Operational', 'N/A'))
        if condemn_col:
            condemn_val = row.get(condemn_col)
            if pd.notna(condemn_val) and str(condemn_val).strip() not in ('', '-----', 'nan', 'None'):
                try:
                    condemn_dt = pd.to_datetime(str(condemn_val).strip(), errors='coerce')
                    if pd.notna(condemn_dt) and pd.notna(max_date):
                        if max_date.tz_localize(None) >= condemn_dt.tz_localize(None):
                            op_status = 'Non-Operational'
                except Exception:
                    pass


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
            'Operational / Non-Operational': op_status,
            'HOTO Status': format_hoto_status(row[hoto_col]) if hoto_col and pd.notna(row.get(hoto_col)) else format_hoto_status(row.get('HOTO Status', row.get('HOTO or not', 'N/A')))
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
        group['Clinical_Category'] = group['Disease'].apply(categorize_disease)
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
        for cat in DISEASE_CATEGORIES.keys():
            daily_row[f'Call Type: {cat}'] = cat_counts.get(cat, 0)
            
        daily_rows.append(daily_row)
        
    daily_df = pd.DataFrame(daily_rows)
    if not daily_df.empty:
        daily_df = daily_df.sort_values('Date')
        
    # 5. Sheet 4: DistrictWise
    dist_rows = []
    
    # Pre-calculate district-wise KPIs from corr_df
    dist_sla_map = {}
    if 'Final_District' in corr_df.columns:
        for f_dist, g_dist in corr_df.groupby('Final_District'):
            clean_d = str(f_dist).strip().upper()
            if not clean_d:
                continue
            
            urban_g = g_dist[g_dist['Location_Category'] == 'Urban']
            rural_g = g_dist[g_dist['Location_Category'] == 'Rural']
            
            u_sla_tot = len(urban_g)
            u_sla_met = urban_g['Urban_SLA_Met'].sum() if 'Urban_SLA_Met' in urban_g.columns else 0
            r_sla_tot = len(rural_g)
            r_sla_met = rural_g['Rural_SLA_Met'].sum() if 'Rural_SLA_Met' in rural_g.columns else 0
            
            u_art_tot = len(urban_g)
            u_art_met = urban_g['Urban_ART_Met'].sum() if 'Urban_ART_Met' in urban_g.columns else 0
            r_art_tot = len(rural_g)
            r_art_met = rural_g['Rural_ART_Met'].sum() if 'Rural_ART_Met' in rural_g.columns else 0
            
            dist_sla_map[clean_d] = {
                'urban_sla': f"{round((u_sla_met / max(u_sla_tot, 1) * 100), 2)}% ({u_sla_met}/{u_sla_tot})" if u_sla_tot > 0 else "N/A",
                'rural_sla': f"{round((r_sla_met / max(r_sla_tot, 1) * 100), 2)}% ({r_sla_met}/{r_sla_tot})" if r_sla_tot > 0 else "N/A",
                'urban_art': f"{round((u_art_met / max(u_art_tot, 1) * 100), 2)}% ({u_art_met}/{u_art_tot})" if u_art_tot > 0 else "N/A",
                'rural_art': f"{round((r_art_met / max(r_art_tot, 1) * 100), 2)}% ({r_art_met}/{r_art_tot})" if r_art_tot > 0 else "N/A"
            }

    if not amb_df.empty:
        # Group Ambulances by District
        amb_grp = amb_df.groupby('District')
        for dist, group in amb_grp:
            clean_d = str(dist).strip().upper()
            tot_v = group['Vehicle Number'].nunique()
            tot_t = pd.to_numeric(group['Trips Count'], errors='coerce').sum()
            
            resp_m = pd.to_numeric(group['Average Response Time'], errors='coerce')
            avg_resp = resp_m.dropna().mean()
            
            high_risk = group['Equipment Risk Level'].str.contains('High Risk', na=False).sum()
            
            gps_val = group.get('GPS', pd.Series('N/A'))
            gps_ok = gps_val.astype(str).str.upper().str.strip().isin(['YES', 'Y']).sum()
            
            # Lookup KPIs for this district
            kpi_data = dist_sla_map.get(clean_d, {
                'urban_sla': 'N/A',
                'rural_sla': 'N/A',
                'urban_art': 'N/A',
                'rural_art': 'N/A'
            })
            
            dist_rows.append({
                'District': dist,
                'Total Vehicles': tot_v,
                'Total Trips': tot_t,
                'Average Response Time (Mins)': round(avg_resp, 2) if pd.notna(avg_resp) else 'N/A',
                'Urban SLA Compliance (<=15 mins)': kpi_data['urban_sla'],
                'Rural SLA Compliance (<=30 mins)': kpi_data['rural_sla'],
                'Urban ART Compliance (<=25 mins)': kpi_data['urban_art'],
                'Rural ART Compliance (<=40 mins)': kpi_data['rural_art'],
                'High Risk Vehicles (Immediate Action)': high_risk,
                'GPS Installed Vehicles': gps_ok
            })
            
    dist_df = pd.DataFrame(dist_rows)
    
    # 5.5 Create Summary sheet
    report_gen_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    period_str = f"{min_date.strftime('%d-%b-%Y')} to {max_date.strftime('%d-%b-%Y')}" if pd.notna(min_date) and pd.notna(max_date) else "N/A"
    
    total_fleet = len(master_df)
    active_fleet = amb_df['Vehicle Number'].nunique() if not amb_df.empty else 0
    total_trips = amb_df['Trips Count'].sum() if not amb_df.empty else 0
    total_dist = amb_df['Total Distance Travelled'].sum() if not amb_df.empty else 0.0
    
    avg_response_time = np.nan
    if 'Response_Time_Mins' in corr_df.columns:
        avg_response_time = corr_df['Response_Time_Mins'].mean()
        
    urban_total = 0
    urban_met = 0
    rural_total = 0
    rural_met = 0
    urban_art_total = 0
    urban_art_met = 0
    rural_art_total = 0
    rural_art_met = 0
    
    if 'Location_Category' in corr_df.columns and 'Urban_SLA_Met' in corr_df.columns and 'Rural_SLA_Met' in corr_df.columns:
        urban_df = corr_df[corr_df['Location_Category'] == 'Urban']
        urban_total = len(urban_df)
        urban_met = urban_df['Urban_SLA_Met'].sum()
        urban_art_total = len(urban_df)
        urban_art_met = urban_df['Urban_ART_Met'].sum()
        
        rural_df = corr_df[corr_df['Location_Category'] == 'Rural']
        rural_total = len(rural_df)
        rural_met = rural_df['Rural_SLA_Met'].sum()
        rural_art_total = len(rural_df)
        rural_art_met = rural_df['Rural_ART_Met'].sum()
        
    urban_sla_pct = f"{round((urban_met / max(urban_total, 1) * 100), 2)}% ({urban_met}/{urban_total})" if urban_total > 0 else "N/A"
    rural_sla_pct = f"{round((rural_met / max(rural_total, 1) * 100), 2)}% ({rural_met}/{rural_total})" if rural_total > 0 else "N/A"
    urban_art_pct = f"{round((urban_art_met / max(urban_art_total, 1) * 100), 2)}% ({urban_art_met}/{urban_art_total})" if urban_art_total > 0 else "N/A"
    rural_art_pct = f"{round((rural_art_met / max(rural_art_total, 1) * 100), 2)}% ({rural_art_met}/{rural_art_total})" if rural_art_total > 0 else "N/A"
    
    # Calculate Dispatch Compliance (<= 180 seconds)
    total_trips_raw = len(raw)
    dispatch_ok = (raw['Dispatch_Sec'] <= 180).sum()
    dispatch_sla_pct = f"{round((dispatch_ok / max(total_trips_raw, 1) * 100), 2)}% ({dispatch_ok}/{total_trips_raw})" if total_trips_raw > 0 else "N/A"
    
    # Calculate Equipment Quality Adherence
    eq_audited_count = len(eq_dict)
    eq_low_risk_count = 0
    for reg, eq_audit in eq_dict.items():
        row_master = master[master['Clean_Vehicle_No'] == reg]
        v_type = row_master.iloc[0].get('Type of Vehicle', 'BLS') if not row_master.empty else 'BLS'
        applicable = _get_applicable_equipments(v_type)
        working = 0
        for item in applicable:
            val = str(eq_audit.get(item)).strip().lower()
            if 'working' in val or 'functional' in val:
                working += 1
        tot = len(applicable)
        health_pct = (working / tot * 100) if tot > 0 else 0.0
        if health_pct >= 90.0:
            eq_low_risk_count += 1
            
    eq_adherence_pct = f"{round((eq_low_risk_count / max(eq_audited_count, 1) * 100), 2)}% ({eq_low_risk_count}/{eq_audited_count})" if eq_audited_count > 0 else "N/A"
    
    high_risk_count = 0
    if not amb_df.empty:
        high_risk_count = amb_df['Equipment Risk Level'].str.contains('High Risk', na=False).sum()
        
    gps_total = 0
    if 'GPS' in master_df.columns:
        gps_total = master_df['GPS'].astype(str).str.upper().str.strip().isin(['YES', 'Y']).sum()
    gps_pct = f"{round((gps_total / max(total_fleet, 1) * 100), 1)}% ({gps_total}/{total_fleet})" if total_fleet > 0 else "N/A"
    
    summary_rows = [
        {"KPI Report Parameter": "Summary Report", "Value / Metric": ""},
        {"KPI Report Parameter": "----------------------------------------", "Value / Metric": "----------------------------------------"},
        {"KPI Report Parameter": "Report Generation Time", "Value / Metric": report_gen_date},
        {"KPI Report Parameter": "Reporting Date Range", "Value / Metric": period_str},
        {"KPI Report Parameter": "", "Value / Metric": ""},
        {"KPI Report Parameter": "Operational Statistics Summary", "Value / Metric": ""},
        {"KPI Report Parameter": "----------------------------------------", "Value / Metric": "----------------------------------------"},
        {"KPI Report Parameter": "Total Fleet Size (Registered)", "Value / Metric": total_fleet},
        {"KPI Report Parameter": "Active Fleet Size (Ambulances with trips)", "Value / Metric": active_fleet},
        {"KPI Report Parameter": "Total Ambulance Trips Completed", "Value / Metric": total_trips},
        {"KPI Report Parameter": "Total Operational Distance Travelled (Km)", "Value / Metric": round(total_dist, 1)},
        {"KPI Report Parameter": "", "Value / Metric": ""},
        {"KPI Report Parameter": "Performance & SLA Compliance", "Value / Metric": ""},
        {"KPI Report Parameter": "----------------------------------------", "Value / Metric": "----------------------------------------"},
        {"KPI Report Parameter": "Average Response Time (Mins)", "Value / Metric": round(avg_response_time, 2) if pd.notna(avg_response_time) else "N/A"},
        {"KPI Report Parameter": "Urban SLA Compliance (<=15 mins)", "Value / Metric": urban_sla_pct},
        {"KPI Report Parameter": "Rural SLA Compliance (<=30 mins)", "Value / Metric": rural_sla_pct},
        {"KPI Report Parameter": "Urban ART Compliance (<=25 mins)", "Value / Metric": urban_art_pct},
        {"KPI Report Parameter": "Rural ART Compliance (<=40 mins)", "Value / Metric": rural_art_pct},
        {"KPI Report Parameter": "Ambulance Dispatch Compliance (<=180s)", "Value / Metric": dispatch_sla_pct},
        {"KPI Report Parameter": "", "Value / Metric": ""},
        {"KPI Report Parameter": "Equipment Quality & Asset Audits", "Value / Metric": ""},
        {"KPI Report Parameter": "----------------------------------------", "Value / Metric": "----------------------------------------"},
        {"KPI Report Parameter": "Total Equipments Audited Vehicles", "Value / Metric": eq_audited_count},
        {"KPI Report Parameter": "Equipment Quality Adherence (Health >= 90%)", "Value / Metric": eq_adherence_pct},
        {"KPI Report Parameter": "High-Risk Ambulances (Equipment health < 70%)", "Value / Metric": high_risk_count},
        {"KPI Report Parameter": "Total GPS Installed Fleet", "Value / Metric": gps_pct},
    ]
    summary_df = pd.DataFrame(summary_rows)
    
    # 6. Save all Sheets to Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        amb_df.to_excel(writer, sheet_name='Ambulances', index=False)
        if not daily_df.empty:
            daily_df.to_excel(writer, sheet_name='Calc_Data', index=False)
        if not dist_df.empty:
            dist_df.to_excel(writer, sheet_name='DistrictWise', index=False)
            
    date_str = ""
    if pd.notna(min_date) and pd.notna(max_date):
        date_str = f"_{min_date.strftime('%d%b')}_to_{max_date.strftime('%d%b')}"
        
    return output.getvalue(), date_str