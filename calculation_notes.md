# 108 Ambulance KPI Calculation Notes

This document explains how each column in the final generated KPI report is calculated and from which source sheet the data is extracted.

## Source Data Sheets
1. **Master Data**: Contains vehicle registry, HOTO status, GPS status, and vehicle type.
2. **Raw Trips Data**: Contains trip-level details like dispatch times, ODO readings, and locations.
3. **Call Center Data (Hits)**: Contains call-level details like queue duration, ring duration, and dispositions.
4. **Equipment Audit Data**: Contains the latest equipment health audits for vehicles.

---

## Sheet 1: Ambulances (Vehicle Level Summary)
*This sheet groups the performance by each unique ambulance (Registration Number).*

- **District, Vehicle Number, Vehicle Type, GPS, Operational / Non-Operational, HOTO Status**: 
  - **Source**: Master Data
  - **Calculation**: Direct mapping from columns like `Registration No.`, `Type of Vehicle`, `District`, `GPS`, `Operational/Non Operational`, `HOTO Status`.
- **Trips Count**:
  - **Source**: Raw Trips Data
  - **Calculation**: Total count of trips for the vehicle (`Vehicle No`).
- **Total Distance Travelled**:
  - **Source**: Raw Trips Data
  - **Calculation**: Sum of (`Base End ODO` - `Base Start ODO`) for all trips of the vehicle.
- **No Of Days (>3 Trips)**:
  - **Source**: Raw Trips Data
  - **Calculation**: Count of unique dates (from the `Date` column) where the vehicle made more than 3 trips.
- **No of Days 0 Trips**:
  - **Source**: Raw Trips Data
  - **Calculation**: Total days in the report period minus the number of days the vehicle had at least 1 trip.
- **Average Dispatch Time**:
  - **Source**: Raw Trips Data
  - **Calculation**: Average difference in seconds between `assigned_time` and `Agrent CONNECTED TIME`.
- **Count of Trip > 180 Sec Dispatch Time**:
  - **Source**: Raw Trips Data
  - **Calculation**: Count of trips where the calculated Dispatch Time is greater than 180 seconds.
- **Average Response Time**:
  - **Source**: Correlated Trips Data (Raw Trips matched with Calls)
  - **Calculation**: Average difference in minutes between `scene_arrival_time` and `assigned_time`.
- **Trips beyond Response Time (Rural / Urban)**:
  - **Source**: Correlated Trips Data
  - **Calculation**: Count of trips where `Location Type` is Rural and Response Time > 30 mins OR `Location Type` is Urban and Response Time > 15 mins.
- **Equipment Metrics (Last Updated On, Working, Not Working, Not Available, Health %, Risk Level)**:
  - **Source**: Equipment Audit Data
  - **Calculation**: Takes the most recent audit for the vehicle (`Timestamp`). Calculates percentages based on the required equipment list for the specific `Vehicle Type` (BLS, ALS, Neonatal).

---

## Sheet 2: Calc_Data (Daily Call Summary)
*This sheet summarizes call center and response performance grouped by Date.*

- **Date**: 
  - **Source**: Call Center Data (`Call Start Time`)
- **Total Calls**:
  - **Source**: Call Center Data
  - **Calculation**: Count of unique incoming calls (`Call_ID`).
- **Avg Call Pickup Time (Sec)**:
  - **Source**: Call Center Data
  - **Calculation**: Average of (`QUEUE Duration` + `RING Duration`).
- **Total Calls Attended**:
  - **Source**: Correlated Data (Calls + Raw Trips)
  - **Calculation**: Count of calls successfully linked to a `Case ID` (Served Status).
- **Calls Attended within SLAs (15 mins Urban / 30 mins Rural)**:
  - **Source**: Correlated Data
  - **Calculation**: Count of served calls meeting the respective response time criteria.
- **Calls Attended within ART Met (25 mins Urban / 40 mins Rural)**:
  - **Source**: Correlated Data
  - **Calculation**: Count of served calls meeting the adjusted response time targets.
- **Call Types (Disease Categories)**:
  - **Source**: Raw Trips Data
  - **Calculation**: Categorization based on the `DISEASE` column (e.g., Pregnancy, Road Traffic Accident).

---

## Sheet 3: District Summary
*This sheet rolls up the vehicle-level data to the District level.*

- **Total Vehicles**: 
  - **Source**: Master Data (Count of unique vehicles per District).
- **Total Trips**: 
  - **Source**: Ambulances Sheet (Sum of `Trips Count` per District).
- **Average Response Time (Mins)**: 
  - **Source**: Ambulances Sheet (Mean of `Average Response Time` for vehicles in the District).
- **High Risk Vehicles (Immediate Action)**: 
  - **Source**: Ambulances Sheet (Count of vehicles with `Equipment Risk Level` containing "High Risk").
- **GPS Installed Vehicles**:
  - **Source**: Ambulances Sheet (Count of vehicles where `GPS` status is 'Yes' or 'Y').
