import os
from pathlib import Path
import pandas as pd
import pyodbc
from dotenv import load_dotenv

# TO DO: SOLVE WHEN TOOL CAVITY = NULL INTEGER
# ============================================================
# CONFIG
# ============================================================
INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\add_routing_dung.xlsx")
OUTPUT_FILE = Path("output/output_tpm_chau_edit.xlsx")
EFFICIENCY_FILE = Path(r"\\MLXVHAVWPAPP2\MXV_Shared\PUBLIC\OperationGroup(OPG)\DATA_OE\huyen_data\Eff_Util_workcenter.xlsx")

OUTPUT_COLUMNS = [
    "Name",
    "Description",
    "Notes",
    "Resource",
    "ToolPlan",
    "Spec",
    "mlxIdealCycleTime",
    "mlxProductionVersion",
    "mlxPriority",
    "mlxERPRoute",
    "RowType"
]

REQUIRED_COLUMNS = [
    "Material",
    "Resource",
    "Tool",
    "group counter",
    "Capacity",
    "Efficiency",
    "Tool Cavity"
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

def validate_input_columns(df):
    missing_columns = list(set(REQUIRED_COLUMNS) - set(df.columns))
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}")
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

# ============================================================
# LOOKUPS
# ============================================================

def build_spec_lookup(existing_df):

    if existing_df.empty:
        return {}

    return (
        existing_df
        .assign(Spec=existing_df["Spec"].fillna("").astype(str))
        .query("Spec != ''")
        .groupby("Name")["Spec"]
        .first()
        .to_dict()
    )

def load_efficiency_lookup():
    try:
        eff_df = pd.read_excel(EFFICIENCY_FILE, dtype=str)
    except Exception as e:
        print(f"Unable to load efficiency file: {e}")
        return {}
    eff_df["Work Center"] = (eff_df["Work Center"].apply(clean_string))
    eff_df["Efficiency"] = pd.to_numeric(
        eff_df["Efficiency"],
        errors="coerce"
    )
    return (eff_df.set_index("Work Center")["Efficiency"].to_dict())
# ============================================================
# BUILD NEW TPM ROWS
# ============================================================
def build_added_rows(input_df, existing_df):
    spec_lookup = build_spec_lookup(existing_df)
    added_df = pd.DataFrame({
        "Name": input_df["Material"].apply(clean_string),
        "Description": "",
        "Notes": "",
        "Resource": input_df["Resource"].apply(clean_string),
        "ToolPlan": input_df["Tool"].apply(clean_string),
        "mlxProductionVersion": "",
        "mlxPriority": "",
        "RowType": "To Add"
    })

    added_df["Spec"] = (
        added_df["Name"]
        .map(spec_lookup)
        .fillna("")
    )

    efficiency_lookup = load_efficiency_lookup()
    capacity = pd.to_numeric(
        input_df["Capacity"],
        errors="coerce"
    )

    input_efficiency = pd.to_numeric(
        input_df["Efficiency"],
        errors="coerce"
    )

    resource_efficiency = (
        input_df["Resource"]
        .apply(clean_string)
        .map(efficiency_lookup)
    )
    tool_cavity = pd.to_numeric(
        input_df["Tool Cavity"],
        errors="coerce"
    )
    final_efficiency = (input_efficiency.replace(0, pd.NA).fillna(resource_efficiency))
    added_df["mlxIdealCycleTime"] = (
        capacity
        * tool_cavity
        * final_efficiency
    ).round().astype(int)
    added_df["mlxERPRoute"] = (input_df["Material"].apply(clean_string) + "-"+ input_df["group counter"].apply(clean_string))

    return added_df[OUTPUT_COLUMNS]

# ============================================================
# MAIN
# ============================================================
def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("Reading input file...")
    input_df = pd.read_excel(
        INPUT_FILE,
        dtype=str
    )
    validate_input_columns(input_df)

    materials = (
        input_df["Material"]
        .apply(clean_string)
        .drop_duplicates()
        .tolist()
    )

    print(f"Found {len(materials)} materials.")

    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)

    found_materials = set(
        existing_df["Name"]
        .apply(clean_string)
        .unique())

    missing_material_df = (
        input_df[
            ~input_df["Material"]
            .apply(clean_string)
            .isin(found_materials)
        ]
        .drop_duplicates(subset=["Material"])
        .copy())

    print(f"Found {len(existing_df)} existing rows.")

    print("Building new TPM rows...")

    added_df = build_added_rows(
        input_df,
        existing_df
    )

    # HANDLE DUPLICATE/UPDATE EXISTING ROWS
    existing_df["_key"] = (
    existing_df["Name"].astype(str)
    + "|"
    + existing_df["Resource"].astype(str)
    + "|"
    + existing_df["ToolPlan"].astype(str)
    )

    added_df["_key"] = (
        added_df["Name"].astype(str)
        + "|"
        + added_df["Resource"].astype(str)
        + "|"
        + added_df["ToolPlan"].astype(str)
    )
    existing_df = existing_df[
        ~existing_df["_key"].isin(
            added_df["_key"]
        )
    ]

    final_df = pd.concat(
        [existing_df, added_df],
        ignore_index=True
    )

    row_type_order = {
        "Existing": 1,
        "To Add": 2
    }

    final_df["_sort"] = final_df["RowType"].map(row_type_order)

    final_df = final_df.sort_values(
        by=["Name", "_sort", "mlxPriority"]
    )
    final_df.drop(
    columns="_key",
    inplace=True,
    errors="ignore"
    )

    final_df.drop(
        columns="_sort",
        inplace=True
    )

    conflict_df = (
        existing_df
        .groupby("Name")["Spec"]
        .nunique()
        .reset_index()
    )

    conflict_df = conflict_df[
        conflict_df["Spec"] > 1
    ]

    with pd.ExcelWriter(
        OUTPUT_FILE,
        engine="openpyxl"
    ) as writer:

        final_df.to_excel(
            writer,
            sheet_name="Tool Plan Matrix Output",
            index=False
        )

        conflict_df.to_excel(
            writer,
            sheet_name="Spec Conflict Check",
            index=False
        )

        missing_material_df.to_excel(
            writer,
            sheet_name="Material Not Found",
            index=False
        )

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()