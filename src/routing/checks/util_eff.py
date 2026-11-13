"""Compare Excel Efficiency / Utilization with routing values at operation 0020.

Excel columns: Material, group / group Counter, Efficiency, Utilization
Prints mismatches and rows found in only one source; returns the merged DataFrame.
"""
from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input
from routing.data import util_eff

EXCEL_RENAME = {
    "Material": "material",
    "group": "group_counter",
    "group Counter": "group_counter",
    "Efficiency": "excel_eff",
    "Utilization": "excel_util",
}


def compare_routing_eff_util(df_excel, conn=None, plant=PLANT):
    with snowflake_session(conn) as c:
        df_sf = util_eff.eff_util_0020(c, plant)
    df_sf.columns = df_sf.columns.str.strip().str.lower()

    df_excel = df_excel.rename(columns=EXCEL_RENAME)

    df_sf["material"] = df_sf["material"].astype(str).str.strip()
    df_excel["material"] = df_excel["material"].astype(str).str.strip()
    df_sf["group_counter"] = df_sf["group_counter"].astype(str).str.strip()
    df_excel["group_counter"] = df_excel["group_counter"].astype(str).str.strip()

    merged = df_sf.merge(df_excel, on=["material", "group_counter"], how="outer", indicator=True)
    merged["eff_match"] = merged["efficiency"] == merged["excel_eff"]
    merged["util_match"] = merged["utilization"] == merged["excel_util"]
    return merged


def report(merged):
    mismatches = merged[(merged["eff_match"] == False) | (merged["util_match"] == False)]  # noqa: E712

    print(f"Total rows compared: {len(merged)}")
    print(f"Mismatches found: {len(mismatches)}\n")

    if not mismatches.empty:
        print("=== MISMATCHES ===")
        print(mismatches[["material", "group_counter", "routing_name",
                          "efficiency", "excel_eff", "utilization", "excel_util"]].to_string(index=False))

    only_sf = merged[merged["_merge"] == "left_only"]
    only_excel = merged[merged["_merge"] == "right_only"]
    if not only_sf.empty:
        print(f"\n=== In Snowflake only ({len(only_sf)} rows) ===")
        print(only_sf[["material", "group_counter", "routing_name"]].to_string(index=False))
    if not only_excel.empty:
        print(f"\n=== In Excel only ({len(only_excel)} rows) ===")
        print(only_excel[["material", "group_counter"]].to_string(index=False))


def run(input_path, sheet_name="Sheet1", conn=None, plant=PLANT):
    merged = compare_routing_eff_util(read_input(input_path, sheet_name=sheet_name), conn=conn, plant=plant)
    report(merged)
    return merged
