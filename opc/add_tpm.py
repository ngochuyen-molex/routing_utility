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
    "Material", "Resource", "Tool", "group counter", "Capacity", "Efficiency",
    "Tool Cavity", "Priority", "Sorting/ Lubricant", "Sorting/ Lubricant Capacity"
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
# BUILD NORMAL TPM REQUESTS
# ============================================================

def build_normal_requests(input_df, existing_df):
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
    priority = pd.to_numeric(input_df["Priority"], errors="coerce")

    no_tool_efficiency = input_efficiency.mask(input_efficiency.eq(0)).fillna(resource_efficiency).fillna(1)
    with_tool_efficiency = input_efficiency.fillna(1)
    final_efficiency = no_tool_efficiency.where(tool == "", with_tool_efficiency)

    request_df = pd.DataFrame({
        "Name": material,
        "Description": "",
        "Notes": "",
        "ToolPlan": tool,
        "Resource": resource,
        "Spec": material.map(spec_lookup).fillna(""),
        "mlxIdealCycleTime": (capacity * tool_cavity * final_efficiency).round().astype("Int64"),
        "mlxProductionVersion": "",
        "mlxPriority": priority.apply(lambda x: "" if pd.isna(x) else int(x)),
        "mlxERPRoute": material + "-" + group_counter,
        "RowType": "Add New TPM",
        "Capacity": capacity,
        "Tool Cavity": pd.to_numeric(input_df["Tool Cavity"], errors="coerce"),
        "FinalToolCavity": tool_cavity,
        "Efficiency": input_efficiency,
        "ResourceEfficiency": resource_efficiency,
        "FinalEfficiency": final_efficiency
    })

    blank_key_df = request_df[(request_df["Name"] == "") | (request_df["Resource"] == "")].copy()
    missing_capacity_df = request_df[(request_df["Name"] != "") & (request_df["Resource"] != "") & request_df["Capacity"].isna()].copy()
    request_df = request_df[(request_df["Name"] != "") & (request_df["Resource"] != "") & request_df["Capacity"].notna()].copy()

    request_df["_ToolPlanClean"] = request_df["ToolPlan"].apply(clean_tool)
    request_df["_key_general"] = request_df["Name"].apply(clean_string) + "|" + request_df["Resource"].apply(clean_string)
    request_df["_key_tool"] = request_df["_key_general"] + "|" + request_df["_ToolPlanClean"]
    request_df["_final_key"] = request_df["_key_tool"].where(request_df["_ToolPlanClean"] != "", request_df["_key_general"])

    conflicting_values = request_df.groupby("_final_key")["mlxIdealCycleTime"].nunique().reset_index(name="IdealCycleTimeCount")
    conflicting_values = conflicting_values[conflicting_values["IdealCycleTimeCount"] > 1]

    conflict_df = request_df[request_df["_final_key"].isin(conflicting_values["_final_key"])].copy()
    request_df = request_df[~request_df["_final_key"].isin(conflicting_values["_final_key"])].drop_duplicates(subset=["_final_key"], keep="last").copy()

    return request_df, blank_key_df, missing_capacity_df, conflict_df


# ============================================================
# UPDATE EXISTING NORMAL TPM OR ADD NEW TPM
# ============================================================

def process_normal_rows(existing_df, request_df):
    updated_existing_df = existing_df.copy()
    updated_existing_df["_key_general"] = updated_existing_df["Name"].apply(clean_string) + "|" + updated_existing_df["Resource"].apply(clean_string)
    updated_existing_df["_key_tool"] = updated_existing_df["_key_general"] + "|" + updated_existing_df["ToolPlan"].apply(clean_tool)

    general_requests = request_df[request_df["_ToolPlanClean"] == ""].copy()
    tool_requests = request_df[request_df["_ToolPlanClean"] != ""].copy()

    general_lookup = general_requests.set_index("_key_general")["mlxIdealCycleTime"].to_dict()
    tool_lookup = tool_requests.set_index("_key_tool")["mlxIdealCycleTime"].to_dict()

    updated_existing_df["_NewIdealCycleTime"] = updated_existing_df["_key_tool"].map(tool_lookup).fillna(updated_existing_df["_key_general"].map(general_lookup))
    existing_update_mask = updated_existing_df["_NewIdealCycleTime"].notna()
    normal_update_audit_df = updated_existing_df.loc[existing_update_mask].copy()

    if not normal_update_audit_df.empty:
        normal_update_audit_df["OldIdealCycleTime"] = normal_update_audit_df["mlxIdealCycleTime"]
        normal_update_audit_df["NewIdealCycleTime"] = normal_update_audit_df["_NewIdealCycleTime"].round().astype("Int64")
        old_cycle_time = pd.to_numeric(normal_update_audit_df["OldIdealCycleTime"], errors="coerce")
        new_cycle_time = pd.to_numeric(normal_update_audit_df["NewIdealCycleTime"], errors="coerce")
        normal_update_audit_df["IdealCycleTimeChanged"] = old_cycle_time.ne(new_cycle_time)
        normal_update_audit_df["RowType"] = "Updated TPM Cycle Time"

        updated_existing_df.loc[existing_update_mask, "mlxIdealCycleTime"] = updated_existing_df.loc[existing_update_mask, "_NewIdealCycleTime"].round().astype("Int64").to_numpy()
        updated_existing_df.loc[existing_update_mask, "RowType"] = "Updated TPM Cycle Time"

    existing_general_keys = set(updated_existing_df["_key_general"])
    existing_tool_keys = set(updated_existing_df["_key_tool"])

    matched_request_mask = request_df.apply(
        lambda row: row["_key_tool"] in existing_tool_keys if row["_ToolPlanClean"] != "" else row["_key_general"] in existing_general_keys,
        axis=1
    )

    new_normal_df = request_df[~matched_request_mask].copy()
    not_added_normal_df = request_df[matched_request_mask].copy()
    new_normal_df["RowType"] = "Add New TPM"

    new_normal_df = new_normal_df[OUTPUT_COLUMNS] if not new_normal_df.empty else pd.DataFrame(columns=OUTPUT_COLUMNS)

    updated_existing_df.drop(columns=["_key_general", "_key_tool", "_NewIdealCycleTime"], inplace=True, errors="ignore")
    normal_update_audit_df.drop(columns=["_key_general", "_key_tool", "_NewIdealCycleTime"], inplace=True, errors="ignore")
    not_added_normal_df.drop(columns=["_ToolPlanClean", "_key_general", "_key_tool", "_final_key"], inplace=True, errors="ignore")

    return updated_existing_df, new_normal_df, normal_update_audit_df, not_added_normal_df


# ============================================================
# BUILD SORTING / LUBRICANT REQUESTS
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

    conflicting_values = sorting_df.groupby("_sorting_key")["NewIdealCycleTime"].nunique().reset_index(name="IdealCycleTimeCount")
    conflicting_values = conflicting_values[conflicting_values["IdealCycleTimeCount"] > 1]

    sorting_conflict_df = sorting_df[sorting_df["_sorting_key"].isin(conflicting_values["_sorting_key"])].copy()
    sorting_df = sorting_df[~sorting_df["_sorting_key"].isin(conflicting_values["_sorting_key"])].drop_duplicates(subset=["_sorting_key"], keep="last").copy()

    return sorting_df, sorting_conflict_df


# ============================================================
# UPDATE EXISTING SORTING OR ADD NEW SORTING
# ============================================================

def process_sorting_rows(existing_df, sorting_df):
    updated_existing_df = existing_df.copy()
    updated_existing_df["_sorting_key"] = updated_existing_df["Name"].apply(clean_string) + "|" + updated_existing_df["Resource"].apply(clean_string)

    existing_sorting_keys = set(updated_existing_df["_sorting_key"])
    sorting_lookup = sorting_df.set_index("_sorting_key")["NewIdealCycleTime"].to_dict()
    existing_update_mask = updated_existing_df["_sorting_key"].isin(sorting_lookup)
    sorting_update_audit_df = updated_existing_df.loc[existing_update_mask].copy()

    if not sorting_update_audit_df.empty:
        sorting_update_audit_df["OldIdealCycleTime"] = sorting_update_audit_df["mlxIdealCycleTime"]
        sorting_update_audit_df["NewIdealCycleTime"] = sorting_update_audit_df["_sorting_key"].map(sorting_lookup).round().astype("Int64")
        old_cycle_time = pd.to_numeric(sorting_update_audit_df["OldIdealCycleTime"], errors="coerce")
        new_cycle_time = pd.to_numeric(sorting_update_audit_df["NewIdealCycleTime"], errors="coerce")
        sorting_update_audit_df["IdealCycleTimeChanged"] = old_cycle_time.ne(new_cycle_time)
        sorting_update_audit_df["RowType"] = "Updated Sorting Cycle Time"

        updated_existing_df.loc[existing_update_mask, "mlxIdealCycleTime"] = updated_existing_df.loc[existing_update_mask, "_sorting_key"].map(sorting_lookup).round().astype("Int64").to_numpy()
        updated_existing_df.loc[existing_update_mask, "RowType"] = "Updated Sorting Cycle Time"

    new_sorting_requests = sorting_df[~sorting_df["_sorting_key"].isin(existing_sorting_keys)].copy()

    if not new_sorting_requests.empty:
        spec_lookup = build_spec_lookup(existing_df)

        new_sorting_df = pd.DataFrame({
            "Name": new_sorting_requests["Name"],
            "Description": "",
            "Notes": "",
            "ToolPlan": "",
            "Resource": new_sorting_requests["Resource"],
            "Spec": new_sorting_requests["Name"].map(spec_lookup).fillna(""),
            "mlxIdealCycleTime": new_sorting_requests["NewIdealCycleTime"].astype("Int64"),
            "mlxProductionVersion": "",
            "mlxPriority": "",
            "mlxERPRoute": "",
            "RowType": "Add New Sorting"
        })

        new_sorting_df = new_sorting_df[OUTPUT_COLUMNS]
    else:
        new_sorting_df = pd.DataFrame(columns=OUTPUT_COLUMNS)

    updated_existing_df.drop(columns="_sorting_key", inplace=True, errors="ignore")
    sorting_update_audit_df.drop(columns="_sorting_key", inplace=True, errors="ignore")

    return updated_existing_df, new_sorting_df, sorting_update_audit_df


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
    print("Building and processing TPM requests...")

    spec_conflict_df = existing_df.groupby("Name")["Spec"].nunique().reset_index()
    spec_conflict_df = spec_conflict_df[spec_conflict_df["Spec"] > 1]

    normal_request_df, blank_key_df, missing_capacity_df, normal_conflict_df = build_normal_requests(input_df, existing_df)
    sorting_request_df, sorting_conflict_df = build_sorting_requests(input_df)

    existing_df, new_normal_df, normal_update_audit_df, matched_normal_request_df = process_normal_rows(existing_df, normal_request_df)
    existing_df, new_sorting_df, sorting_update_audit_df = process_sorting_rows(existing_df, sorting_request_df)

    final_df = pd.concat([existing_df, new_normal_df, new_sorting_df], ignore_index=True)

    row_type_order = {
        "Existing": 1,
        "Updated TPM Cycle Time": 2,
        "Updated Sorting Cycle Time": 3,
        "Add New TPM": 4,
        "Add New Sorting": 5
    }

    final_df["_sort"] = final_df["RowType"].map(row_type_order).fillna(99)
    final_df["_priority_sort"] = pd.to_numeric(final_df["mlxPriority"], errors="coerce")
    final_df = final_df.sort_values(by=["Name", "_sort", "_priority_sort"], na_position="last")
    final_df.drop(columns=["_sort", "_priority_sort"], inplace=True, errors="ignore")

    calculation_audit_df = normal_request_df[
        [
            "Name", "Resource", "ToolPlan", "Capacity", "Tool Cavity", "FinalToolCavity",
            "Efficiency", "ResourceEfficiency", "FinalEfficiency", "mlxIdealCycleTime"
        ]
    ].rename(columns={"mlxIdealCycleTime": "NewIdealCycleTime"}).copy()

    print(f"Normal TPM rows added: {len(new_normal_df)}.")
    print(f"Existing normal TPM rows updated: {len(normal_update_audit_df)}.")
    print(f"Sorting/Lubricant rows added: {len(new_sorting_df)}.")
    print(f"Existing Sorting/Lubricant rows updated: {len(sorting_update_audit_df)}.")
    print(f"Conflicting normal TPM requests skipped: {len(normal_conflict_df)}.")
    print(f"Conflicting Sorting/Lubricant requests skipped: {len(sorting_conflict_df)}.")
    print(f"Missing Capacity rows skipped: {len(missing_capacity_df)}.")
    print(f"Blank Material/Resource rows skipped: {len(blank_key_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Tool Plan Matrix Output", index=False)
        normal_update_audit_df.to_excel(writer, sheet_name="Normal Update Audit", index=False)
        sorting_update_audit_df.to_excel(writer, sheet_name="Sorting Update Audit", index=False)
        calculation_audit_df.to_excel(writer, sheet_name="Calculation Audit", index=False)
        normal_conflict_df.to_excel(writer, sheet_name="Normal Conflict Check", index=False)
        sorting_conflict_df.to_excel(writer, sheet_name="Sorting Conflict Check", index=False)
        missing_capacity_df.to_excel(writer, sheet_name="Missing Capacity", index=False)
        blank_key_df.to_excel(writer, sheet_name="Blank Material Resource", index=False)
        spec_conflict_df.to_excel(writer, sheet_name="Spec Conflict Check", index=False)
        missing_material_df.to_excel(writer, sheet_name="Material Not Found", index=False)

    print(f"Final TPM rows: {len(final_df)}.")
    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()