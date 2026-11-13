import os
from pathlib import Path

import pandas as pd


def clean_path(path):
    """Strip quotes/spaces that drag & drop adds."""
    return str(path).strip().strip('"')


def ask_path(prompt="Enter Excel file path (or drag & drop): "):
    return clean_path(input(prompt))


def read_input(path, sheet_name=0, **kwargs):
    return pd.read_excel(clean_path(path), sheet_name=sheet_name, **kwargs)


def write_output(df, path):
    path = Path(clean_path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)
    return path


def write_sheets(sheets, path):
    """sheets = {"Sheet name": df, ...} -> one workbook."""
    path = Path(clean_path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
    return path


def with_suffix(path, suffix):
    """'C:/x/input.xlsx' + '_checked' -> 'C:/x/input_checked.xlsx'."""
    root, ext = os.path.splitext(clean_path(path))
    return f"{root}{suffix}{ext or '.xlsx'}"
