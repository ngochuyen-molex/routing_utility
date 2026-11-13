"""Compare Excel Capacity with routing base quantity at operations 0020 and 0030.

Excel columns: Material, Resource, Capacity, Tool Cavity, optional Tool / group / group counter
Matching: group + group counter when both filled, else Resource (+ Tool in description).
Adds: MATCH_METHOD, ROUTING_GROUP, ROUTING_GROUP_COUNTER, ROUTING_DESCRIPTION,
      BASE_QTY_0020, BASE_QTY_0030, CHECK_0020, CHECK_0030
Note: when routing is not found, check delete status as well.
"""
import pandas as pd

from routing.core.clean import clean_material_series
from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input, write_output
from routing.data import operation_capacity

TOLERANCE = 0.001


def _compare(expected, actual):
    if pd.notna(expected) and actual is not None:
        return "Match" if abs(actual - expected) < TOLERANCE else "Mismatch"
    if actual is None:
        return "No routing found"
    return "Missing capacity"


def check_routing_capacity(df, conn=None, plant=PLANT):
    df = df.copy()
    df["Material"] = clean_material_series(df["Material"])
    df["Resource"] = df["Resource"].astype(str).str.strip()
    df["group counter"] = pd.to_numeric(df["group counter"], errors="coerce").astype("Int64").astype(str)

    for col in ["Tool", "group", "group counter"]:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("").astype(str).str.strip().str.replace(r"\.0$", "", regex=True)

    df["Capacity"] = pd.to_numeric(df["Capacity"], errors="coerce")

    with snowflake_session(conn) as c:
        sf_df = operation_capacity.base_quantity_0020_0030(c, df["Material"].unique().tolist(), plant)

    sf_df["Material"] = sf_df["MATNR"].str.lstrip("0")
    sf_df["ROUTING_GROUP"] = sf_df["ROUTING_GROUP"].astype(str).str.strip()
    sf_df["GROUP_COUNTER"] = pd.to_numeric(sf_df["GROUP_COUNTER"], errors="coerce").astype("Int64").astype(str)
    sf_df["RESOURCE_NAME"] = sf_df["RESOURCE_NAME"].astype(str).str.strip()
    sf_df["ROUTING_DESCRIPTION"] = sf_df["ROUTING_DESCRIPTION"].fillna("").astype(str).str.strip()
    sf_df["BASE_QUANTITY"] = pd.to_numeric(sf_df["BASE_QUANTITY"], errors="coerce")

    out = {key: [] for key in ["MATCH_METHOD", "ROUTING_GROUP", "ROUTING_GROUP_COUNTER", "ROUTING_DESCRIPTION",
                               "BASE_QTY_0020", "BASE_QTY_0030", "CHECK_0020", "CHECK_0030"]}

    for _, row in df.iterrows():
        mat = row["Material"]
        grp = row.get("group", "")
        gc = row.get("group counter", "")
        tool = row.get("Tool", "")
        capacity = row["Capacity"]
        capacity_30 = row["Capacity"] * row["Tool Cavity"]

        if grp and gc:
            matches = sf_df[(sf_df["Material"] == mat) & (sf_df["ROUTING_GROUP"] == grp) & (sf_df["GROUP_COUNTER"] == gc)]
            method = "Group+Counter"
        else:
            matches = sf_df[(sf_df["Material"] == mat) & (sf_df["RESOURCE_NAME"] == row["Resource"])]
            if tool:
                matches = matches[matches["ROUTING_DESCRIPTION"].str.contains(tool, na=False)]
                method = "Resource+Tool"
            else:
                method = "Resource"

        op20 = matches[matches["OPERATION_NUMBER"] == "0020"]
        op30 = matches[matches["OPERATION_NUMBER"] == "0030"]
        qty_20 = op20.iloc[0]["BASE_QUANTITY"] if not op20.empty else None
        qty_30 = op30.iloc[0]["BASE_QUANTITY"] if not op30.empty else None

        out["MATCH_METHOD"].append(method)
        out["BASE_QTY_0020"].append(qty_20)
        out["BASE_QTY_0030"].append(qty_30)
        out["CHECK_0020"].append(_compare(capacity, qty_20))
        out["CHECK_0030"].append(_compare(capacity_30, qty_30))

        first = matches.iloc[0] if not matches.empty else None
        out["ROUTING_GROUP"].append(first["ROUTING_GROUP"] if first is not None else "")
        out["ROUTING_GROUP_COUNTER"].append(first["GROUP_COUNTER"] if first is not None else "")
        out["ROUTING_DESCRIPTION"].append(first["ROUTING_DESCRIPTION"] if first is not None else "")

    for key, values in out.items():
        df[key] = values
    return df


def summary(df):
    mismatch = ((df["CHECK_0020"] == "Mismatch") | (df["CHECK_0030"] == "Mismatch")).sum()
    no_routing = ((df["CHECK_0020"] == "No routing found") & (df["CHECK_0030"] == "No routing found")).sum()
    all_match = ((df["CHECK_0020"] == "Match") & (df["CHECK_0030"] == "Match")).sum()
    return (f"  Both match: {all_match}\n"
            f"  Mismatch (0020 or 0030): {mismatch}\n"
            f"  No routing found: {no_routing}")


def run(input_path, output_path=None, sheet_name="Sheet1", conn=None, plant=PLANT):
    df = check_routing_capacity(read_input(input_path, sheet_name=sheet_name), conn=conn, plant=plant)
    saved = write_output(df, output_path or input_path)
    print(f"Done. {len(df)} rows processed. Saved to: {saved}")
    print(summary(df))
    return df
