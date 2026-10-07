import os
import sys

import pandas as pd
import pyodbc
from dotenv import load_dotenv

# === CONFIGURATION ===
EXCEL_FILE = r"C:\Users\nguyeb3\Downloads\Delete prod ver.xlsx"  # Update with your file path
MATERIAL_COLUMN = "Material"                  # Update with your column name
SHEET_NAME = 0


def clean_string(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return value


# ============================================================
# SQL CONNECTION
# ============================================================
def get_sql_connection():
    load_dotenv()
    conn_str = (
        f"DRIVER={{{os.getenv('SQL_DRIVER', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={os.getenv('SQL_SERVER')};"
        f"DATABASE={os.getenv('SQL_DATABASE')};"
        f"UID={os.getenv('SQL_USERNAME')};"
        f"PWD={os.getenv('SQL_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


# ============================================================
# VERIFY MATERIALS
# ============================================================
def verify_materials(excel_path, material_column, sheet_name=0):
    df = pd.read_excel(excel_path, sheet_name=sheet_name)

    if material_column not in df.columns:
        print(f"ERROR: Column '{material_column}' not found.")
        print(f"Available columns: {list(df.columns)}")
        sys.exit(1)

    materials = (
        df[material_column]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .unique()
        .tolist()
    )
    print(f"Found {len(materials)} unique material(s) in Excel.\n")

    if not materials:
        print("No materials to check.")
        return

    placeholders = ",".join(["?"] * len(materials))
    query = f"""
        SELECT DISTINCT
            C.ES_ToolPlanMatrixName
        FROM EXCRSCH.ES_ToolPlanMatrix C WITH (NOLOCK)
        JOIN EXCRSch.ES_ToolPlanMatrixDetails cd WITH (NOLOCK)
            ON C.ES_ToolPlanMatrixId = cd.ES_ToolPlanMatrixId
        WHERE C.ES_ToolPlanMatrixName IN ({placeholders})
    """

    with get_sql_connection() as conn:
        result_df = pd.read_sql(query, conn, params=materials)

    found_materials = set(result_df["ES_ToolPlanMatrixName"].astype(str).str.strip())

    df["TPM_Exist"] = df[material_column].apply(
        lambda x: "Found" if clean_string(x) in found_materials else "Not Found"
    )

    found_count = (df["TPM_Exist"] == "Found").sum()
    not_found_count = (df["TPM_Exist"] == "Not Found").sum()

    print(f"{'='*60}")
    print(f" FOUND in ToolPlanMatrix: {found_count}")
    print(f" NOT FOUND:              {not_found_count}")
    print(f"{'='*60}\n")

    # Write result back to the input file
    df.to_excel(excel_path, sheet_name=sheet_name if isinstance(sheet_name, str) else "Sheet1", index=False)
    print(f"Results written back to: {excel_path}")


if __name__ == "__main__":
    verify_materials(EXCEL_FILE, MATERIAL_COLUMN, SHEET_NAME)
