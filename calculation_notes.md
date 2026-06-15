# 108 Ambulance KPI Calculation Notes

This document explains how each sheet and column in the final generated Excel KPI report is calculated, the mapping of fields, and the underlying correlation logic.

## Source Data Sheets
1. **Master Data**: Contains vehicle registry (`Registration No.`), HOTO status, GPS status, operational status, and vehicle type.
2. **Raw Trips Data**: Contains trip-level details like dispatch times, ODO readings, caller numbers, and locations.
3. **Call Center Data (Hits)**: Contains call-level details like queue duration, ring duration, call start/end times, and dispositions.
4. **Equipment Audit Data**: Contains equipment health audits for vehicles.

---

## Correlation Logic & Data Preparation
- **Vehicle-Based Matching (Primary)**: Calls and trips are primarily matched by vehicle number (`Call_Vehicle_No` from the call log matches `Clean_Vehicle_No` from the raw trip log) within a **90-minute time window** (`Call_Start_Time` vs `Trip_Connected_Time` of the trip).
- **Phone-Based Matching (Fallback)**: If the call has no vehicle number associated with it, it falls back to phone number matching (`Clean_Phone` from calls matches `Trip_Clean_Phone` from raw trips) within the **90-minute window**.
- **Case ID Resolution**: Since the `Case ID` column in the raw trip data is a generic year prefix (`20260000000000`), it is non-unique. The engine uses `Sl No` (or the row index as a fallback) as the unique trip identifier for deduplication and ranking.
- **Time Window Formatting**: Date parsing uses standard US/ISO format parsing (`dayfirst=False`) for BOTH calls and raw trips, correcting a legacy date swapper bug where `dayfirst=True` treated March 1st as January 3rd.
- **True Response Time (Follow-up Overwrite Fix)**: Bypasses the raw trip connected time (which can be overwritten by subsequent follow-up calls in the logs) and uses the true dialer connect time (`Call_Connect_Time`). To select the first call in a sequence of follow-up calls, the candidate calls for a trip are ranked and matched chronologically using `Call_Start_Time ASC`.

---

## Sheet 1: Summary
*This sheet contains a vertical, state-wide high-level dashboard of operational statistics and SLA compliance metrics.*

- **Report Details**:
  - **Report Generation Time**: Current system timestamp when the report was generated.
  - **Reporting Date Range**: The minimum and maximum dates present in the Raw Trips dataset.
- **Operational Statistics Summary**:
  - **Total Vehicles**: Total count of rows in the Master sheet before any filters.
  - **Handed Over Fleet (HOTO)**: Count of active vehicles in the Master sheet marked as handed over/taken over (HOTO) that are not condemned/retired before the reporting period.
  - **Active Ambulances (Ambulances with trips)**: Count of HOTO vehicles that have at least one trip recorded during the period. (Excludes 0-distance trips and trips missing vehicle numbers).
  - **Total Trips Completed**: Sum of all completed trips for HOTO vehicles. (Excludes 0-distance trips and trips missing vehicle numbers).
  - **Total Distance Travelled (Km)**: Sum of all completed trip distances (`Base End ODO` - `Base Start ODO`) for HOTO vehicles. (Excludes 0-distance trips and trips missing vehicle numbers).
- **Call Center & IVR Performance**:
  - **Average Call Pickup Time (Sec)**: The average call pickup duration `(IVR Duration + QUEUE Duration + RING Duration)` across all calls with duration > 0 seconds.
  - **Calls Pickup Beyond 30 Sec**: The count of calls where the sum of IVR, Queue, and Ring durations exceeds 30 seconds.
- **Call Outcome Breakdown (Monthly)**:
  - Monthly percentage breakdown of all incoming calls mapped via a strict hierarchy:
    1. **Valid**: Operational call dispositions (`EmergencyCall`, `InterFacilityTransfer`, etc.) or completed status.
    2. **Dropped**: Agent disposition containing the string "dropped" or "drop".
    3. **Missed**: Agent disposition containing "missed" or Dialer disposition equal to "MISSED".
    4. **Silent**: Agent disposition containing "silent".
    5. **Abandoned (Non-Penalty)**: Dialer disposition equal to "ABANDONED" (with no agent classification).
    6. **Incomplete**: Answered calls that did not match any categories above (e.g. `REDIAL`, `RepeatedCall`, `Informationcall`).
    7. **Noise/Disturbance**: Agent disposition containing "nuisance", "prank", or "wrong".
- **Performance & SLA Compliance**:
  - **Average Response Time (Mins)**: Average true response time (`scene_arrival_time` - dialer's `Call_Connect_Time`) across all correlated/served trips.
  - **Urban ART Compliance (<=25 mins)**: Percentage and raw ratio of served Urban trips with response time <= 25 minutes.
  - **Rural ART Compliance (<=40 mins)**: Percentage and raw ratio of served Rural trips with response time <= 40 minutes.
  - **Ambulance Dispatch Compliance (<=180s)**: Percentage and raw ratio of trips with dispatch times (`assigned_time` - `Agent CONNECTED TIME`) <= 180 seconds.
- **SLA & Operational Insights**:
  - **Total Days with Operational fleet < 95%**: Number of days where the operational fleet percentage (Operational Fleet / Total Agreed Fleet) was below 95%.
  - **Total Fleet Delay in response time (Mins)**: Sum of all delay minutes incurred beyond the ART compliance limits (Response Time - 25 mins for Urban, Response Time - 40 mins for Rural) across all HOTO vehicles.
  - **Districts with Shortfall in Trips**: Count of districts where the average trips/day/vehicle was < 3.
  - **Districts with Shortfall in Distance**: Count of districts where the average KM/day/vehicle was < 120 km.
- **Equipment Quality & Asset Audits**:
  - **Total Equipments Audited Vehicles**: Total count of unique vehicles that have at least one equipment audit.
  - **Equipment Quality Adherence (Health >= 90%)**: Percentage of audited vehicles with an equipment health score >= 90%.
  - **High-Risk Ambulances (Equipment health < 70%)**: Count of audited vehicles with an equipment health score < 70%.
  - **Total GPS Installed Fleet**: Percentage of HOTO vehicles with GPS marked as installed.
- **AHT Insight**:
  - **Total Average Handling Time (AHT) per Call**: The average call handle time (`Call_End_Time` - `Call_Connect_Time`) for calls with valid duration records.

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
- **Average Dispatch Time in Sec**: Average dispatch time in seconds, calculated as (`assigned_time` - `Agent CONNECTED TIME`). Filters out outliers (negative times and durations > 3 hours) and handles midnight crossover.
- **Count of Trip > 180 Sec Dispatch Time**: Count of trips where the dispatch time was greater than 180 seconds.
- **Average Response Time in Min**: Average response time in minutes (`scene_arrival_time` - `Agent CONNECTED TIME`) for all correlated trips of the vehicle. Includes midnight crossover handling.
- **Total Delay in response time in Min**: Total minutes of delay beyond target ART SLAs (Response Time - 25 minutes for Urban, Response Time - 40 minutes for Rural).
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
- **Operational Fleet**: Count of vehicles that completed at least 1 trip on that date (excluding 0-distance trips).
- **Operational Fleet %**: (Operational Fleet / Total Agreed Fleet) * 100.
- **Operational fleet < 95%**: Flag (`YES` / `NO`) indicating whether the daily operational fleet percentage fell below the 95% target.
- **Total Calls**: Count of incoming calls logged in the Call Hits log.
- **Avg Call Pickup Time (Sec)**: Daily average call pickup latency (`IVR Duration` + `Queue Duration` + `Ring Duration`).
- **Total Calls Attended**: Count of calls successfully correlated to an ambulance dispatch.
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
