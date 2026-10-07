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
    r"C:\Users\nguyeb3\Downloads\delete_routing.xlsx"
)

OUTPUT_FILE = Path(
    "output/delete_tpm.xlsx"
)

REQUIRED_COLUMNS = [
    "Material",
    "Resource"
]

# ============================================================
# PREPARE DELETE INPUT
# ============================================================

def prepare_delete_input(input_df):
    delete_df = input_df.copy()

    delete_df["Material"] = delete_df["Material"].apply(clean_string)
    delete_df["Resource"] = delete_df["Resource"].apply(clean_string)

    blank_key_rows = delete_df[
        (delete_df["Material"] == "")
        | (delete_df["Resource"] == "")
    ].copy()

    delete_df = delete_df[
        (delete_df["Material"] != "")
        & (delete_df["Resource"] != "")
    ].copy()

    delete_df = add_material_resource_key(
        delete_df,
        "Material",
        "Resource"
    )

    delete_df = delete_df.drop_duplicates(
        subset=["_key"]
    )

    return delete_df, blank_key_rows


# ============================================================
# DELETE TPM ROWS
# ============================================================

def delete_matching_rows(existing_df, delete_df):
    keyed_existing = add_material_resource_key(
        existing_df,
        "Name",
        "Resource"
    )

    delete_keys = set(delete_df["_key"])
    delete_mask = keyed_existing["_key"].isin(delete_keys)

    deleted_rows_df = keyed_existing.loc[delete_mask].copy()
    remaining_df = keyed_existing.loc[~delete_mask].copy()

    deleted_rows_df["RowType"] = "Deleted"
    remaining_df["RowType"] = "Existing"

    deleted_rows_df = deleted_rows_df.drop(columns="_key")
    remaining_df = remaining_df.drop(columns="_key")

    remaining_df = remaining_df.sort_values(
        by=["Name", "mlxPriority", "Resource", "ToolPlan"],
        na_position="last"
    )

    deleted_rows_df = deleted_rows_df.sort_values(
        by=["Name", "Resource", "ToolPlan"],
        na_position="last"
    )

    return (
        remaining_df[OUTPUT_COLUMNS],
        deleted_rows_df[OUTPUT_COLUMNS]
    )


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading delete request file...")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    delete_df, blank_key_df = prepare_delete_input(input_df)

    materials = (
        delete_df["Material"]
        .drop_duplicates()
        .tolist()
    )

    print(f"Found {len(materials)} materials.")
    print("Loading existing Tool Plan Matrix...")

    existing_df = fetch_existing_tool_plan_matrix(materials)

    print(f"Found {len(existing_df)} existing TPM rows.")

    not_found_df = get_missing_input_rows(
        delete_df.drop(columns="_key"),
        existing_df
    )

    remaining_df, deleted_rows_df = delete_matching_rows(
        existing_df,
        delete_df
    )

    print(f"Removed {len(deleted_rows_df)} TPM rows.")
    print(f"Unmatched input pairs: {len(not_found_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        remaining_df.to_excel(
            writer,
            sheet_name="Remaining TPM Output",
            index=False
        )

        deleted_rows_df.to_excel(
            writer,
            sheet_name="Deleted Rows Audit",
            index=False
        )

        not_found_df.to_excel(
            writer,
            sheet_name="Material Resource Not Found",
            index=False
        )

        blank_key_df.to_excel(
            writer,
            sheet_name="Blank Material Resource",
            index=False
        )

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()