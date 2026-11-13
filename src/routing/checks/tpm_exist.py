"""Does a Tool Plan Matrix exist in OpCenter for each material?

Excel columns: Material (or the column given)
Adds: TPM_Exist = Found / Not Found
"""
from routing.core.clean import clean_string
from routing.core.excel import read_input, write_output
from routing.data.tpm import existing_tpm_names


def unique_materials(df, material_column="Material"):
    if material_column not in df.columns:
        raise ValueError(f"Column '{material_column}' not found. Available columns: {list(df.columns)}")
    return (
        df[material_column].dropna().astype(str).str.strip()
        .loc[lambda s: s != ""].unique().tolist()
    )


def check_tpm_exists(df, material_column="Material"):
    df = df.copy()
    materials = unique_materials(df, material_column)
    found = existing_tpm_names(materials) if materials else set()
    df["TPM_Exist"] = df[material_column].apply(lambda x: "Found" if clean_string(x) in found else "Not Found")
    return df


def run(input_path, output_path=None, material_column="Material", sheet_name=0):
    df = read_input(input_path, sheet_name=sheet_name)

    materials = unique_materials(df, material_column)
    print(f"Found {len(materials)} unique material(s) in Excel.\n")
    if not materials:
        print("No materials to check.")
        return df

    df = check_tpm_exists(df, material_column)

    print(f"{'=' * 60}")
    print(f" FOUND in ToolPlanMatrix: {(df['TPM_Exist'] == 'Found').sum()}")
    print(f" NOT FOUND:              {(df['TPM_Exist'] == 'Not Found').sum()}")
    print(f"{'=' * 60}\n")

    saved = write_output(df, output_path or input_path)
    print(f"Results written back to: {saved}")
    return df
