import io
import os
import sys
import streamlit as st
import pandas as pd

# Add backend directory to sys.path to import report_generator
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))
try:
    import report_generator
except ImportError:
    st.error("Could not import report_generator from backend folder.")

st.set_page_config(
    page_title="108 Ambulance KPI Analyzer",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom modern styling
st.markdown("""
<style>
    .main {
        background-color: #0f172a;
    }
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        color: #f8fafc;
    }
    h1, h2, h3 {
        font-family: 'Outfit', sans-serif !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
    }
    div[data-testid="stMarkdownContainer"] p {
        color: #94a3b8;
    }
    div[data-testid="stMetricValue"] {
        color: #06b6d4 !important;
        font-weight: 700;
    }
    div[data-testid="metric-container"] {
        background: rgba(255, 255, 255, 0.03) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px;
        padding: 15px !important;
    }
    .stButton>button {
        background: linear-gradient(135deg, #06b6d4 0%, #3b82f6 100%) !important;
        color: white !important;
        border: none !important;
        padding: 10px 24px !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        box-shadow: 0 4px 15px rgba(6, 182, 212, 0.25) !important;
        width: 100%;
        transition: all 0.3s;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(6, 182, 212, 0.4) !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("108 Ambulance KPI Analyzer")
st.markdown("Compile district-wide operational metrics, check equipment health levels, and pivot daily metrics with integrated HOTO, GPS, and Operational statuses.")

st.markdown("---")

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Upload Operational Data Files")
    master_file = st.file_uploader("Vehicle Master Data", type=["xlsx", "xls", "csv"], help="Upload the vehicle master sheet")
    raw_file = st.file_uploader("Raw Trips Data", type=["xlsx", "xls", "csv"], help="Upload the ambulance raw trips sheet")
    
with col2:
    st.subheader("2. Upload Audit & Logs")
    eq_file = st.file_uploader("Equipments Audit Data (Optional)", type=["xlsx", "xls", "csv"], help="Upload the Google Form responses for equipment audit (Optional)")
    calls_file = st.file_uploader("Call Hits Log", type=["xlsx", "xls", "csv"], help="Upload the call center log sheet")

st.markdown("---")

hoto_only = st.checkbox("Filter for HOTO Only Vehicles", help="Check this box to limit the report to Handed Over / Taken Over vehicles")

if st.button("Generate Report"):
    if not (master_file and raw_file and calls_file):
        st.error("Please upload all required files (Master Data, Raw Trips, and Call Hits).")
    else:
        with st.spinner("Processing files and correlating data using SQL engine..."):
            try:
                # Helper function to read file into DataFrame
                def read_excel_smart(uploaded_file, candidates):
                    filename = uploaded_file.name
                    file_bytes = uploaded_file.read()
                    if filename.lower().endswith('.csv'):
                        return pd.read_csv(io.BytesIO(file_bytes))
                    try:
                        engine = 'openpyxl' if filename.lower().endswith('.xlsx') else 'xlrd' if filename.lower().endswith('.xls') else None
                        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
                        sheet_names = xl.sheet_names
                        for cand in candidates:
                            cand_lower = cand.lower().strip()
                            for name in sheet_names:
                                if cand_lower in name.lower():
                                    return xl.parse(name)
                        return xl.parse(0)
                    except Exception:
                        try:
                            return pd.read_csv(io.BytesIO(file_bytes))
                        except Exception as e:
                            raise ValueError(f"Failed to read {filename}: {str(e)}")

                master_df = read_excel_smart(master_file, ['master'])
                raw_df = read_excel_smart(raw_file, ['raw data', 'raw trips', 'trips', 'trip data'])
                calls_df = read_excel_smart(calls_file, ['callhi', 'call hits', 'callhits', 'calls', 'call log', 'call'])
                
                if eq_file:
                    eq_df = read_excel_smart(eq_file, ['equipment', 'audit', 'response'])
                else:
                    eq_df = pd.DataFrame()
                
                # Generate Report Excel using same report_generator logic
                excel_data, date_str = report_generator.generate_excel(
                    master_df, raw_df, eq_df, calls_df, hoto_only=hoto_only
                )
                
                filename = f"KPI_Report_HOTO_Only{date_str}.xlsx" if hoto_only else f"KPI_Report{date_str}.xlsx"
                
                st.success("Report compiled successfully!")
                
                # Show key metrics in dashboard
                st.subheader("Summary Preview")
                
                # Reload sheets from the generated excel bytes to display them interactively
                excel_file = pd.ExcelFile(io.BytesIO(excel_data))
                if 'Summary' in excel_file.sheet_names:
                    summary_preview = excel_file.parse('Summary')
                    st.dataframe(summary_preview, use_container_width=True, hide_index=True)
                
                st.download_button(
                    label="Download Excel Report",
                    data=excel_data,
                    file_name=filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except Exception as e:
                st.error(f"Error during execution: {str(e)}")
                st.exception(e)
