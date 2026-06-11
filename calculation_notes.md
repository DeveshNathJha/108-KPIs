# 108 Ambulance KPI Calculation Notes

This document explains how each sheet and column in the final generated Excel KPI report is calculated and from which source sheets/fields the data is extracted.

## Source Data Sheets
1. **Master Data**: Contains vehicle registry (`Registration No.`), HOTO status, GPS status, operational status, and vehicle type.
2. **Raw Trips Data**: Contains trip-level details like dispatch times, ODO readings, caller numbers, and locations.
3. **Call Center Data (Hits)**: Contains call-level details like queue duration, ring duration, call start/end times, and dispositions.
4. **Equipment Audit Data**: Contains equipment health audits for vehicles.

---

## Sheet 1: Summary
*This sheet contains a vertical, state-wide high-level dashboard of operational statistics and SLA compliance metrics.*

- **Report Details**:
  - **Report Generation Time**: Current system timestamp when the report was generated.
  - **Reporting Date Range**: The minimum and maximum dates present in the Raw Trips dataset.
- **Operational Statistics Summary**:
  - **Total Vehicles in Master Database**: Total count of rows in the Master sheet before filtering.
  - **Registered Handed Over Fleet (HOTO)**: Count of vehicles marked as handed over/taken over (HOTO) in the Master sheet.
  - **Active Fleet Size (Ambulances with trips)**: Count of registered HOTO vehicles that have at least one trip recorded during the period.
  - **Total Ambulance Trips Completed**: Sum of all completed trips for HOTO vehicles.
  - **Total Operational Distance Travelled (Km)**: Sum of all completed trip distances (`Base End ODO` - `Base Start ODO`) for HOTO vehicles.
- **Performance & SLA Compliance**:
  - **Average Response Time (Mins)**: Average response time (assigned time to scene arrival) across all correlated trips.
  - **Urban ART Compliance (<=25 mins)**: Percentage and raw ratio of Urban trips arriving within 25 minutes.
  - **Rural ART Compliance (<=40 mins)**: Percentage and raw ratio of Rural trips arriving within 40 minutes.
  - **Ambulance Dispatch Compliance (<=180s)**: Percentage and raw ratio of trips with dispatch times (assigned time - connect time) <= 180 seconds.
- **SLA & Operational Insights**:
  - **Total Days with Operational fleet < 95%**: Number of days where the operational fleet percentage was below 95%.
  - **Total Fleet Delay in response time (Mins)**: Sum of all delay minutes incurred beyond the ART compliance limits (Response Time - 25 mins for Urban, Response Time - 40 mins for Rural).
  - **Districts with Shortfall in Trips**: Count of districts where the average trips/day/vehicle was < 3.
  - **Districts with Shortfall in Distance**: Count of districts where the average KM/day/vehicle was < 120 km.
- **Equipment Quality & Asset Audits**:
  - **Total Equipments Audited Vehicles**: Total count of unique vehicles that have at least one equipment audit.
  - **Equipment Quality Adherence (Health >= 90%)**: Percentage of audited vehicles with an equipment health score >= 90%.
  - **High-Risk Ambulances (Equipment health < 70%)**: Count of audited vehicles with an equipment health score < 70%.
  - **Total GPS Installed Fleet**: Percentage of HOTO vehicles with GPS marked as installed.

---

## Sheet 2: Ambulances (Vehicle Level Details)
*This sheet lists operational, SLA, and audit metrics grouped by each unique ambulance (Registration Number).*

- **District**: The district of the vehicle mapped from the Master sheet (standardized to uppercase).
- **Vehicle Number**: Standardized vehicle registration number (e.g., alphanumeric, stripped of non-alphanumeric characters).
- **Vehicle Type**: Type of vehicle (e.g., BLS, ALS, Neonatal) from the Master sheet.
- **Trips Count**: Total count of completed trips in the Raw Trips data.
- **Total Distance Travelled**: Sum of (`Base End ODO` - `Base Start ODO`) for all trips of the vehicle.
- **No Of Days (>3 Trips)**: Count of unique days where the vehicle completed more than 3 trips.
- **No of Days 0 Trips**: Total number of days in the report period minus the unique days the vehicle completed at least 1 trip.
- **Average Dispatch Time**: Average dispatch time in seconds, calculated as (`assigned_time` - `Agent Connected Time`). Filters out outliers (negative times and durations > 3 hours) and handles midnight crossover.
- **Count of Trip > 180 Sec Dispatch Time**: Count of trips where the dispatch time was greater than 180 seconds.
- **Average Response Time**: Average response time in minutes (`scene_arrival_time` - `assigned_time`) for all correlated trips of the vehicle. Includes midnight crossover handling.
- **Total Delay in response time**: Total minutes of delay beyond target ART SLAs (Response Time - 25 minutes for Urban, Response Time - 40 minutes for Rural).
- **Trips beyond Response Time(Rural)**: Count of trips in Rural areas where Response Time was > 30 minutes.
- **Trips beyond Response Time(Urban)**: Count of trips in Urban areas where Response Time was > 15 minutes.
- **Equipments Last Updated On**: The date (`YYYY-MM-DD`) of the latest equipment audit for the vehicle.
- **No Of Equipment - Working**: Count of required medical equipment marked as working in the latest audit.
- **No Of Equipment – Not Working**: Count of required medical equipment marked as not working/malfunctioning in the latest audit.
- **No Of Equipment – Not Available**: Count of required medical equipment marked as not available/absent in the latest audit.
- **Equipment Health %**: Percentage of required equipment in working condition relative to the vehicle's type requirements.
- **Equipment Risk Level**: Risk classification based on health percentage:
  - **High Risk**: Health < 70%
  - **Medium Risk**: 70% <= Health < 90%
  - **Low Risk**: Health >= 90%
- **GPS**: GPS installation status from the Master sheet (`YES` / `NO` / `N/A`).
- **Operational / Non-Operational**: Fleet operational status. Non-operational status is forced if the vehicle's condemnation date is prior to the report period.
- **HOTO Status**: Mapped HOTO status showing either the formatted date (`YYYY-MM-DD`) or `YES` / `N/A`.

---

## Sheet 3: Calc_Data (Daily Call & Fleet Summary)
*This sheet provides a daily operational log aggregating call volume, fleet availability, and response performance.*

- **Date**: The call date.
- **Total Agreed Fleet**: Count of HOTO-registered vehicles that were active (not yet condemned) on that date.
- **Operational Fleet**: Count of vehicles that completed at least 1 trip on that date.
- **Operational Fleet %**: (Operational Fleet / Total Agreed Fleet) * 100.
- **Operational fleet < 95%**: Flag (`YES` / `NO`) indicating whether the daily operational fleet percentage fell below the 95% target.
- **Total Calls**: Count of incoming calls logged in the Call Hits log.
- **Avg Call Pickup Time (Sec)**: Daily average call pickup latency (`Queue Duration` + `Ring Duration`).
- **Total Calls Attended**: Count of calls successfully correlated to an ambulance dispatch.
- **Calls Attended within 25 mins (Urban ART Met)**: Daily count of served urban calls where response time was <= 25 minutes.
- **Calls Attended within 40 mins (Rural ART Met)**: Daily count of served rural calls where response time was <= 40 minutes.
- **Call Type: [Clinical Category]**: Daily volume breakdown of calls mapped into clinical groups:
  - *Maternal, Trauma (Vehicular), Trauma (Non-Vehicular), Cardiac / Stroke, Respiratory, Neonatal / Pediatric, Gastrointestinal, Poisoning / Environmental, Chronic / Other Medical*.

---

## Sheet 4: DistrictWise (District Operational Scorecard)
*This sheet summarizes fleet operations, response compliance, and equipment risk levels aggregated by District.*

- **District**: Name of the district (standardized to uppercase).
- **Total Vehicles**: Count of unique vehicles registered in the district.
- **Total HOTO Vehicles**: Count of unique HOTO-registered vehicles in the district.
- **Total Trips**: Total trips completed by the district's vehicles.
- **District Average Trips/Day**: Average trips per day per active HOTO vehicle in the district.
- **District Average KM/Day**: Average kilometers traveled per day per active HOTO vehicle.
- **Excess / Shortfall Status**: Identifies performance gaps against targets:
  - Flags `"Shortfall in Trips"` if trips/day/vehicle < 3.
  - Flags `"Shortfall in Distance"` if KM/day/vehicle < 120.
  - Flags `"Excess Distance (>120km)"` if KM/day/vehicle >= 120.
  - Flags `"Target Met"` if both are satisfied.
- **Average Response Time (Mins)**: Average response time across all district trips.
- **Urban ART Compliance (<=25 mins)**: Percentage and raw ratio of Urban trips meeting the <=25 mins target.
- **Rural ART Compliance (<=40 mins)**: Percentage and raw ratio of Rural trips meeting the <=40 mins target.
- **High Risk Vehicles (Immediate Action)**: Count of vehicles in the district with equipment health < 70%.
- **GPS Installed Vehicles**: Count of vehicles in the district with GPS installed.
