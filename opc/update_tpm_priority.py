from pathlib import Path
import pandas as pd
from tpm_common import (
    OUTPUT_COLUMNS,
    add_material_resource_key,
    clean_string,
    fetch_existing_tool_plan_matrix,
    get_missing_input_rows,
    validate_input_columns
)

# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(
    r"C:\Users\nguyeb3\OneDrive - kochind.com\change_routing.xlsx"
)

OUTPUT_FILE = Path(
    "output/update_tpm_priority_result.xlsx"
)

REQUIRED_COLUMNS = [
    "Material",
    "Resource",
    "Priority"
]


# ============================================================
# VALIDATE PRIORITY INPUT
# ============================================================
def prepare_priority_input(input_df):

    update_df = input_df.copy()

    update_df["Material"] = update_df["Material"].apply(clean_string)
    update_df["Resource"] = update_df["Resource"].apply(clean_string)
    update_df["Priority"] = pd.to_numeric(update_df["Priority"], errors="coerce")

    blank_key_rows = update_df[(update_df["Material"] == "") | (update_df["Resource"] == "")].copy()

    update_df = update_df[(update_df["Material"] != "") & (update_df["Resource"] != "")].copy()

    missing_priority_rows = update_df[update_df["Priority"].isna()].copy()

    update_df = update_df[update_df["Priority"].notna()].copy()

    update_df["Priority"] = update_df["Priority"].round().astype(int)

    update_df = add_material_resource_key(update_df, "Material", "Resource")

    conflicting_priorities = (
        update_df.groupby("_key")["Priority"]
        .nunique()
        .reset_index(name="PriorityCount")
    )

    conflicting_priorities = conflicting_priorities[
        conflicting_priorities["PriorityCount"] > 1
    ]

    conflict_rows = update_df[
        update_df["_key"].isin(conflicting_priorities["_key"])
    ].copy()

    update_df = update_df[
        ~update_df["_key"].isin(conflicting_priorities["_key"])
    ].copy()

    update_df = update_df.drop_duplicates(subset=["_key"], keep="last")

    return update_df, blank_key_rows, missing_priority_rows, conflict_rows


# ============================================================
# UPDATE PRIORITY
# ============================================================
def update_priority(existing_df, update_df):

    result_df = add_material_resource_key(existing_df, "Name", "Resource")

    priority_lookup = update_df.set_index("_key")["Priority"].to_dict()

    matching_mask = result_df["_key"].isin(priority_lookup)

    updated_rows_df = result_df.loc[matching_mask].copy()

    updated_rows_df["OldPriority"] = updated_rows_df["mlxPriority"]

    updated_rows_df["NewPriority"] = (
        updated_rows_df["_key"].map(priority_lookup)
    )

    updated_rows_df["PriorityChanged"] = (
        updated_rows_df["OldPriority"]
        !=
        updated_rows_df["NewPriority"]
    )

    result_df.loc[matching_mask, "mlxPriority"] = (
        result_df.loc[matching_mask, "_key"]
        .map(priority_lookup)
        .to_numpy()
    )

    result_df.loc[matching_mask, "RowType"] = "Priority Updated"

    updated_rows_df["RowType"] = "Priority Updated"

    result_df = result_df.drop(columns="_key")
    updated_rows_df = updated_rows_df.drop(columns="_key")

    result_df = result_df.sort_values(
        by=["Name", "mlxPriority", "Resource", "ToolPlan"],
        na_position="last"
    )

    return result_df[OUTPUT_COLUMNS], updated_rows_df

# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading priority update file...")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    update_df, blank_key_df, missing_priority_df, conflict_df = (
    prepare_priority_input(input_df))

    materials = (
        update_df["Material"]
        .drop_duplicates()
        .tolist()
    )

    print(f"Found {len(materials)} materials.")
    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)

    print(f"Found {len(existing_df)} existing TPM rows.")

    not_found_df = get_missing_input_rows(
        update_df.drop(columns="_key"),
        existing_df
    )

    result_df, updated_rows_df = update_priority(
        existing_df,
        update_df
    )

    print(f"Updated {len(updated_rows_df)} TPM rows.")
    print(f"Unmatched input pairs: {len(not_found_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:

        result_df.to_excel(writer, sheet_name="Updated TPM Output", index=False)

        updated_rows_df.to_excel(writer, sheet_name="Updated Rows Audit", index=False)

        not_found_df.to_excel(writer, sheet_name="Material Resource Not Found", index=False)

        missing_priority_df.to_excel(writer, sheet_name="Missing Priority", index=False)

        blank_key_df.to_excel(writer, sheet_name="Blank Material Resource", index=False)

        conflict_df.to_excel(writer, sheet_name="Conflicting Priority", index=False)

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()