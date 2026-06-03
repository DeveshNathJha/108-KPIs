# 108 Ambulance KPI Calculation Notes

This document explains how each column in the final generated KPI report is calculated and from which source sheet the data is extracted.

## Source Data Sheets
1. **Master Data**: Contains vehicle registry, HOTO status, GPS status, and vehicle type.
2. **Raw Trips Data**: Contains trip-level details like dispatch times, ODO readings, and locations.
3. **Call Center Data (Hits)**: Contains call-level details like queue duration, ring duration, and dispositions.
4. **Equipment Audit Data**: Contains the latest equipment health audits for vehicles.

---

## Sheet 1: Summary (State & District Health Dashboard)
*This sheet rolls up all performance metrics to provide a district-by-district high-level overview, along with statewide aggregated counters.*

- **District**: Direct list of the 24 Jharkhand districts.
- **Total Vehicles**: Count of unique active vehicles registered in each district from the Vehicle Master.
- **Total Equipments Audited Vehicles**: Count of unique vehicles in each district that have at least one equipment audit in the audit file.
- **Equipment Health %**: The average equipment health percentage across all audited vehicles in the district.
- **Total Trips**: Total number of completed trips recorded in the Raw Trips file for the district's vehicles.
- **Average Response Time (Mins)**: The average response time (Scene Arrival Time - Assigned Time) for all trips associated with the district.
- **High Risk Vehicles (Immediate Action)**: Number of vehicles in the district whose calculated equipment health index places them in the "High Risk" category (Health < 70%).
- **GPS Installed Vehicles**: Count of active vehicles in the district marked as having GPS installed in the Vehicle Master.

---

## Sheet 2: Ambulances (Vehicle Level Details)
*This sheet groups performance and audit metrics by each unique ambulance (Registration Number).*

- **District, Vehicle Number, Vehicle Type, GPS, Operational / Non-Operational, HOTO Status**:
  - **Source**: Vehicle Master Data.
  - **Calculation**: Direct mapping from columns like `Registration No.`, `Type of Vehicle`, `District`, `GPS`, `Operational/Non Operational`, `HOTO Status`.
- **Trips Count**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Total count of trips made by the vehicle.
- **Total Distance Travelled**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Sum of (`Base End ODO` - `Base Start ODO`) for all trips of the vehicle.
- **No of Days (>3 Trips)**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Count of unique dates where the vehicle made more than 3 trips.
- **No of Days 0 Trips**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Total days in the report period minus the number of unique days the vehicle had at least 1 trip.
- **Average Dispatch Time**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Average difference in seconds between `assigned_time` and `Agrent CONNECTED TIME`.
- **Count of Trip > 180 Sec Dispatch Time**:
  - **Source**: Raw Trips Data.
  - **Calculation**: Count of trips where the calculated Dispatch Time is greater than 180 seconds.
- **Average Response Time**:
  - **Source**: Correlated Trips Data (Raw Trips matched with Calls).
  - **Calculation**: Average difference in minutes between `scene_arrival_time` and `assigned_time`.
- **Trips beyond Response Time (Rural / Urban)**:
  - **Source**: Correlated Trips Data.
  - **Calculation**: Count of trips where `Location Type` is Rural and Response Time > 30 mins OR `Location Type` is Urban and Response Time > 15 mins.
- **Equipment Health %, Risk Level, Last Audited On, and Equipment Checklist Status**:
  - **Source**: Equipment Audit Data.
  - **Calculation**: Pulls the latest audit entry for the vehicle based on the `Timestamp`. Validates working conditions of required devices (Ventilator, Stethoscope, etc.) relative to the vehicle's specific type (BLS, ALS, Neonatal).

---

## Sheet 3: Calc_Data (Daily Call Center Summary)
*This sheet summarizes incoming call traffic and response metrics grouped by Date.*

- **Date**: Extracted from the Call Hits log (`Call Start Time`).
- **Total Calls**: Total count of unique incoming calls.
- **Avg Call Pickup Time (Sec)**: Average time for the call center to pick up, calculated as (`QUEUE Duration` + `RING Duration`).
- **Total Calls Attended**: Count of calls successfully linked to a trip (Served Status).
- **Calls Attended within SLAs (15 mins Urban / 30 mins Rural)**: Count of served calls meeting the respective response time criteria.
- **Calls Attended within ART Met (25 mins Urban / 40 mins Rural)**: Count of served calls meeting the adjusted response time targets.
- **Call Types (Disease Categories)**: Daily volume breakdown mapped from raw `DISEASE` values into clean clinical categories (Maternal, Trauma, Cardiac, Neonatal, etc.).

---

## Sheet 4: DistrictWise (District Performance Breakdown)
*This sheet summarizes operational and SLA compliance metrics grouped by District.*

- **District**: The district name.
- **Total Calls**: Count of calls linked to the district (after backfilling).
- **Calls Attended / Missed**: Split of served versus non-served calls.
- **Average Dispatch Time (Sec)**: Mean dispatch delay in seconds.
- **Average Response Time (Mins)**: Mean response delay in minutes.
- **SLA Compliance % (Urban / Rural)**: The percentage of dispatches that met the respective 15-minute Urban or 30-minute Rural response times.
- **ART Met % (Urban / Rural)**: The percentage of dispatches meeting the adjusted 25-minute Urban or 40-minute Rural response times.
- **P90 Response Time (Mins)**: The time within which 90% of all dispatches in the district arrived at the scene.
- **Case Type Distribution**: Volume of dispatches per district for each clean disease category.
