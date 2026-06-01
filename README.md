# 108 Ambulance KPI Dashboard — v3

> **Project:** 108 Emergency Ambulance Service — Performance Monitoring System  
> **Stack:** Python · Streamlit · FastAPI · Pandas · SQLite (In-Memory)  
> **Core Files:** `kpi_dashboard.py` (Streamlit UI) | `backend/main.py` (FastAPI Server) | `backend/report_generator.py` (Excel logic) | `sql_engine.py` (Backend SQL Logic)


---

## 1. Project Overview

This dashboard monitors the **108 Emergency Ambulance Service** by automatically matching two separate operational data sources using a sophisticated SQL Correlation Engine:

- **Call Hits File** — Records from the call center (every call that came in).
- **Raw Data File** — Records from dispatch operations (every ambulance trip that was completed).

The dashboard successfully solves the data-silo problem: determining which calls resulted in ambulance dispatches, and measuring end-to-end service quality.

## 2. Architecture & File Structure

The project has been refactored for speed and accuracy using an **In-Memory SQLite Engine**.

- **`kpi_dashboard.py`**: The Streamlit frontend. Handles file uploads, date/district filters, KPI scorecard generation, and UI components.
- **`sql_engine.py`**: The backend correlation engine. When files are uploaded, this script loads the data into memory, normalizes the dates and string values, and executes a large SQLite query to perform phone number & time-proximity matching.
- **`query.sql`**: A standalone SQL file. **This file is for documentation and review.** It contains the exact SQL logic used inside `sql_engine.py` but is separated out so you can read the logic with SQL syntax highlighting, comments, and structure. 

## 3. The SQL Correlation Engine (v3 Fixes)

The correlation engine performs the following key steps:

1. **Normalization**: Phone numbers are stripped of spaces to last 10 digits. Dispositions like "Silent Call" and "SilentCall" are merged. Blank/NULL districts are mapped to 'Unknown', and "Other" or "other" districts are also normalized.
2. **Proximity Matching**: A call and a trip are matched if they share the same phone number AND the time difference is **within ±90 minutes**.
3. **Trip Deduplication**: If multiple calls match the same Trip ID, only the closest call gets the trip. The rest are marked as 'Not Served' (prevents inflating the Service Coverage %).
4. **District Backfilling**: To accurately distribute missed calls, the script backfills missing districts in the Call Hits file by looking up the known district history of the caller's phone number, or prioritizing the actual dispatch location (`Trip_District`) if a trip occurred.
5. **Ranking & SLA**: SLA flags are computed based on Location Category (Urban ≤15 mins, Rural ≤30 mins) and P90 response times are calculated.

## 4. Key Performance Indicators (KPIs)

- **Total Calls / Served Calls**: Overall volume.
- **Eligible Conversion %**: (Eligible Calls Served / Total Eligible Calls) * 100
- **Emergency Conversion %**: (Emergency Calls Served / Total Emergency Calls) * 100 - A stricter metric focusing only on high-risk cases.
- **Avg Response Time (ART)**: Average time from Call Center connection to Scene Arrival.
- **P90 Response Time**: The time within which 90% of all trips arrive. This is the worst-case scenario metric.
- **Genuine Emergency %**: Percentage of calls related to actual emergencies.
- **Case Type Distribution**: Medical conditions are mapped from 44 raw text values into 10 clean clinical categories (e.g., Maternal, Trauma, Cardiac/Stroke).

## 5. How to Run the Dashboard

**Prerequisites:**
```bash
pip install streamlit pandas numpy openpyxl
```

**Run the Application:**
```bash
cd /home/deveshjha/108-KPI
streamlit run kpi_dashboard.py
```

**Data Upload Requirements:**
You need two `.xlsx` files:
1. **Raw Data** (Must contain: Date, Agrent CONNECTED TIME, scene_arrival_time, Location Type, DISEASE, District, CALLER NO, Vehicle No, Case ID)
2. **Call Hits** (Must contain: Call Start Time, Agent Disposition, District, Phone Number)

---
*Last Updated: May 2026*
