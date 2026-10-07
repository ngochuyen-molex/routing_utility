from pathlib import Path

import pandas as pd

from tpm_common import OUTPUT_COLUMNS, clean_string, fetch_existing_tool_plan_matrix, validate_input_columns, clean_tool


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\csvt_oct.xlsx")
OUTPUT_FILE = Path("output/update_idealcycle.xlsx")
EFFICIENCY_FILE = Path(r"\\MLXVHAVWPAPP2\MXV_Shared\PUBLIC\OperationGroup(OPG)\DATA_OE\huyen_data\Eff_Util_workcenter.xlsx")

REQUIRED_COLUMNS = ["Material", "Resource", "Capacity", "Efficiency", "Tool Cavity"]


# ============================================================
# HELPERS
# ============================================================


def build_update_key(row):
    material = clean_string(row["Material"])
    resource = clean_string(row["Resource"])
    tool = clean_tool(row["Tool"])
    return f"{material}|{resource}|{tool}" if tool else f"{material}|{resource}"


# ============================================================
# LOAD EFFICIENCY LOOKUP
# ============================================================

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
# PREPARE CAPACITY INPUT
# ============================================================

def prepare_capacity_input(input_df):
    update_df = input_df.copy()

    update_df["Material"] = update_df["Material"].apply(clean_string)
    update_df["Resource"] = update_df["Resource"].apply(clean_string)
    update_df["Tool"] = update_df["Tool"].apply(clean_tool) if "Tool" in update_df.columns else ""
    update_df["Capacity"] = pd.to_numeric(update_df["Capacity"], errors="coerce")
    update_df["Efficiency"] = pd.to_numeric(update_df["Efficiency"], errors="coerce")
    update_df["Tool Cavity"] = pd.to_numeric(update_df["Tool Cavity"], errors="coerce")

    blank_key_df = update_df[(update_df["Material"] == "") | (update_df["Resource"] == "")].copy()
    update_df = update_df[(update_df["Material"] != "") & (update_df["Resource"] != "")].copy()

    missing_capacity_df = update_df[update_df["Capacity"].isna()].copy()
    update_df = update_df[update_df["Capacity"].notna()].copy()

    efficiency_lookup = load_efficiency_lookup()
    update_df["ResourceEfficiency"] = update_df["Resource"].map(efficiency_lookup)

    # --------------------------------------------------------
    # TOOL BLANK:
    # Excel Efficiency -> Resource Efficiency -> 1
    # --------------------------------------------------------
    no_tool_efficiency = (
        update_df["Efficiency"]
        .replace(0, pd.NA)
        .fillna(update_df["ResourceEfficiency"])
        .fillna(1)
    )

    # --------------------------------------------------------
    # TOOL EXISTS:
    # Excel Efficiency -> 1
    # (DO NOT use Resource Efficiency lookup)
    # --------------------------------------------------------
    with_tool_efficiency = (
        update_df["Efficiency"]
        .fillna(1)
    )

    update_df["FinalEfficiency"] = no_tool_efficiency.where(
        update_df["Tool"] == "",
        with_tool_efficiency
    )

    # Blank Tool Cavity becomes 1.
    update_df["FinalToolCavity"] = update_df["Tool Cavity"].fillna(1)

    update_df["NewIdealCycleTime"] = (
        update_df["Capacity"]
        * update_df["FinalToolCavity"]
        * update_df["FinalEfficiency"]
    ).round().astype(int)

    # Tool specified: Material|Resource|Tool.
    # Tool blank: Material|Resource.
    update_df["_key"] = update_df.apply(build_update_key, axis=1)

    conflicting_values = update_df.groupby("_key")["NewIdealCycleTime"].nunique().reset_index(name="IdealCycleTimeCount")
    conflicting_values = conflicting_values[conflicting_values["IdealCycleTimeCount"] > 1]

    conflict_df = update_df[update_df["_key"].isin(conflicting_values["_key"])].copy()
    update_df = update_df[~update_df["_key"].isin(conflicting_values["_key"])].copy()
    update_df = update_df.drop_duplicates(subset=["_key"], keep="last")

    return update_df, blank_key_df, missing_capacity_df, conflict_df


# ============================================================
# FIND UNMATCHED INPUT ROWS
# ============================================================

def get_unmatched_input_rows(update_df, existing_df):
    existing_keys = existing_df.copy()

    existing_keys["_key_general"] = existing_keys["Name"].apply(clean_string) + "|" + existing_keys["Resource"].apply(clean_string)
    existing_keys["_key_tool"] = existing_keys["_key_general"] + "|" + existing_keys["ToolPlan"].apply(clean_tool)

    general_keys = set(existing_keys["_key_general"])
    tool_keys = set(existing_keys["_key_tool"])

    matched_mask = update_df.apply(
        lambda row: row["_key"] in tool_keys if clean_tool(row["Tool"]) else row["_key"] in general_keys,
        axis=1
    )

    return update_df[~matched_mask].drop(columns="_key", errors="ignore").copy()


# ============================================================
# UPDATE IDEAL CYCLE TIME
# ============================================================

def update_ideal_cycle_time(existing_df, update_df):
    result_df = existing_df.copy()

    result_df["_key_general"] = result_df["Name"].apply(clean_string) + "|" + result_df["Resource"].apply(clean_string)
    result_df["_key_tool"] = result_df["_key_general"] + "|" + result_df["ToolPlan"].apply(clean_tool)

    cycle_time_lookup = update_df.set_index("_key")["NewIdealCycleTime"].to_dict()

    # Tool-specific match has priority. If unavailable, use Material + Resource.
    result_df["_NewIdealCycleTime"] = result_df["_key_tool"].map(cycle_time_lookup).fillna(result_df["_key_general"].map(cycle_time_lookup))
    matching_mask = result_df["_NewIdealCycleTime"].notna()

    updated_rows_df = result_df.loc[matching_mask].copy()
    updated_rows_df["OldIdealCycleTime"] = updated_rows_df["mlxIdealCycleTime"]
    updated_rows_df["NewIdealCycleTime"] = updated_rows_df["_NewIdealCycleTime"].round().astype(int)

    old_numeric = pd.to_numeric(updated_rows_df["OldIdealCycleTime"], errors="coerce")
    new_numeric = pd.to_numeric(updated_rows_df["NewIdealCycleTime"], errors="coerce")
    updated_rows_df["IdealCycleTimeChanged"] = old_numeric.ne(new_numeric)

    result_df.loc[matching_mask, "mlxIdealCycleTime"] = result_df.loc[matching_mask, "_NewIdealCycleTime"].round().astype(int).to_numpy()
    result_df.loc[matching_mask, "RowType"] = "Ideal Cycle Time Updated"
    updated_rows_df["RowType"] = "Ideal Cycle Time Updated"

    result_df = result_df.drop(columns=["_key_general", "_key_tool", "_NewIdealCycleTime"], errors="ignore")
    updated_rows_df = updated_rows_df.drop(columns=["_key_general", "_key_tool", "_NewIdealCycleTime"], errors="ignore")

    result_df = result_df.sort_values(by=["Name", "Resource", "ToolPlan", "mlxPriority"], na_position="last")

    return result_df[OUTPUT_COLUMNS], updated_rows_df


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading ideal cycle time update file...")

    input_df = pd.read_excel(INPUT_FILE, sheet_name="Sheet1", dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    update_df, blank_key_df, missing_capacity_df, conflict_df = prepare_capacity_input(input_df)
    materials = update_df["Material"].drop_duplicates().tolist()

    print(f"Found {len(materials)} materials.")
    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)

    print(f"Found {len(existing_df)} existing TPM rows.")

    not_found_df = get_unmatched_input_rows(update_df, existing_df)
    result_df, updated_rows_df = update_ideal_cycle_time(existing_df, update_df)

    calculation_audit_df = update_df[
        [
            "Material",
            "Resource",
            "Tool",
            "Capacity",
            "Tool Cavity",
            "FinalToolCavity",
            "Efficiency",
            "ResourceEfficiency",
            "FinalEfficiency",
            "NewIdealCycleTime"
        ]
    ].copy()

    print(f"Updated {len(updated_rows_df)} TPM rows.")
    print(f"Unmatched input rows: {len(not_found_df)}.")
    print(f"Missing Capacity rows skipped: {len(missing_capacity_df)}.")
    print(f"Conflicting calculations skipped: {len(conflict_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        result_df.to_excel(writer, sheet_name="Updated TPM Output", index=False)
        updated_rows_df.to_excel(writer, sheet_name="Updated Rows Audit", index=False)
        calculation_audit_df.to_excel(writer, sheet_name="Calculation Audit", index=False)
        not_found_df.to_excel(writer, sheet_name="Input Rows Not Found", index=False)
        missing_capacity_df.to_excel(writer, sheet_name="Missing Capacity", index=False)
        blank_key_df.to_excel(writer, sheet_name="Blank Material Resource", index=False)
        conflict_df.to_excel(writer, sheet_name="Conflicting Cycle Time", index=False)

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()