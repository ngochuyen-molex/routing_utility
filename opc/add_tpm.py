from pathlib import Path
import pandas as pd
import numpy as np
from tpm_common import clean_string, validate_input_columns, fetch_existing_tool_plan_matrix, OUTPUT_COLUMNS, clean_tool

# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\add_routing_mold.xlsx")
OUTPUT_FILE = Path("output/add_mld.xlsx")
EFFICIENCY_FILE = Path(r"\\MLXVHAVWPAPP2\MXV_Shared\PUBLIC\OperationGroup(OPG)\DATA_OE\huyen_data\Eff_Util_workcenter.xlsx")
EXCLUDED_RESOURCES = {"C_RFE", "C_RE", "C_FE"}
REQUIRED_COLUMNS = [
    "Material", "Resource", "Tool", "group counter", "Efficiency", "Utilization",
    "Tool Cavity", "Dept", "Priority", "Sorting/ Lubricant", "Sorting/ Lubricant Capacity"]

# ============================================================
# LOOKUPS
# ============================================================
def optional_numeric_column(input_df, column):
    if column not in input_df.columns:
        return pd.Series(float("nan"), index=input_df.index)
    return pd.to_numeric(input_df[column], errors="coerce")


def build_spec_lookup(existing_df):
    if existing_df.empty:
        return {}
    # For normal resources: Spec must not contain "sort", "sorting" or "lubrication".
    spec_df = existing_df.assign(Spec=existing_df["Spec"].fillna("").astype(str)).query("Spec != ''")
    valid = ~spec_df["Spec"].str.lower().str.contains("sort|lubrication")
    return spec_df[valid].groupby("Name")["Spec"].first().to_dict()


def build_ymhi_spec_lookup(existing_df):
    # For YMHI resources: Spec must not contain "production" and must contain "sort" or "lubrication".
    if existing_df.empty:
        return {}
    spec_df = existing_df.assign(Spec=existing_df["Spec"].fillna("").astype(str)).query("Spec != ''")
    spec_lower = spec_df["Spec"].str.lower()
    valid = ~spec_lower.str.contains("production", regex=False) & spec_lower.str.contains("sort|lubrication")
    return spec_df[valid].groupby("Name")["Spec"].first().to_dict()


def resolve_spec(names, resources, existing_df):
    is_ymhi = resources.astype(str).str.upper().str.contains("YMHI", regex=False)
    ymhi_spec = names.map(build_ymhi_spec_lookup(existing_df))
    normal_spec = names.map(build_spec_lookup(existing_df))
    return ymhi_spec.where(is_ymhi, normal_spec).fillna("")

def load_efficiency_lookup():
    try:
        eff_df = pd.read_excel(EFFICIENCY_FILE, dtype=str)
    except Exception as e:
        print(f"Unable to load efficiency file: {e}")
        return {}, {}

    required_columns = ["Work Center", "Efficiency", "Utilization"]
    missing_columns = list(set(required_columns) - set(eff_df.columns))

    if missing_columns:
        print(f"Efficiency file is missing columns: {missing_columns}")
        return {}, {}

    eff_df["Work Center"] = eff_df["Work Center"].apply(clean_string)
    eff_df["Efficiency"] = pd.to_numeric(eff_df["Efficiency"], errors="coerce")
    eff_df["Utilization"] = pd.to_numeric(eff_df["Utilization"], errors="coerce")
    eff_df = eff_df[eff_df["Work Center"] != ""].drop_duplicates(subset=["Work Center"], keep="last").copy()

    efficiency_lookup = eff_df.set_index("Work Center")["Efficiency"].to_dict()
    utilization_lookup = eff_df.set_index("Work Center")["Utilization"].to_dict()

    return efficiency_lookup, utilization_lookup


# ============================================================
# BUILD NORMAL TPM REQUESTS
# ============================================================

def build_normal_requests(input_df, existing_df):
    resource = input_df["Resource"].apply(clean_string)
    excluded_mask = resource.str.upper().isin(EXCLUDED_RESOURCES)
    excluded_df = input_df.loc[excluded_mask].copy()
    input_df = input_df.loc[~excluded_mask].copy()

    efficiency_lookup, utilization_lookup = load_efficiency_lookup()

    material = input_df["Material"].apply(clean_string)
    resource = input_df["Resource"].apply(clean_string)
    tool = input_df["Tool"].apply(clean_tool)
    dept = input_df["Dept"].apply(clean_string).str.upper()
    group_counter = input_df["group counter"].apply(clean_string)

    input_ideal_cycle_time = optional_numeric_column(input_df, "Ideal cycle time")
    capacity_pcs = optional_numeric_column(input_df, "Capacity(Pcs/hr)")
    capacity_shot = optional_numeric_column(input_df, "Capacity")
    capacity = capacity_pcs.combine_first(capacity_shot)
    capacity_source = pd.Series("", index=input_df.index, dtype="object")
    capacity_source.loc[capacity_pcs.notna()] = "Capacity(Pcs/hr)"
    capacity_source.loc[capacity_pcs.isna() & capacity_shot.notna()] = "Capacity"

    input_tool_cavity = pd.to_numeric(input_df["Tool Cavity"], errors="coerce")
    tool_cavity = input_tool_cavity.fillna(1)
    capacity_multiplier = pd.Series(1, index=input_df.index, dtype="Float64")
    shot_capacity_mask = capacity_pcs.isna() & capacity_shot.notna()
    capacity_multiplier.loc[shot_capacity_mask] = tool_cavity.loc[shot_capacity_mask]

    input_efficiency = pd.to_numeric(input_df["Efficiency"], errors="coerce")
    input_utilization = pd.to_numeric(input_df["Utilization"], errors="coerce")
    resource_efficiency = resource.map(efficiency_lookup)
    resource_utilization = resource.map(utilization_lookup)
    priority = pd.to_numeric(input_df["Priority"], errors="coerce")

    # MLD: use the Excel efficiency, then the resource lookup, then 1.
    mld_efficiency = input_efficiency.mask(input_efficiency.eq(0)).fillna(resource_efficiency).fillna(1)
    mld_cycle_time = capacity * capacity_multiplier * mld_efficiency

    # AS: Capacity × Excel Utilization.
    as_utilization = input_utilization.fillna(resource_utilization).fillna(1)
    as_cycle_time = capacity * capacity_multiplier * as_utilization

    # STP/PLT:
    # Tool exists -> Efficiency and Utilization from lookup file.
    # Tool blank -> Efficiency and Utilization from Excel input.
    stp_plt_input_efficiency = input_efficiency.fillna(1)
    stp_plt_input_utilization = input_utilization.fillna(1)
    stp_plt_lookup_efficiency = resource_efficiency.fillna(1)
    stp_plt_lookup_utilization = resource_utilization.fillna(1)
    stp_plt_efficiency = stp_plt_input_efficiency.where(tool == "", stp_plt_lookup_efficiency)
    stp_plt_utilization = stp_plt_input_utilization.where(tool == "", stp_plt_lookup_utilization)
    stp_plt_cycle_time = capacity * capacity_multiplier * stp_plt_efficiency * stp_plt_utilization

    ideal_cycle_time = pd.Series(pd.NA, index=input_df.index, dtype="Float64")
    ideal_cycle_time = ideal_cycle_time.mask(dept == "MD", mld_cycle_time)
    ideal_cycle_time = ideal_cycle_time.mask(dept == "AS", as_cycle_time)
    ideal_cycle_time = ideal_cycle_time.mask(dept.isin(["STP", "PLT"]), stp_plt_cycle_time)
    ideal_cycle_time = input_ideal_cycle_time.combine_first(ideal_cycle_time)
    capacity_source.loc[input_ideal_cycle_time.notna()] = "Ideal cycle time"

    final_efficiency = pd.Series(pd.NA, index=input_df.index, dtype="Float64")
    final_utilization = pd.Series(pd.NA, index=input_df.index, dtype="Float64")
    final_efficiency = final_efficiency.mask(dept == "MD", mld_efficiency).mask(dept == "AS", 1).mask(dept.isin(["STP", "PLT"]), stp_plt_efficiency)
    final_utilization = final_utilization.mask(dept == "MD", 1).mask(dept == "AS", as_utilization).mask(dept.isin(["STP", "PLT"]), stp_plt_utilization)

    request_df = pd.DataFrame({
        "Name": material,
        "Description": "",
        "Notes": "",
        "ToolPlan": tool,
        "Resource": resource,
        "Spec": resolve_spec(material, resource, existing_df),
        "mlxIdealCycleTime": ideal_cycle_time.round().astype("Int64"),
        "mlxProductionVersion": "",
        "mlxPriority": priority.apply(lambda x: "" if pd.isna(x) else int(x)),
        "mlxERPRoute": (material + "-" + group_counter).mask(group_counter.isin(["", "1"]), material),
        "RowType": "Add New TPM",
        "GroupCounter": pd.to_numeric(group_counter, errors="coerce").fillna(1),
        "Dept": dept,
        "Capacity": capacity,
        "InputIdealCycleTime": input_ideal_cycle_time,
        "CapacitySource": capacity_source,
        "Tool Cavity": input_tool_cavity,
        "FinalToolCavity": tool_cavity,
        "Efficiency": input_efficiency,
        "Utilization": input_utilization,
        "ResourceEfficiency": resource_efficiency,
        "ResourceUtilization": resource_utilization,
        "FinalEfficiency": final_efficiency,
        "FinalUtilization": final_utilization
    })
    invalid_dept_df = request_df[~request_df["Dept"].isin(["MD", "AS", "STP", "PLT"])].copy()
    request_df = request_df[request_df["Dept"].isin(["MD", "AS", "STP", "PLT"])].copy()

    blank_key_df = request_df[(request_df["Name"] == "") | (request_df["Resource"] == "")].copy()
    missing_capacity_df = request_df[
        (request_df["Name"] != "")
        & (request_df["Resource"] != "")
        & request_df["mlxIdealCycleTime"].isna()
    ].copy()
    request_df = request_df[
        (request_df["Name"] != "")
        & (request_df["Resource"] != "")
        & request_df["mlxIdealCycleTime"].notna()
    ].copy()

    request_df["_ToolPlanClean"] = request_df["ToolPlan"].apply(clean_tool)
    request_df["_key_general"] = request_df["Name"].apply(clean_string) + "|" + request_df["Resource"].apply(clean_string) + "|" + request_df["mlxERPRoute"].apply(clean_tool)
    request_df["_key_tool"] = request_df["_key_general"] + "|" + request_df["_ToolPlanClean"]
    request_df["_final_key"] = request_df["_key_tool"].where(request_df["_ToolPlanClean"] != "", request_df["_key_general"])

    # Same Material + Resource (+ Tool) on several group counters: keep the highest group counter only.
    route_free_key = request_df["Name"] + "|" + request_df["Resource"] + "|" + request_df["_ToolPlanClean"]
    max_group_counter = request_df.groupby(route_free_key)["GroupCounter"].transform("max")
    lower_route_df = request_df[request_df["GroupCounter"] < max_group_counter].copy()
    lower_route_df["KeptGroupCounter"] = max_group_counter[lower_route_df.index]
    request_df = request_df[request_df["GroupCounter"] == max_group_counter].copy()

    conflicting_values = request_df.groupby("_final_key")["mlxIdealCycleTime"].nunique().reset_index(name="IdealCycleTimeCount")
    conflicting_values = conflicting_values[conflicting_values["IdealCycleTimeCount"] > 1]

    conflict_df = request_df[request_df["_final_key"].isin(conflicting_values["_final_key"])].copy()
    request_df = request_df[~request_df["_final_key"].isin(conflicting_values["_final_key"])].drop_duplicates(subset=["_final_key"], keep="last").copy()

    return request_df, excluded_df, blank_key_df, missing_capacity_df, invalid_dept_df, conflict_df, lower_route_df


# ============================================================
# UPDATE EXISTING NORMAL TPM OR ADD NEW TPM
# ============================================================

def process_normal_rows(existing_df, request_df):
    updated_existing_df = existing_df.copy()
    existing_name = updated_existing_df["Name"].apply(clean_string)
    existing_route = updated_existing_df["mlxERPRoute"].apply(clean_tool)
    updated_existing_df["_key_general"] = existing_name + "|" + updated_existing_df["Resource"].apply(clean_string) + "|" + existing_route
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
        new_sorting_df = pd.DataFrame({
            "Name": new_sorting_requests["Name"],
            "Description": "",
            "Notes": "",
            "ToolPlan": "",
            "Resource": new_sorting_requests["Resource"],
            "Spec": resolve_spec(new_sorting_requests["Name"], new_sorting_requests["Resource"], existing_df),
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
    print(f"Reading input file: {INPUT_FILE}")
    excel_file = pd.ExcelFile(INPUT_FILE)
    sheet_name = excel_file.sheet_names[0]
    print(f"Worksheet: {sheet_name}")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    materials = input_df["Material"].apply(clean_string).drop_duplicates().tolist()

    print(f"Found {len(materials)} materials.")
    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)
    found_materials = set(existing_df["Name"].apply(clean_string).unique())
    missing_material_df = input_df[~input_df["Material"].apply(clean_string).isin(found_materials)].copy()
    valid_materials = set(found_materials)
    input_df = input_df[input_df["Material"].apply(clean_string).isin(valid_materials)].copy()

    print(f"Found {len(existing_df)} existing rows.")
    print("Building and processing TPM requests...")

    normal_request_df, excluded_df, blank_key_df, missing_capacity_df, invalid_dept_df, normal_conflict_df, lower_route_df = build_normal_requests(input_df, existing_df)
    sorting_request_df, sorting_conflict_df = build_sorting_requests(input_df)

    existing_df, new_normal_df, normal_update_audit_df, matched_normal_request_df = process_normal_rows(existing_df, normal_request_df)
    existing_df, new_sorting_df, sorting_update_audit_df = process_sorting_rows(existing_df, sorting_request_df)

    new_rows_df = pd.concat([new_normal_df, new_sorting_df], ignore_index=True)
    is_ymhi_row = new_rows_df["Resource"].astype(str).str.upper().str.contains("YMHI", regex=False)
    spec_warning_df = new_rows_df[new_rows_df["Spec"].fillna("").astype(str) == ""].copy()
    spec_warning_df["Warning"] = np.where(
        is_ymhi_row[spec_warning_df.index],
        "YMHI resource: no existing Spec with sort/sorting/lubrication (without 'production') found; Spec left blank",
        "Normal resource: no existing Spec without sort/sorting/lubrication found; Spec left blank",
    )

    final_df = pd.concat([existing_df, new_normal_df, new_sorting_df], ignore_index=True)
    final_df = final_df.reindex(columns=OUTPUT_COLUMNS)

    new_row_mask = final_df["RowType"].isin(["Add New TPM", "Add New Sorting"])
    final_df.insert(0, "Execute", new_row_mask.map({True: "Insert/Update", False: "Update"}))
    final_df.insert(1, "Completion Message", "")
    final_df = final_df[["Execute", "Completion Message", *OUTPUT_COLUMNS]]
    erp_route_pos = final_df.columns.get_loc("mlxERPRoute") + 1
    final_df.insert(erp_route_pos, "ReplaceDetails", "True")
    final_df.insert(erp_route_pos + 1, "ReplaceDetailsSubentityListNames", "Details")

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

    calculation_audit_df = normal_request_df[["Name", "Resource", "ToolPlan", "Dept", "InputIdealCycleTime", "CapacitySource",
        "Capacity", "Tool Cavity", "FinalToolCavity",
        "Efficiency", "Utilization", "ResourceEfficiency", "ResourceUtilization",
        "FinalEfficiency", "FinalUtilization", "mlxIdealCycleTime"]].rename(columns={"mlxIdealCycleTime": "NewIdealCycleTime"}).copy()

    print(f"Normal TPM rows added: {len(new_normal_df)}.")
    print(f"Existing normal TPM rows updated: {len(normal_update_audit_df)}.")
    print(f"Sorting/Lubricant rows added: {len(new_sorting_df)}.")
    print(f"Existing Sorting/Lubricant rows updated: {len(sorting_update_audit_df)}.")
    print(f"Conflicting normal TPM requests skipped: {len(normal_conflict_df)}.")
    print(f"Conflicting Sorting/Lubricant requests skipped: {len(sorting_conflict_df)}.")
    print(f"Lower group counter duplicates skipped: {len(lower_route_df)}.")
    print(f"Missing Capacity rows skipped: {len(missing_capacity_df)}.")
    print(f"Blank Material/Resource rows skipped: {len(blank_key_df)}.")
    print(f"Invalid Dept rows skipped: {len(invalid_dept_df)}.")
    print(f"Excluded resource rows skipped: {len(excluded_df)}.")
    print(f"Material not found rows skipped: {len(missing_material_df)}.")

    # Raw input rows use input column names; align them with the request columns.
    raw_input_columns = {"Material": "Name", "Tool": "ToolPlan"}
    skipped_parts = [
        (missing_material_df.rename(columns=raw_input_columns), "Material not found in Tool Plan Matrix"),
        (excluded_df.rename(columns=raw_input_columns), "Excluded resource (C_RFE / C_RE / C_FE)"),
        (invalid_dept_df, "Invalid Dept (not MD / AS / STP / PLT)"),
        (blank_key_df, "Blank Material or Resource"),
        (missing_capacity_df, "Missing Capacity / Ideal cycle time"),
        (lower_route_df, "Lower group counter duplicate (higher group counter kept)"),
        (normal_conflict_df, "Conflicting cycle time for same Material / Resource / ERPRoute / Tool"),
        (sorting_conflict_df, "Conflicting Sorting/Lubricant cycle time"),
    ]
    skipped_df = pd.concat([part.assign(SkipReason=reason) for part, reason in skipped_parts if not part.empty], ignore_index=True) \
        if any(not part.empty for part, _ in skipped_parts) else pd.DataFrame(columns=["SkipReason"])
    skipped_df = skipped_df.drop(columns=["_ToolPlanClean", "_key_general", "_key_tool", "_final_key", "_sorting_key"], errors="ignore")
    skipped_df = skipped_df[["SkipReason", *[c for c in skipped_df.columns if c != "SkipReason"]]]

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        final_df.to_excel(writer, sheet_name="Tool Plan Matrix Output", index=False)
        normal_update_audit_df.to_excel(writer, sheet_name="Normal Update Audit", index=False)
        sorting_update_audit_df.to_excel(writer, sheet_name="Sorting Update Audit", index=False)
        calculation_audit_df.to_excel(writer, sheet_name="Calculation Audit", index=False)
        skipped_df.to_excel(writer, sheet_name="Skipped Rows", index=False)
        spec_warning_df.to_excel(writer, sheet_name="Spec Warning", index=False)

    print(f"Final TPM rows: {len(final_df)}.")
    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()