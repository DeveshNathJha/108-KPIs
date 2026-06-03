# 108 Ambulance KPI Dashboard — v3

> **Project:** 108 Emergency Ambulance Service — Performance Monitoring System  
> **Stack:** Python · Streamlit · FastAPI · Pandas · SQLite (In-Memory)  
> **Core Files:** `kpi_dashboard.py` (Streamlit UI) | `backend/main.py` (FastAPI Server) | `backend/report_generator.py` (Excel logic) | `sql_engine.py` (Backend SQL Logic)


---

## 1. Project Overview

This system monitors the **108 Emergency Ambulance Service** by automatically integrating and correlating **four core operational registers** using a sophisticated in-memory SQL correlation pipeline:

1. **Call Hits Log (`Call Hits File`)** — Call center logs recording every call that came in.
2. **Raw Trips Data (`Raw Data File`)** — Dispatch operations records showing completed ambulance trips with ODO readings, caller numbers, and times.
3. **Master Data (`Master File`)** — The vehicle master registry listing active ambulance registrations, GPS installation status, operational status, vehicle type, and HOTO status.
4. **Equipments Audit (`Equipments File`)** — Live equipment audit records (often collected via Google Forms) tracking medical inventory status (Working/Not Working/Not Available) per ambulance.

By bringing these four separate sources together, the system dynamically calculates vehicle-level performance metrics, daily call trends, and district-level operational health summaries while filtering for active HOTO fleets.

## 2. Architecture & File Structure

The project has been architected for high-speed calculation using an **In-Memory SQLite Engine**.

- **`backend/main.py`**: The FastAPI server. Exposes the `/api/generate-report` endpoint to ingest all 4 files, orchestrate calculations, and serve the styled Excel output.
- **`backend/static/index.html`**: A premium glassmorphism Web UI serving as the control hub for upload, processing, and download of HOTO and Full reports.
- **`kpi_dashboard.py`**: A Streamlit frontend providing interactive dashboard charts, date filtering, and live scorecard metrics.
- **`sql_engine.py`**: The core correlation engine. Executes high-speed probabilistic SQL matching (using phone + time proximity) inside an in-memory SQLite database.
- **`backend/report_generator.py`**: The Excel report builder. Applies deep sanitization filters, calculates equipment health risk indices, and renders multiple dashboard sheets.
- **`query.sql`**: A standalone SQL file containing the query blueprints for manual execution and review. 

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
cd /home/deveshjha/Downloads/108_KPI_Code
streamlit run kpi_dashboard.py
```

**Data Upload Requirements:**
You upload four core files (in `.xlsx` or `.csv` format):
1. **Master Data** (Must contain: `Registration No.` / `Registration No`, `GPS`, `HOTO Status` / `HOTO or not`, `Operational / Non-Operational`, `Type of Vehicle`)
2. **Raw Trips Data** (Must contain: `Date`, `Agrent CONNECTED TIME`, `assigned_time`, `scene_arrival_time`, `Location Type`, `DISEASE`, `District` / `Distict`, `CALLER NO`, `Vehicle No`, `Case ID`, `Base Start ODO`, `Base End ODO`)
3. **Equipments Audit** (Must contain: `VEHICLE NUMBER` and individual column headers for each standard medical equipment, e.g., `Cervical Collar`, `Pulse Oximeter`, `Suction Machine (Electric)`)
4. **Call Hits Log** (Must contain: `Call Start Time`, `Agent Disposition` / `Dialer Disposition`, `District`, `Phone Number`, `Call Connect Time`, `Call End Time`, `QUEUE Duration`, `RING Duration`)

---
*Last Updated: June 2026*
