from pathlib import Path
import pandas as pd
from tpm_common import clean_string, validate_input_columns, fetch_existing_tool_plan_matrix, OUTPUT_COLUMNS, clean_tool


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\OneDrive - kochind.com\add_routing_chau_september.xlsx")
OUTPUT_FILE = Path("output/add_tpm.xlsx")
EFFICIENCY_FILE = Path(r"\\MLXVHAVWPAPP2\MXV_Shared\PUBLIC\OperationGroup(OPG)\DATA_OE\huyen_data\Eff_Util_workcenter.xlsx")

REQUIRED_COLUMNS = [
    "Material",
    "Resource",
    "Tool",
    "group counter",
    "Capacity",
    "Efficiency",
    "Tool Cavity",
    "Priority",
    "Sorting/ Lubricant",
    "Sorting/ Lubricant Capacity"
]

# ============================================================
# LOOKUPS
# ============================================================

def build_spec_lookup(existing_df):
    if existing_df.empty:
        return {}

    return existing_df.assign(Spec=existing_df["Spec"].fillna("").astype(str)).query("Spec != ''").groupby("Name")["Spec"].first().to_dict()


def load_efficiency_lookup():
    try:
        eff_df = pd.read_excel(EFFICIENCY_FILE, dtype=str)
    except Exception as e:
        print(f"Unable to load efficiency file: {e}")
        return {}

    required_columns = ["Work Center", "Efficiency"]
    missing_columns = list(set(required_columns) - set(eff_df.columns))

    if missing_columns:
        print(f"Efficiency file is missing columns: {missing_columns}")
        return {}

    eff_df["Work Center"] = eff_df["Work Center"].apply(clean_string)
    eff_df["Efficiency"] = pd.to_numeric(eff_df["Efficiency"], errors="coerce")
    eff_df = eff_df[(eff_df["Work Center"] != "") & eff_df["Efficiency"].notna()].copy()

    duplicate_work_centers = eff_df[eff_df.duplicated(subset=["Work Center"], keep=False)].copy()

    if not duplicate_work_centers.empty:
        print(f"Warning: {len(duplicate_work_centers)} duplicate work-center rows found in the efficiency file.")

    return eff_df.drop_duplicates(subset=["Work Center"], keep="last").set_index("Work Center")["Efficiency"].to_dict()


# ============================================================
# BUILD NORMAL TPM ROWS
# ============================================================

def build_normal_rows(input_df, existing_df):
    spec_lookup = build_spec_lookup(existing_df)
    efficiency_lookup = load_efficiency_lookup()

    material = input_df["Material"].apply(clean_string)
    resource = input_df["Resource"].apply(clean_string)
    tool = input_df["Tool"].apply(clean_tool)
    group_counter = input_df["group counter"].apply(clean_string)

    capacity = pd.to_numeric(input_df["Capacity"], errors="coerce")
    tool_cavity = pd.to_numeric(input_df["Tool Cavity"], errors="coerce").fillna(1)
    input_efficiency = pd.to_numeric(input_df["Efficiency"], errors="coerce")
    resource_efficiency = resource.map(efficiency_lookup)

    # Tool blank: Excel Efficiency -> Resource Efficiency -> 1.
    # Excel Efficiency = 0 is treated as unavailable.
    no_tool_efficiency = input_efficiency.mask(input_efficiency.eq(0)).fillna(resource_efficiency).fillna(1)

    # Tool populated: Excel Efficiency -> 1.
    # Resource Efficiency is not used. An actual zero remains zero.
    with_tool_efficiency = input_efficiency.fillna(1)
    final_efficiency = no_tool_efficiency.where(tool == "", with_tool_efficiency)

    existing_general_keys = set(existing_df["Name"].apply(clean_string) + "|" + existing_df["Resource"].apply(clean_string))
    existing_tool_keys = set(existing_df["Name"].apply(clean_string) + "|" + existing_df["Resource"].apply(clean_string) + "|" + existing_df["ToolPlan"].apply(clean_tool))

    normal_df = pd.DataFrame({
        "Name": material,
        "Description": "",
        "Notes": "",
        "ToolPlan": tool,
        "Resource": resource,
        "mlxProductionVersion": ""
    })

    priority = pd.to_numeric(input_df["Priority"], errors="coerce")

    normal_df["mlxPriority"] = priority.apply(lambda x: "" if pd.isna(x) else int(x))
    normal_df["Spec"] = normal_df["Name"].map(spec_lookup).fillna("")
    normal_df["mlxIdealCycleTime"] = (capacity * tool_cavity * final_efficiency).round().astype("Int64")
    normal_df["mlxERPRoute"] = material + "-" + group_counter

    normal_df["_ToolPlanClean"] = normal_df["ToolPlan"].apply(clean_tool)
    normal_df["_key_general"] = normal_df["Name"].apply(clean_string) + "|" + normal_df["Resource"].apply(clean_string)
    normal_df["_key_tool"] = normal_df["_key_general"] + "|" + normal_df["_ToolPlanClean"]

    normal_df["RowType"] = normal_df.apply(
        lambda row: "Replace Existing TPM"
        if (row["_key_tool"] in existing_tool_keys if row["_ToolPlanClean"] != "" else row["_key_general"] in existing_general_keys)
        else "Add New TPM",
        axis=1
    )

    normal_df = normal_df.drop(columns=["_ToolPlanClean", "_key_general", "_key_tool"])

    return normal_df[OUTPUT_COLUMNS]


# ============================================================
# PREPARE SORTING / LUBRICANT REQUESTS
# ============================================================

def build_sorting_requests(input_df):
    material = input_df["Material"].apply(clean_string)
    sorting_resource = input_df["Sorting/ Lubricant"].apply(clean_tool)
    sorting_capacity = pd.to_numeric(input_df["Sorting/ Lubricant Capacity"], errors="coerce")
    sorting_mask = (material != "") & (sorting_resource != "") & sorting_capacity.notna()

    sorting_df = pd.DataFrame({
        "Name": material[sorting_mask],
        "Resource": sorting_resource[sorting_mask],
        "NewIdealCycleTime": sorting_capacity[sorting_mask].round().astype("Int64")
    })

    sorting_df["_sorting_key"] = sorting_df["Name"].apply(clean_string) + "|" + sorting_df["Resource"].apply(clean_string)

    conflicting_sorting = sorting_df.groupby("_sorting_key")["NewIdealCycleTime"].nunique().reset_index(name="CycleTimeCount")
    conflicting_sorting = conflicting_sorting[conflicting_sorting["CycleTimeCount"] > 1]

    sorting_conflict_df = sorting_df[sorting_df["_sorting_key"].isin(conflicting_sorting["_sorting_key"])].copy()
    sorting_df = sorting_df[~sorting_df["_sorting_key"].isin(conflicting_sorting["_sorting_key"])].drop_duplicates(subset=["_sorting_key"], keep="last").copy()

    return sorting_df, sorting_conflict_df


# ============================================================
# UPDATE EXISTING SORTING OR ADD NEW SORTING
# ============================================================

def process_sorting_rows(existing_df, sorting_df):
    updated_existing_df = existing_df.copy()
    updated_existing_df["_sorting_key"] = updated_existing_df["Name"].apply(clean_string) + "|" + updated_existing_df["Resource"].apply(clean_string)

    existing_sorting_keys = set(updated_existing_df["_sorting_key"])
    sorting_lookup = sorting_df.set_index("_sorting_key")["NewIdealCycleTime"].to_dict()

    existing_sorting_mask = updated_existing_df["_sorting_key"].isin(sorting_lookup)
    sorting_update_audit_df = updated_existing_df.loc[existing_sorting_mask].copy()

    if not sorting_update_audit_df.empty:
        sorting_update_audit_df["OldIdealCycleTime"] = sorting_update_audit_df["mlxIdealCycleTime"]
        sorting_update_audit_df["NewIdealCycleTime"] = sorting_update_audit_df["_sorting_key"].map(sorting_lookup)
        sorting_update_audit_df["IdealCycleTimeChanged"] = pd.to_numeric(sorting_update_audit_df["OldIdealCycleTime"], errors="coerce").ne(pd.to_numeric(sorting_update_audit_df["NewIdealCycleTime"], errors="coerce"))
        sorting_update_audit_df["RowType"] = "Updated Sorting Cycle Time"

        updated_existing_df.loc[existing_sorting_mask, "mlxIdealCycleTime"] = updated_existing_df.loc[existing_sorting_mask, "_sorting_key"].map(sorting_lookup).to_numpy()
        updated_existing_df.loc[existing_sorting_mask, "RowType"] = "Updated Sorting Cycle Time"

    new_sorting_df = sorting_df[~sorting_df["_sorting_key"].isin(existing_sorting_keys)].copy()

    if not new_sorting_df.empty:
        spec_lookup = build_spec_lookup(existing_df)

        new_sorting_df = pd.DataFrame({
            "Name": new_sorting_df["Name"],
            "Description": "",
            "Notes": "",
            "ToolPlan": "",
            "Resource": new_sorting_df["Resource"],
            "Spec": new_sorting_df["Name"].map(spec_lookup).fillna(""),
            "mlxIdealCycleTime": new_sorting_df["NewIdealCycleTime"].astype("Int64"),
            "mlxProductionVersion": "",
            "mlxPriority": "",
            "mlxERPRoute": "",
            "RowType": "Add New Sorting"
        })

        new_sorting_df = new_sorting_df[OUTPUT_COLUMNS]
    else:
        new_sorting_df = pd.DataFrame(columns=OUTPUT_COLUMNS)

    updated_existing_df = updated_existing_df.drop(columns="_sorting_key", errors="ignore")
    sorting_update_audit_df = sorting_update_audit_df.drop(columns="_sorting_key", errors="ignore")

    return updated_existing_df, new_sorting_df, sorting_update_audit_df


# ============================================================
# REMOVE / REPLACE NORMAL TPM DUPLICATES
# ============================================================

def replace_normal_tpm_rows(existing_df, normal_df):
    existing_df = existing_df.copy()
    normal_df = normal_df.copy()

    existing_df["_key_general"] = existing_df["Name"].apply(clean_string) + "|" + existing_df["Resource"].apply(clean_string)
    existing_df["_key_tool"] = existing_df["_key_general"] + "|" + existing_df["ToolPlan"].apply(clean_tool)

    normal_df["_ToolPlanClean"] = normal_df["ToolPlan"].apply(clean_tool)
    normal_df["_key_general"] = normal_df["Name"].apply(clean_string) + "|" + normal_df["Resource"].apply(clean_string)
    normal_df["_key_tool"] = normal_df["_key_general"] + "|" + normal_df["_ToolPlanClean"]

    general_normal_keys = set(normal_df.loc[normal_df["_ToolPlanClean"] == "", "_key_general"])
    tool_normal_keys = set(normal_df.loc[normal_df["_ToolPlanClean"] != "", "_key_tool"])

    replace_existing_mask = existing_df["_key_general"].isin(general_normal_keys) | existing_df["_key_tool"].isin(tool_normal_keys)
    existing_df = existing_df[~replace_existing_mask].copy()

    normal_df["_final_key"] = normal_df["_key_tool"].where(normal_df["_ToolPlanClean"] != "", normal_df["_key_general"])
    duplicate_normal_df = normal_df[normal_df.duplicated(subset=["_final_key"], keep=False)].copy()
    normal_df = normal_df.drop_duplicates(subset=["_final_key"], keep="last").copy()

    existing_df = existing_df.drop(columns=["_key_general", "_key_tool"], errors="ignore")
    normal_df = normal_df.drop(columns=["_ToolPlanClean", "_key_general", "_key_tool", "_final_key"], errors="ignore")
    duplicate_normal_df = duplicate_normal_df.drop(columns=["_ToolPlanClean", "_key_general", "_key_tool", "_final_key"], errors="ignore")

    return existing_df, normal_df, duplicate_normal_df


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading input file...")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    materials = input_df["Material"].apply(clean_string).drop_duplicates().tolist()

    print(f"Found {len(materials)} materials.")
    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)
    found_materials = set(existing_df["Name"].apply(clean_string).unique())

    missing_material_df = input_df[~input_df["Material"].apply(clean_string).isin(found_materials)].drop_duplicates(subset=["Material"]).copy()

    print(f"Found {len(existing_df)} existing rows.")
    print("Building TPM rows...")

    conflict_df = existing_df.groupby("Name")["Spec"].nunique().reset_index()
    conflict_df = conflict_df[conflict_df["Spec"] > 1]

    normal_df = build_normal_rows(input_df, existing_df)
    sorting_df, sorting_conflict_df = build_sorting_requests(input_df)

    # Sorting behavior:
    # Existing Sorting resource -> update only mlxIdealCycleTime.
    # Missing Sorting resource -> add a new Sorting TPM row.
    existing_df, new_sorting_df, sorting_update_audit_df = process_sorting_rows(existing_df, sorting_df)

    # Normal TPM behavior remains replace/add.
    existing_df, normal_df, duplicate_normal_df = replace_normal_tpm_rows(existing_df, normal_df)

    final_df = pd.concat([existing_df, normal_df, new_sorting_df], ignore_index=True)

    row_type_order = {
        "Existing": 1,
        "Updated Sorting Cycle Time": 2,
        "Replace Existing TPM": 3,
        "Add New TPM": 4,
        "Add New Sorting": 5
    }

    final_df["_sort"] = final_df["RowType"].map(row_type_order).fillna(99)
    final_df["_priority_sort"] = pd.to_numeric(final_df["mlxPriority"], errors="coerce")
    final_df = final_df.sort_values(by=["Name", "_sort", "_priority_sort"], na_position="last")
    final_df.drop(columns=["_sort", "_priority_sort"], inplace=True, errors="ignore")

    add_normal_count = (normal_df["RowType"] == "Add New TPM").sum()
    replace_normal_count = (normal_df["RowType"] == "Replace Existing TPM").sum()
    add_sorting_count = (new_sorting_df["RowType"] == "Add New Sorting").sum() if not new_sorting_df.empty else 0
    update_sorting_count = len(sorting_update_audit_df)

    print(f"Normal TPM rows to add: {add_normal_count}.")
    print(f"Normal TPM rows replacing existing rows: {replace_normal_count}.")
    print(f"New Sorting/Lubricant rows to add: {add_sorting_count}.")
    print(f"Existing Sorting/Lubricant rows updated: {update_sorting_count}.")
    print(f"Conflicting Sorting/Lubricant rows skipped: {len(sorting_conflict_df)}.")
    print(f"Duplicate normal TPM rows found: {len(duplicate_normal_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Tool Plan Matrix Output", index=False)
        sorting_update_audit_df.to_excel(writer, sheet_name="Sorting Update Audit", index=False)
        sorting_conflict_df.to_excel(writer, sheet_name="Sorting Conflict Check", index=False)
        duplicate_normal_df.to_excel(writer, sheet_name="Generated Duplicate Check", index=False)
        conflict_df.to_excel(writer, sheet_name="Spec Conflict Check", index=False)
        missing_material_df.to_excel(writer, sheet_name="Material Not Found", index=False)

    print(f"Final TPM rows: {len(final_df)}.")
    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()