"""OpCenter (SQL Server) Tool Plan Matrix queries."""
import pandas as pd

from routing.core.db import mssql_conn

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


def fetch_existing_tool_plan_matrix(materials, batch_size=500):
    if not materials:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = []

    with mssql_conn() as conn:
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
            tp.ToolPlanName AS ToolPlan,
            sb.SpecName AS Spec,
            r.ResourceName AS Resource,
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


SQL_TPM_NAMES = """
    SELECT DISTINCT
        C.ES_ToolPlanMatrixName
    FROM EXCRSCH.ES_ToolPlanMatrix C WITH (NOLOCK)
    JOIN EXCRSch.ES_ToolPlanMatrixDetails cd WITH (NOLOCK)
        ON C.ES_ToolPlanMatrixId = cd.ES_ToolPlanMatrixId
    WHERE C.ES_ToolPlanMatrixName IN ({placeholders})
"""


def existing_tpm_names(materials, batch_size=500):
    """Set of material numbers that have a Tool Plan Matrix with details."""
    found = set()
    with mssql_conn() as conn:
        for start in range(0, len(materials), batch_size):
            batch = materials[start:start + batch_size]
            query = SQL_TPM_NAMES.format(placeholders=",".join(["?"] * len(batch)))
            result_df = pd.read_sql(query, conn, params=batch)
            found |= set(result_df["ES_ToolPlanMatrixName"].astype(str).str.strip())
    return found
