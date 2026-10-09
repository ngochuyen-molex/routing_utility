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
def fetch_existing_tool_plan_matrix(materials, batch_size=500):
    if not materials:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = []

    with get_sql_connection() as conn:
        for start in range(0, len(materials), batch_size):
            batch = materials[start:start + batch_size]

            print(f"Loading TPM batch {start+1}-{start+len(batch)} of {len(materials)} materials...")

            placeholders = ",".join(["?"] * len(batch))

            query = f"""
        WITH RankedToolPlanMatrix AS
        (
        SELECT
            tpm.ES_ToolPlanMatrixId,
            tpm.ES_ToolPlanMatrixName AS Name,
            tpm.Description,
            tpm.Notes,
            r.ResourceName AS Resource,
            tp.ToolPlanName AS ToolPlan,
            sb.SpecName AS Spec,
            tpmd.mlxIdealCycleTime,
            tpmd.mlxProductionVersion,
            tpmd.mlxPriority,
            erb.ERPRouteName AS mlxERPRoute,
            tpmd.hvr_change_time,

            ROW_NUMBER() OVER
            (
                PARTITION BY
                    tpm.ES_ToolPlanMatrixId,
                    tpmd.SpecBaseId,
                    tpmd.ResourceId,
                    tpmd.ToolPlanId,
                    tpmd.mlxERPRouteBaseId,
                    tpmd.mlxPriority
                ORDER BY
                    tpmd.hvr_change_time DESC,
                    tpmd.ES_ToolPlanMatrixDetailsId DESC
            ) AS row_num

        FROM EXCRSch.ES_ToolPlanMatrix AS tpm

        LEFT JOIN EXCRSch.ES_ToolPlanMatrixDetails AS tpmd
            ON tpmd.ES_ToolPlanMatrixId = tpm.ES_ToolPlanMatrixId
            AND tpmd.hvr_is_deleted = 0

        LEFT JOIN EXCRSch.SpecBase AS sb
            ON sb.SpecBaseId = tpmd.SpecBaseId
            AND sb.hvr_is_deleted = 0

        LEFT JOIN EXCRSch.ResourceDef AS r
            ON r.ResourceId = tpmd.ResourceId
            AND r.hvr_is_deleted = 0

        LEFT JOIN EXCRSch.A_ToolPlan AS tp
            ON tp.ToolPlanId = tpmd.ToolPlanId
            AND tp.hvr_is_deleted = 0

        LEFT JOIN EXCRSch.ERPRouteBase AS erb
            ON erb.ERPRouteBaseId = tpmd.mlxERPRouteBaseId
            AND erb.hvr_is_deleted = 0

        WHERE
            tpm.hvr_is_deleted = 0
            AND tpm.ES_ToolPlanMatrixName IN ({placeholders})
    )
        SELECT
        Name,
        Description,
        Notes,
        Resource,
        ToolPlan,
        Spec,
        mlxIdealCycleTime,
        mlxProductionVersion,
        mlxPriority,
        mlxERPRoute
    FROM RankedToolPlanMatrix
    WHERE row_num = 1
    ORDER BY
        Name,
        mlxPriority;
            """

            batch_df = pd.read_sql(query, conn, params=batch)

            if not batch_df.empty:
                result.append(batch_df)

    existing_df = pd.concat(result, ignore_index=True) if result else pd.DataFrame(columns=OUTPUT_COLUMNS)
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