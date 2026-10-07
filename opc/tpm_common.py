import os

import pandas as pd
import pyodbc
from dotenv import load_dotenv

OUTPUT_COLUMNS = [
    "Name",
    "Description",
    "Notes",
    "ToolPlan",
    "Spec",
    "Resource",
    "mlxIdealCycleTime",
    "mlxProductionVersion",
    "mlxPriority",
    "mlxERPRoute",
    "RowType"
]

# ============================================================
# HELPERS
# ============================================================
def clean_string(value):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    if value.endswith(".0"):
        value = value[:-2]

    return value

def clean_tool(value):
    tool = clean_string(value)
    return "" if tool.upper() in ["0", "0.0", "NULL", "NONE", "NAN"] else tool

def validate_input_columns(df, required_columns):
    missing_columns = sorted(set(required_columns) - set(df.columns))

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}. "
            f"Columns found: {list(df.columns)}"
        )


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
# FETCH EXISTING TPM
# ============================================================
def fetch_existing_tool_plan_matrix(materials):

    if not materials:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    placeholders = ",".join(["?"] * len(materials))

    query = f"""
    SELECT
        tpm.ES_ToolPlanMatrixName AS Name,
        tpm.Description,
        tpm.Notes,
        r.ResourceName AS Resource,
        tp.ToolPlanName AS ToolPlan,
        sb.SpecName AS Spec,
        tpmd.mlxIdealCycleTime,
        tpmd.mlxProductionVersion,
        tpmd.mlxPriority,
        erb.ERPRouteName AS mlxERPRoute
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

    WHERE
        tpm.hvr_is_deleted = 0
        AND tpm.ES_ToolPlanMatrixName IN ({placeholders})

    ORDER BY
        tpm.ES_ToolPlanMatrixName,
        tpmd.mlxPriority
    """

    with get_sql_connection() as conn:
        existing_df = pd.read_sql(
            query,
            conn,
            params=materials
        )
    existing_df["RowType"] = "Existing"
    return existing_df


def add_material_resource_key(
    df,
    material_column,
    resource_column,
    key_column="_key"
):
    result_df = df.copy()

    material = result_df[material_column].apply(clean_string)
    resource = result_df[resource_column].apply(clean_string)

    result_df[key_column] = material + "_" + resource

    return result_df


def get_missing_input_rows(
    input_df,
    existing_df,
    input_material_column="Material",
    input_resource_column="Resource"
):
    keyed_input = add_material_resource_key(
        input_df,
        input_material_column,
        input_resource_column
    )

    keyed_existing = add_material_resource_key(
        existing_df,
        "Name",
        "Resource"
    )

    existing_keys = set(keyed_existing["_key"])

    return (
        keyed_input[~keyed_input["_key"].isin(existing_keys)]
        .drop(columns="_key")
        .drop_duplicates(
            subset=[input_material_column, input_resource_column]
        )
        .copy()
    )