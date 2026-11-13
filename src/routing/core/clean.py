import pandas as pd


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


def clean_material_series(series):
    """Excel material column -> plain strings, e.g. 12345.0 -> '12345'."""
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def to_sap_matnr(material):
    """'12345' -> '000000000000012345' (SAP MATNR is 18 chars, zero padded)."""
    return str(material).zfill(18)


def from_sap_matnr(matnr):
    """'000000000000012345' -> '12345'."""
    return str(matnr).lstrip("0")


def validate_input_columns(df, required_columns):
    missing_columns = sorted(set(required_columns) - set(df.columns))

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}. "
            f"Columns found: {list(df.columns)}"
        )
