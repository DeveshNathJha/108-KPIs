-- ============================================================================
-- 108 AMBULANCE SERVICE — CALL-TO-TRIP CORRELATION & KPI ANALYSIS (v3)
-- ============================================================================
-- Author  : Devesh Jha
-- Purpose : Correlate emergency call records with ambulance trip dispatches
--           using phone-number matching and time-proximity scoring, then
--           compute operational KPIs (ART, SLA compliance, conversion rates).
-- Engine  : SQLite (uses JULIANDAY for timestamp arithmetic)
--
-- v3 AUDIT FIXES APPLIED:
--   FIX 1: Smart trip deduplication (TripDeduped CTE) — prevents one trip
--          from being counted for multiple calls. Road accident scenario
--          (same phone, different Case IDs) correctly preserved.
--   FIX 2: Time window reduced from ±180 to ±90 minutes — safer for
--          healthcare data, eliminates false positive matches.
--   FIX 3: Agent Disposition normalization — merges duplicate format
--          variants (e.g. 'Silent Call' / 'SilentCall' → 'SilentCall').
--   FIX 4: \N district values replaced with 'Unknown'.
-- ============================================================================

-- -----------------------------------------------------------------------------
-- SOURCE SCHEMA REFERENCE
-- -----------------------------------------------------------------------------
--
-- TABLE: CallHits  (Call Center Dispatch Log)
-- Column              | Description
-- --------------------+----------------------------------------------------
-- Phone Number        | Caller's phone number
-- Call Start Time     | Timestamp when the call was received
-- Agent Disposition   | Call outcome (EmergencyCall, etc.)
-- District            : District from which the call originated
--
-- TABLE: RawData  (Ambulance Trip / Dispatch Records)
-- Column                | Description
-- ----------------------+--------------------------------------------------
-- Date                  | Date of the ambulance trip
-- Agrent CONNECTED TIME | Timestamp when the agent connected
-- scene_arrival_time    | Timestamp when the ambulance arrived on scene
-- Case ID               | Unique case identifier
-- CALLER NO             | Caller's phone number
-- DISEASE               | Medical condition
-- Vehicle No            | Ambulance vehicle number
-- District              | District
-- Location Type         | Urban / Rural
-- -----------------------------------------------------------------------------


-- ============================================================================
-- STEP 1: CLEAN & NORMALIZE CALL RECORDS
-- ============================================================================
-- Strip spaces from phone numbers and extract the last 10 digits to create
-- a uniform join key. Assign a deterministic unique ID to every call using
-- ROW_NUMBER with a composite sort to handle duplicate timestamps.
-- Tag each call with its eligibility status for ambulance service.
--
-- FIX 3: Normalize Agent Disposition — the source data has duplicate values
-- with inconsistent spacing (e.g. 'Silent Call' vs 'SilentCall').
-- FIX 4: Replace \N district values with 'Unknown'.

WITH CleanedCalls AS (
    SELECT
        "Call Start Time",

        -- FIX 3: Normalize duplicate disposition values to a single form
        -- This ensures eligibility check doesn't miss variants like 'Inter State '
        CASE
            WHEN "Agent Disposition" IN ('Silent Call', 'SilentCall')           THEN 'SilentCall'
            WHEN "Agent Disposition" IN ('Missed Call', 'MissedCall')           THEN 'MissedCall'
            WHEN "Agent Disposition" IN ('Nuisance Call', 'NuisanceCall')       THEN 'NuisanceCall'
            WHEN "Agent Disposition" IN ('Information call', 'Informationcall') THEN 'InformationCall'
            WHEN "Agent Disposition" IN ('Wrong call', 'Wrongcall')            THEN 'WrongCall'
            WHEN "Agent Disposition" IN ('Prank Call', 'PrankCall')             THEN 'PrankCall'
            WHEN "Agent Disposition" IN ('Repeated Call', 'RepeatedCall')       THEN 'RepeatedCall'
            WHEN "Agent Disposition" IN ('Follow Up call', 'FollowUpcall')      THEN 'FollowUpCall'
            WHEN "Agent Disposition" IN ('Inter State', 'Inter State ')         THEN 'InterState'
            WHEN "Agent Disposition" IN ('Test Call', 'TestCall')               THEN 'TestCall'
            WHEN "Agent Disposition" IN ('EMT To ERO', 'EMTToERO')             THEN 'EMTToERO'
            WHEN "Agent Disposition" IN ('Call-dropped')                        THEN 'CallDropped'
            WHEN "Agent Disposition" IN ('Complaint Call')                      THEN 'ComplaintCall'
            ELSE "Agent Disposition"
        END                                                              AS Agent_Disposition,

        -- FIX 4: Replace \N, NULL-like district values with 'Unknown'
        CASE
            WHEN "District" IS NULL THEN 'Unknown'
            WHEN TRIM("District") IN ('', '\N', 'nan', 'NaN', 'None', 'NULL') THEN 'Unknown'
            ELSE TRIM("District")
        END                                                              AS Call_District,

        SUBSTR(REPLACE("Phone Number", ' ', ''), -10)                    AS Clean_Phone,

        -- Deterministic call ID — tiebreaker on phone avoids non-determinism
        ROW_NUMBER() OVER (
            ORDER BY "Call Start Time", SUBSTR(REPLACE("Phone Number", ' ', ''), -10)
        )                                                                AS Call_ID,

        -- Eligibility flag: only ambulance-relevant dispositions
        -- Uses raw disposition here since CASE result isn't available as alias
        CASE
            WHEN "Agent Disposition" IN (
                'EmergencyCall', 'InterFacilityTransfer',
                'NonEmergencyCall', 'InterState', 'Inter State', 'Inter State '
            ) THEN 1
            ELSE 0
        END                                                              AS Is_Eligible,

        -- Sequential call number per phone number to detect repeat callers
        ROW_NUMBER() OVER (
            PARTITION BY SUBSTR(REPLACE("Phone Number", ' ', ''), -10)
            ORDER BY "Call Start Time"
        )                                                                AS Call_Seq_Per_Phone,

        -- Count of total calls from the same phone number (repeat caller detection)
        COUNT(*) OVER (
            PARTITION BY SUBSTR(REPLACE("Phone Number", ' ', ''), -10)
        )                                                                AS Total_Calls_From_Phone,

        -- Rank calls within each district by time to track call volume flow
        DENSE_RANK() OVER (
            PARTITION BY "District"
            ORDER BY DATE("Call Start Time")
        )                                                                AS Day_Rank_In_District

    FROM CallHits
    WHERE "Call Start Time" IS NOT NULL
),


-- ============================================================================
-- STEP 2: CLEAN & ENRICH AMBULANCE TRIP RECORDS
-- ============================================================================
-- Normalize phone numbers, compute response time (scene arrival minus agent
-- connected time), and classify each trip by urban/rural location.
-- FIX 4: District \N handling applied here too.

CleanedTrips AS (
    SELECT
        "Agrent CONNECTED TIME"                                          AS Trip_Connected_Time,
        "scene_arrival_time"                                             AS Scene_Arrival_Time,
        "Case ID",
        "DISEASE",
        "Vehicle No",

        -- FIX 4: Normalize trip district
        CASE
            WHEN "District" IS NULL THEN 'Unknown'
            WHEN TRIM("District") IN ('', '\N', 'nan', 'NaN', 'None', 'NULL') THEN 'Unknown'
            ELSE TRIM("District")
        END                                                              AS Trip_District,

        "Location Type",
        SUBSTR(REPLACE("CALLER NO", ' ', ''), -10)                       AS Clean_Phone_Raw,

        -- Response Time (ART) in minutes: scene arrival - agent connected
        ROUND(
            (JULIANDAY("scene_arrival_time") - JULIANDAY("Agrent CONNECTED TIME")) * 1440,
            2
        )                                                                AS Response_Time_Mins,

        -- Urban / Rural classification for SLA bucketing
        CASE
            WHEN "Location Type" LIKE '%Urban%' THEN 'Urban'
            WHEN "Location Type" LIKE '%Rural%' THEN 'Rural'
            ELSE 'Unclassified'
        END                                                              AS Location_Category,

        -- Rank trips per phone to handle multiple dispatches for same caller
        ROW_NUMBER() OVER (
            PARTITION BY SUBSTR(REPLACE("CALLER NO", ' ', ''), -10)
            ORDER BY "Agrent CONNECTED TIME"
        )                                                                AS Trip_Seq_Per_Phone,

        -- Running count of trips per district (dispatch load tracking)
        COUNT(*) OVER (
            PARTITION BY "District"
        )                                                                AS District_Trip_Volume,

        -- Percentile rank of response time within the district
        PERCENT_RANK() OVER (
            PARTITION BY "District"
            ORDER BY (JULIANDAY("scene_arrival_time") - JULIANDAY("Agrent CONNECTED TIME")) * 1440
        )                                                                AS Response_Time_Percentile

    FROM RawData
    WHERE "Agrent CONNECTED TIME" IS NOT NULL
),


-- ============================================================================
-- STEP 3: PHONE + TIME-PROXIMITY JOIN (CORRELATION ENGINE)
-- ============================================================================
-- Match calls to trips using cleaned phone numbers.
-- FIX 2: Window reduced from ±180 to ±90 minutes.
-- In emergency ambulance service, if a trip hasn't been dispatched within
-- ~90 minutes of a call, it's very unlikely to be the same incident.
-- The time constraint is applied inside the ON clause (not WHERE) to
-- preserve unmatched calls via LEFT JOIN.

PotentialMatches AS (
    SELECT
        c.Call_ID,
        c."Call Start Time",
        c.Clean_Phone,
        c.Agent_Disposition,
        c.Call_District,
        c.Is_Eligible,
        c.Call_Seq_Per_Phone,
        c.Total_Calls_From_Phone,
        c.Day_Rank_In_District,

        t."Case ID",
        t.Trip_Connected_Time,
        t.Scene_Arrival_Time,
        t."DISEASE",
        t."Vehicle No",
        t.Trip_District,
        t.Location_Category,
        t.Response_Time_Mins,
        t.Response_Time_Percentile,

        -- Time gap between call and trip (minutes), used for proximity scoring
        ROUND(
            (JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c."Call Start Time")) * 1440,
            2
        )                                                                AS Time_Gap_Mins,

        -- Absolute time gap for symmetric matching
        ROUND(
            ABS((JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c."Call Start Time")) * 1440),
            2
        )                                                                AS Abs_Time_Gap_Mins

    FROM CleanedCalls c
    LEFT JOIN CleanedTrips t
        ON  c.Clean_Phone = t.Clean_Phone_Raw
        AND ABS(
                (JULIANDAY(t.Trip_Connected_Time) - JULIANDAY(c."Call Start Time")) * 1440
            ) <= 90    -- FIX 2: Reduced from 180 to 90 minutes (safer for healthcare)
),


-- ============================================================================
-- STEP 4: BEST-MATCH SELECTION (CLOSEST TIME GAP WINS)
-- ============================================================================
-- For each call, rank all candidate trip matches by absolute time proximity.
-- NULL matches (unmatched calls) are pushed to the bottom so they appear
-- only when no real match exists.

RankedMatches AS (
    SELECT
        *,
        -- Primary ranking: closest time gap wins; NULLs (no match) sink to bottom
        ROW_NUMBER() OVER (
            PARTITION BY Call_ID
            ORDER BY
                CASE WHEN "Case ID" IS NULL THEN 1 ELSE 0 END,
                Abs_Time_Gap_Mins ASC
        )                                                                AS Match_Rank,

        -- Count of candidate matches per call (indicates ambiguity)
        SUM(CASE WHEN "Case ID" IS NOT NULL THEN 1 ELSE 0 END) OVER (
            PARTITION BY Call_ID
        )                                                                AS Candidate_Match_Count

    FROM PotentialMatches
),


-- ============================================================================
-- STEP 4b: SMART TRIP DEDUPLICATION (FIX 1)
-- ============================================================================
-- After Step 4, each CALL has its best trip. But one TRIP (Case_ID) can
-- still be claimed by multiple calls simultaneously. This inflates
-- Service Coverage %.
--
-- Smart dedup logic:
--   • PARTITION BY "Case ID" — group all calls claiming the same trip
--   • ORDER BY Abs_Time_Gap_Mins — closest call wins
--   • Trip_Usage_Rank = 1 → this call legitimately "owns" the trip
--   • Trip_Usage_Rank > 1 → duplicate claim, demoted to 'Not Served'
--
-- Road accident handling:
--   If 3 calls from one phone match 3 DIFFERENT Case_IDs → each has its
--   own partition → all get Trip_Usage_Rank = 1 → all Served ✓
--   If 3 calls match the SAME Case_ID → only closest gets rank 1,
--   other 2 become 'Not Served' → prevents inflation ✓

TripDeduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY "Case ID"
            ORDER BY Abs_Time_Gap_Mins ASC
        ) AS Trip_Usage_Rank
    FROM RankedMatches
    WHERE Match_Rank = 1
      AND "Case ID" IS NOT NULL
),


-- ============================================================================
-- STEP 5: FINAL CORRELATED DATASET (ONE ROW PER CALL)
-- ============================================================================
-- Combines three sets:
--   1. Matched calls that legitimately own their trip (TripDeduped rank=1)
--   2. Matched calls whose trip was claimed by a closer call (demoted)
--   3. Unmatched calls (no trip found)

CorrelatedCalls AS (
    -- 1. Calls that legitimately own their matched trip
    SELECT
        Call_ID,
        "Call Start Time",
        Clean_Phone,
        Agent_Disposition,
        Call_District,
        Is_Eligible,
        Call_Seq_Per_Phone,
        Total_Calls_From_Phone,
        Day_Rank_In_District,
        Candidate_Match_Count,

        "Case ID",
        Trip_Connected_Time,
        Scene_Arrival_Time,
        "DISEASE",
        "Vehicle No",
        Trip_District,
        Location_Category,
        Response_Time_Mins,
        Response_Time_Percentile,
        Time_Gap_Mins,
        Abs_Time_Gap_Mins,

        'Served' AS Service_Status,

        CASE
            WHEN Abs_Time_Gap_Mins <= 60  THEN 'High'
            WHEN Abs_Time_Gap_Mins <= 90  THEN 'Medium'
            ELSE 'Low'
        END                                                              AS Match_Confidence,

        ROUND(
            (JULIANDAY(Scene_Arrival_Time) - JULIANDAY("Call Start Time")) * 1440,
            2
        )                                                                AS Scene_Arrival_TAT_Mins,

        CASE
            WHEN Location_Category = 'Urban'
                 AND Response_Time_Mins IS NOT NULL
                 AND Response_Time_Mins > 0
                 AND Response_Time_Mins <= 15 THEN 1
            ELSE 0
        END                                                              AS Urban_SLA_Met,

        CASE
            WHEN Location_Category = 'Rural'
                 AND Response_Time_Mins IS NOT NULL
                 AND Response_Time_Mins > 0
                 AND Response_Time_Mins <= 30 THEN 1
            ELSE 0
        END                                                              AS Rural_SLA_Met,

        CASE
            WHEN Total_Calls_From_Phone > 1 THEN 'Repeat Caller'
            ELSE 'Single Caller'
        END                                                              AS Caller_Type

    FROM TripDeduped
    WHERE Trip_Usage_Rank = 1

    UNION ALL

    -- 2. Calls whose matched trip was claimed by a closer call (demoted)
    SELECT
        Call_ID, "Call Start Time", Clean_Phone, Agent_Disposition,
        Call_District, Is_Eligible, Call_Seq_Per_Phone,
        Total_Calls_From_Phone, Day_Rank_In_District, Candidate_Match_Count,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        'Not Served' AS Service_Status,
        'No Match'   AS Match_Confidence,
        NULL AS Scene_Arrival_TAT_Mins,
        0 AS Urban_SLA_Met,
        0 AS Rural_SLA_Met,
        CASE WHEN Total_Calls_From_Phone > 1 THEN 'Repeat Caller' ELSE 'Single Caller' END AS Caller_Type
    FROM TripDeduped
    WHERE Trip_Usage_Rank > 1

    UNION ALL

    -- 3. Unmatched calls (no trip found at all)
    SELECT
        Call_ID, "Call Start Time", Clean_Phone, Agent_Disposition,
        Call_District, Is_Eligible, Call_Seq_Per_Phone,
        Total_Calls_From_Phone, Day_Rank_In_District, Candidate_Match_Count,
        NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        'Not Served' AS Service_Status,
        'No Match'   AS Match_Confidence,
        NULL AS Scene_Arrival_TAT_Mins,
        0 AS Urban_SLA_Met,
        0 AS Rural_SLA_Met,
        CASE WHEN Total_Calls_From_Phone > 1 THEN 'Repeat Caller' ELSE 'Single Caller' END AS Caller_Type
    FROM RankedMatches
    WHERE Match_Rank = 1
      AND "Case ID" IS NULL
),


-- ============================================================================
-- STEP 6: DISTRICT-LEVEL KPI AGGREGATION
-- ============================================================================
-- Roll up correlated call data into district-level performance metrics.
-- Uses window functions over the aggregated results for cross-district
-- ranking and contribution analysis.

DistrictKPIs AS (
    SELECT
        Call_District                                                     AS District,

        -- Volume metrics
        COUNT(*)                                                         AS Total_Calls,
        SUM(CASE WHEN Is_Eligible = 1 THEN 1 ELSE 0 END)                AS Eligible_Calls,
        SUM(CASE WHEN Service_Status = 'Served' THEN 1 ELSE 0 END)      AS Served_Calls,
        SUM(CASE WHEN Service_Status = 'Not Served'
                  AND Is_Eligible = 1 THEN 1 ELSE 0 END)                AS Eligible_Not_Served,

        -- Conversion & Coverage
        ROUND(
            SUM(CASE WHEN Service_Status = 'Served' THEN 1.0 ELSE 0 END)
            / NULLIF(COUNT(*), 0) * 100, 2
        )                                                                AS Call_To_Trip_Conversion_Pct,

        -- FIX: Coverage uses ELIGIBLE + SERVED, not just SERVED
        ROUND(
            SUM(CASE WHEN Service_Status = 'Served' AND Is_Eligible = 1 THEN 1.0 ELSE 0 END)
            / NULLIF(SUM(CASE WHEN Is_Eligible = 1 THEN 1 ELSE 0 END), 0) * 100, 2
        )                                                                AS Service_Coverage_Pct,

        -- Average Response Time (ART)
        ROUND(AVG(Response_Time_Mins), 2)                                AS Overall_ART_Mins,

        ROUND(AVG(CASE
            WHEN Location_Category = 'Urban' THEN Response_Time_Mins
        END), 2)                                                         AS Urban_ART_Mins,

        ROUND(AVG(CASE
            WHEN Location_Category = 'Rural' THEN Response_Time_Mins
        END), 2)                                                         AS Rural_ART_Mins,

        -- SLA Compliance Percentages
        ROUND(
            SUM(Urban_SLA_Met) * 100.0
            / NULLIF(SUM(CASE WHEN Location_Category = 'Urban'
                              AND Response_Time_Mins IS NOT NULL THEN 1 ELSE 0 END), 0),
            2
        )                                                                AS Urban_SLA_Compliance_Pct,

        ROUND(
            SUM(Rural_SLA_Met) * 100.0
            / NULLIF(SUM(CASE WHEN Location_Category = 'Rural'
                              AND Response_Time_Mins IS NOT NULL THEN 1 ELSE 0 END), 0),
            2
        )                                                                AS Rural_SLA_Compliance_Pct,

        -- Scene Arrival TAT
        ROUND(AVG(Scene_Arrival_TAT_Mins), 2)                            AS Avg_Scene_Arrival_TAT_Mins,

        -- Confidence distribution
        SUM(CASE WHEN Match_Confidence = 'High'   THEN 1 ELSE 0 END)    AS High_Confidence_Matches,
        SUM(CASE WHEN Match_Confidence = 'Medium' THEN 1 ELSE 0 END)    AS Medium_Confidence_Matches,
        SUM(CASE WHEN Match_Confidence = 'Low'    THEN 1 ELSE 0 END)    AS Low_Confidence_Matches

    FROM CorrelatedCalls
    GROUP BY Call_District
),


-- ============================================================================
-- STEP 7: DISTRICT RANKING & CROSS-DISTRICT ANALYTICS
-- ============================================================================
-- Layer window functions over the aggregated district KPIs for comparative
-- ranking across multiple performance dimensions.

DistrictRanked AS (
    SELECT
        *,

        -- Rank districts by response time (lower ART = better rank)
        RANK() OVER (ORDER BY Overall_ART_Mins ASC)                      AS ART_Rank,

        -- Rank districts by service coverage (higher = better)
        RANK() OVER (ORDER BY Service_Coverage_Pct DESC)                 AS Coverage_Rank,

        -- Rank districts by call volume (busiest first)
        RANK() OVER (ORDER BY Total_Calls DESC)                          AS Volume_Rank,

        -- Each district's share of total state-wide calls
        ROUND(
            Total_Calls * 100.0 / SUM(Total_Calls) OVER (), 2
        )                                                                AS Pct_Of_Total_Calls,

        -- Each district's share of total served trips
        ROUND(
            Served_Calls * 100.0 / NULLIF(SUM(Served_Calls) OVER (), 0), 2
        )                                                                AS Pct_Of_Total_Served,

        -- Running cumulative percentage of calls (for Pareto analysis)
        ROUND(
            SUM(Total_Calls) OVER (ORDER BY Total_Calls DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            * 100.0 / SUM(Total_Calls) OVER (), 2
        )                                                                AS Cumulative_Call_Pct,

        -- Deviation of district ART from state average
        ROUND(
            Overall_ART_Mins - AVG(Overall_ART_Mins) OVER (), 2
        )                                                                AS ART_Deviation_From_Avg,

        -- State-wide averages for benchmarking
        ROUND(AVG(Overall_ART_Mins) OVER (), 2)                          AS State_Avg_ART,
        ROUND(AVG(Service_Coverage_Pct) OVER (), 2)                      AS State_Avg_Coverage

    FROM DistrictKPIs
)


-- ============================================================================
-- FINAL OUTPUT: DISTRICT PERFORMANCE SCORECARD
-- ============================================================================

SELECT
    District,

    -- Volume
    Total_Calls,
    Eligible_Calls,
    Served_Calls,
    Eligible_Not_Served,

    -- Conversion & Coverage KPIs
    Call_To_Trip_Conversion_Pct,
    Service_Coverage_Pct,

    -- Response Time KPIs
    Overall_ART_Mins,
    Urban_ART_Mins,
    Rural_ART_Mins,
    Avg_Scene_Arrival_TAT_Mins,

    -- SLA Compliance
    Urban_SLA_Compliance_Pct     AS "Urban SLA (<=15 min) %",
    Rural_SLA_Compliance_Pct     AS "Rural SLA (<=30 min) %",

    -- Match Quality
    High_Confidence_Matches,
    Medium_Confidence_Matches,
    Low_Confidence_Matches,

    -- Cross-District Rankings
    ART_Rank,
    Coverage_Rank,
    Volume_Rank,
    Pct_Of_Total_Calls,
    Pct_Of_Total_Served,
    Cumulative_Call_Pct,

    -- Benchmarking
    ART_Deviation_From_Avg,
    State_Avg_ART,
    State_Avg_Coverage

FROM DistrictRanked
ORDER BY Volume_Rank ASC;


-- ============================================================================
-- PURPOSE & METHODOLOGY (Project Context)
-- ============================================================================
--
-- This SQL query was designed as the analytical backbone of the 108 Ambulance
-- Service KPI monitoring system for the state of Jharkhand, India. The 108
-- emergency helpline receives thousands of calls daily, but the call center
-- system (CallHits) and the ambulance dispatch system (RawData) operate as
-- independent databases with no shared transaction identifier. This creates
-- a fundamental data correlation challenge: determining which calls actually
-- resulted in ambulance dispatches, and measuring the end-to-end service
-- quality for each.
--
-- The query solves this problem through a phone-number-based probabilistic
-- matching engine. First, phone numbers from both systems are normalized by
-- stripping whitespace and extracting the last 10 digits to handle formatting
-- inconsistencies across platforms. The cleaned numbers serve as the primary
-- join key. However, phone matching alone is insufficient — a single caller
-- may place multiple calls, or the same phone number may appear across
-- unrelated incidents on different days. To resolve this ambiguity, a
-- symmetric time-proximity window of ±90 minutes is applied (reduced from
-- the original ±180 minutes after audit — the wider window was producing
-- false positive matches in healthcare data). Among all candidates, the
-- closest match by absolute time difference is selected using window-function-
-- based ranking.
--
-- v3 DEDUPLICATION: After per-call ranking, a second deduplication pass
-- ensures each ambulance trip (Case_ID) is assigned to at most one call.
-- If multiple calls claim the same trip, only the closest time match keeps
-- it — the rest are demoted to "Not Served". This prevents inflation of
-- Service Coverage %. Importantly, this correctly handles the road accident
-- scenario where one phone number dispatches multiple ambulances: since each
-- dispatch has a different Case_ID, they each form their own partition and
-- all remain as "Served".
--
-- v3 DISPOSITION NORMALIZATION: The call center data contains duplicate
-- disposition values with inconsistent formatting (e.g. 'Silent Call' vs
-- 'SilentCall', 'Inter State' vs 'InterState'). These are normalized in
-- Step 1 to ensure accurate eligibility classification. Without this fix,
-- ~56 'Inter State ' calls (with trailing space) were being wrongly
-- classified as non-eligible.
--
-- A confidence score (High ≤60 min, Medium ≤90 min) is assigned based on
-- the gap duration. With the reduced ±90 min window, all matches are either
-- High or Medium confidence — the "Low" category is effectively eliminated.
--
-- Beyond correlation, the query computes the key operational KPIs that
-- govern ambulance service performance. Average Response Time (ART) measures
-- how quickly an ambulance reaches the scene after the agent connects the
-- dispatch. SLA compliance is evaluated against government-mandated
-- benchmarks: 15 minutes for Urban areas and 30 minutes for Rural areas.
-- The Call-to-Trip Conversion Rate quantifies what fraction of incoming
-- emergency calls translate into actual ambulance dispatches, while Service
-- Coverage isolates this metric to only eligible (genuine emergency) calls
-- by filtering out prank calls, information requests, and test entries
-- using the Agent Disposition field. Scene Arrival TAT captures the total
-- elapsed time from the moment a citizen dials 108 to the ambulance
-- physically arriving at their location, representing the true end-to-end
-- patient experience metric.
--
-- At the district level, the query layers cross-district ranking using
-- RANK and cumulative aggregation window functions, enabling comparative
-- performance analysis. Each district is benchmarked against the state-wide
-- average for both ART and service coverage, with a Pareto-style cumulative
-- call distribution to identify which districts account for the majority of
-- emergency call volume. This district scorecard directly feeds into the
-- Streamlit-based interactive dashboard used by state health administrators
-- to monitor daily operations, identify underperforming districts, and
-- allocate ambulance fleet resources based on data-driven evidence.
--
-- ============================================================================
