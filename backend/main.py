import sys
import os
backend_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(backend_dir)
sys.path.append(backend_dir)
sys.path.append(parent_dir)

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
import io
import pandas as pd
import uvicorn
import report_generator

app = FastAPI(title="108 Ambulance KPI Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/generate-report")
async def generate_report(
    master_file: UploadFile = File(...),
    raw_file: UploadFile = File(...),
    equipments_file: UploadFile = File(None),
    calls_file: UploadFile = File(...),
    hoto_only: bool = False
):
    try:
        # Load sheets in memory
        master_bytes = await master_file.read()
        raw_bytes = await raw_file.read()
        calls_bytes = await calls_file.read()
        
        def read_excel_smart(file_bytes, filename, candidates):
            if filename and filename.lower().endswith('.csv'):
                return pd.read_csv(io.BytesIO(file_bytes), low_memory=False)
            try:
                engine = 'openpyxl' if (filename and filename.lower().endswith('.xlsx')) else 'xlrd' if (filename and filename.lower().endswith('.xls')) else None
                xl = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
                sheet_names = xl.sheet_names
                for cand in candidates:
                    cand_lower = cand.lower().strip()
                    for name in sheet_names:
                        if cand_lower in name.lower():
                            return xl.parse(name)
                return xl.parse(0)
            except Exception as ve:
                try:
                    return pd.read_csv(io.BytesIO(file_bytes))
                except Exception:
                    raise ve
            
        master_df = read_excel_smart(master_bytes, master_file.filename, ['master'])
        raw_df = read_excel_smart(raw_bytes, raw_file.filename, ['raw data', 'raw trips', 'trips', 'trip data'])
        calls_df = read_excel_smart(calls_bytes, calls_file.filename, ['callhi', 'call hits', 'callhits', 'calls', 'call log', 'call'])
        
        if equipments_file:
            eq_bytes = await equipments_file.read()
            eq_df = read_excel_smart(eq_bytes, equipments_file.filename, ['equipment', 'audit', 'response'])
        else:
            eq_df = pd.DataFrame()
            
        excel_data, date_str = report_generator.generate_excel(master_df, raw_df, eq_df, calls_df, hoto_only=hoto_only)
        
        filename = f"KPI_Report_HOTO_Only{date_str}.xlsx" if hoto_only else f"KPI_Report{date_str}.xlsx"
        return StreamingResponse(
            io.BytesIO(excel_data),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating KPI report: {str(e)}")

# Mount static files
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_path, exist_ok=True)
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)