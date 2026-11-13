"""Count active alternative BOMs per material.

Excel columns: Material
Adds: ALT_BOM_COUNT (0 when none)
"""
from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input, write_output
from routing.data import bom


def check_alt_bom_count(df, conn=None, plant=PLANT):
    df = df.copy()
    materials = df["Material"].astype(str).tolist()
    with snowflake_session(conn) as c:
        bom_df = bom.alt_bom_count(c, materials, plant)

    bom_df["Material"] = bom_df["MATNR"].astype(str).str.lstrip("0")
    df["Material"] = df["Material"].astype(str)

    if "ALT_BOM_COUNT" in df.columns:
        df = df.drop(columns=["ALT_BOM_COUNT"])

    df = df.merge(bom_df[["Material", "ALT_BOM_COUNT"]], on="Material", how="left")
    df["ALT_BOM_COUNT"] = df["ALT_BOM_COUNT"].fillna(0).astype(int)
    return df


def run(input_path, output_path=None, conn=None, plant=PLANT):
    df = check_alt_bom_count(read_input(input_path), conn=conn, plant=plant)
    saved = write_output(df, output_path or input_path)
    print(f"Done. {len(df)} materials processed. Saved to: {saved}")
    return df
