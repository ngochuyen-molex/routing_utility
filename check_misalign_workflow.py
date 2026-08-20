import os
from pathlib import Path
import pandas as pd
import pyodbc
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================
INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\check_workflow.xlsx")
OUTPUT_FILE = Path("output/output_workflow_check.xlsx")


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


def fetch_tpm_workflow_mismatch(materials):
    if not materials:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(materials))

    query = f"""
    SELECT
        tpm.ES_ToolPlanMatrixName AS Name,
        tpm.Description,
        tpm.Notes,
        r.ResourceName AS Resource,
        tp.ToolPlanName AS ToolPlan,
        sb.SpecName AS SpecName,
        tpmd.mlxIdealCycleTime,
        tpmd.mlxProductionVersion,
        tpmd.mlxPriority,
        erb.ERPRouteName AS mlxERPRoute,
        ws.WorkflowStepName AS [workflow.StepName],
        rs.Name AS [workflow.RouteStepName],
        ws.Sequence AS [workflow.Sequence],
        erb_wf.ERPRouteName AS [workflow.ERPRouteName]
    FROM EXCRSch.ES_ToolPlanMatrix tpm

    LEFT JOIN EXCRSch.ES_ToolPlanMatrixDetails tpmd
        ON tpmd.ES_ToolPlanMatrixId = tpm.ES_ToolPlanMatrixId
        AND tpmd.hvr_is_deleted = 0

    LEFT JOIN EXCRSch.SpecBase sb
        ON sb.SpecBaseId = tpmd.SpecBaseId
        AND sb.hvr_is_deleted = 0

    LEFT JOIN EXCRSch.ResourceDef r
        ON r.ResourceId = tpmd.ResourceId
        AND r.hvr_is_deleted = 0

    LEFT JOIN EXCRSch.A_ToolPlan tp
        ON tp.ToolPlanId = tpmd.ToolPlanId
        AND tp.hvr_is_deleted = 0

    LEFT JOIN EXCRSch.ERPRouteBase erb
        ON erb.ERPRouteBaseId = tpmd.mlxERPRouteBaseId
        AND erb.hvr_is_deleted = 0

    INNER JOIN [STDS].[EXCRSCh].ERPRouteBase erb_wf WITH(NOLOCK)
        ON erb_wf.ERPRouteName = erb.ERPRouteName

    INNER JOIN [STDS].[EXCRSCh].ERPRoute erp WITH(NOLOCK)
        ON erp.ERPRouteBaseId = erb_wf.ERPRouteBaseId

    INNER JOIN [STDS].[EXCRSCh].Workflow wf WITH(NOLOCK)
        ON wf.ERPRouteId = erp.ERPRouteId
        OR (wf.ERPRouteId = '0000000000000000' AND wf.ERPRouteBaseId = erb_wf.ERPRouteBaseId)

    LEFT JOIN [STDS].[EXCRSCh].WorkflowStep ws WITH(NOLOCK)
        ON ws.WorkflowId = wf.WorkflowId

    LEFT JOIN [STDS].[EXCRSCh].RouteStep rs WITH(NOLOCK)
        ON rs.RouteStepId = ws.RouteStepId

    WHERE
        tpm.hvr_is_deleted = 0
        AND tpm.ES_ToolPlanMatrixName IN ({placeholders})
        AND ws.Sequence = 3
        AND LTRIM(RTRIM(LOWER(sb.SpecName))) <> LTRIM(RTRIM(LOWER(ws.WorkflowStepName)))

    ORDER BY
        tpm.ES_ToolPlanMatrixName,
        tpmd.mlxPriority
    """

    with get_sql_connection() as conn:
        df = pd.read_sql(query, conn, params=materials)

    return df


def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading input file...")
    input_df = pd.read_excel(INPUT_FILE, dtype=str)

    # Read Material column and deduplicate
    materials = input_df["Material"].dropna().str.strip().unique().tolist()
    print(f"Found {len(materials)} unique materials.")

    print("Fetching TPM vs Workflow mismatches...")
    result_df = fetch_tpm_workflow_mismatch(materials)

    print(f"Found {len(result_df)} mismatched rows.")
    result_df.to_excel(OUTPUT_FILE, index=False)
    print(f"Output saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()