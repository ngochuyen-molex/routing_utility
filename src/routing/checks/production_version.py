"""Production version checks (MKAL).

- count_production_versions: number of production versions per material
- lookup_by_group:           match on Material + group + group counter
- lookup_by_attributes:      match on Material + Resource (+ Tool / Lubricant when filled)
- lookup_with_fallback:      group first, then attributes for blank / not found rows
"""
import pandas as pd

from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input, with_suffix, write_output
from routing.data import production_version as pv_data


def _join_sorted(values, sep):
    return sep.join(sorted(set(values)))


# ============================================================
# COUNT
# ============================================================
def count_production_versions(df_excel, conn=None, plant=PLANT):
    df_excel = df_excel.copy()
    df_excel.columns = df_excel.columns.str.strip()
    df_excel["material"] = df_excel["Material"].astype(str).str.strip()
    materials = df_excel["material"].unique().tolist()

    with snowflake_session(conn) as c:
        df_sf = pv_data.count_by_material(c, materials, plant)
    df_sf.columns = ["material", "production_version_count"]
    df_sf["material"] = df_sf["material"].astype(str).str.strip()

    merged = df_excel.merge(df_sf, on="material", how="left")
    merged["production_version_count"] = merged["production_version_count"].fillna(0).astype(int)

    print(f"Total Excel rows:           {len(df_excel)}")
    print(f"Unique materials:           {len(materials)}")
    print(f"Materials with versions:    {merged[merged['production_version_count'] > 0]['material'].nunique()}")
    print(f"Materials without versions: {merged[merged['production_version_count'] == 0]['material'].nunique()}")
    return merged


def run_count(input_path, output_path=None, sheet_name="Sheet1", conn=None, plant=PLANT):
    merged = count_production_versions(read_input(input_path, sheet_name=sheet_name), conn=conn, plant=plant)
    output_path = output_path or with_suffix(input_path, "_version_counts")
    saved = write_output(merged[[c for c in merged.columns if c != "material"]], output_path)
    print(f"\nOutput saved to: {saved}")
    return merged


# ============================================================
# LOOKUP BY GROUP + GROUP COUNTER
# ============================================================
def lookup_by_group(df_excel, conn=None, plant=PLANT):
    """Returns the merged DataFrame incl. the `_merge` indicator column."""
    df_excel = df_excel.copy()
    df_excel.columns = df_excel.columns.str.strip()
    df_excel = df_excel.rename(columns={"group": "routing_group", "group counter": "group_counter"})

    df_excel["material"] = df_excel["Material"].astype(str).str.strip()
    df_excel["routing_group"] = df_excel["routing_group"].astype(str).str.strip()
    df_excel["group_counter"] = df_excel["group_counter"].astype(str).str.strip()

    pairs = df_excel[["material", "routing_group", "group_counter"]].drop_duplicates()
    triples = list(pairs.itertuples(index=False, name=None))

    with snowflake_session(conn) as c:
        df_sf = pv_data.by_group(c, triples, plant)
    df_sf.columns = df_sf.columns.str.strip().str.lower()

    for col in ["material", "routing_group", "group_counter"]:
        df_sf[col] = df_sf[col].astype(str).str.strip()

    merged = df_excel.merge(df_sf, on=["material", "routing_group", "group_counter"], how="left", indicator=True)

    print(f"Total Excel rows: {len(df_excel)}")
    print(f"Matched in MKAL:  {(merged['_merge'] == 'both').sum()}")
    print(f"Not found:        {(merged['_merge'] == 'left_only').sum()}")
    return merged


def run_by_group(input_path, output_path=None, sheet_name="Sheet1", conn=None, plant=PLANT):
    merged = lookup_by_group(read_input(input_path, sheet_name=sheet_name), conn=conn, plant=plant)
    output_path = output_path or with_suffix(input_path, "_with_description")
    saved = write_output(merged[[c for c in merged.columns if c not in ("_merge", "material")]], output_path)
    print(f"\nOutput saved to: {saved}")
    return merged


# ============================================================
# LOOKUP BY MATERIAL + RESOURCE (+ TOOL / LUBRICANT)
# ============================================================
def lookup_by_attributes(df_excel, conn=None, plant=PLANT):
    """Blank Tool / Lubricant in Excel = ignored. Lists every matching version."""
    df_excel = df_excel.copy()
    df_excel.columns = df_excel.columns.str.strip()

    def norm(col):
        return (df_excel[col].fillna("").astype(str).str.strip().str.upper()
                if col in df_excel.columns else "")

    df_excel["material"] = norm("Material")
    df_excel["resource"] = norm("Resource")
    df_excel["tool"] = norm("Tool")
    df_excel["lubricant"] = norm("Lubricant")
    if "_row_id" not in df_excel.columns:
        df_excel["_row_id"] = range(len(df_excel))

    with snowflake_session(conn) as c:
        df_sf = pv_data.by_attributes(c, df_excel["material"].drop_duplicates().tolist(), plant)
    df_sf.columns = df_sf.columns.str.lower()
    df_sf = df_sf.fillna("")

    # Per production version: resource set and PRT set
    pv_key = ["material", "production_version", "description", "routing_group", "group_counter"]
    pv_attrs = (df_sf.groupby(pv_key)
                     .agg(resources=("resource", lambda s: set(s) - {""}),
                          prts=("prt", lambda s: set(s) - {""}))
                     .reset_index()
                     .drop(columns=["routing_group", "group_counter"]))

    cand = df_excel.merge(pv_attrs, on="material", how="left")

    def matches(r):
        if not isinstance(r["resources"], set):
            return False
        if r["resource"] and r["resource"] not in r["resources"]:
            return False
        if r["tool"] and r["tool"] not in r["prts"]:
            return False
        if r["lubricant"] and r["lubricant"] not in r["prts"]:
            return False
        return True

    cand = cand[cand.apply(matches, axis=1)] if len(cand) else cand

    result = (cand.groupby("_row_id")
                  .agg(production_version=("production_version", lambda s: _join_sorted(s, ", ")),
                       description=("description", lambda s: _join_sorted(s, " | ")),
                       match_count=("production_version", "nunique"))
                  .reset_index())
    merged = df_excel.merge(result, on="_row_id", how="left")
    merged["match_count"] = merged["match_count"].fillna(0).astype(int)

    print(f"Total Excel rows:   {len(merged)}")
    print(f"Unique match:       {(merged['match_count'] == 1).sum()}")
    print(f"Multiple matches:   {(merged['match_count'] > 1).sum()}")
    print(f"Not found:          {(merged['match_count'] == 0).sum()}")
    return merged


def run_by_attributes(input_path, output_path=None, sheet_name="Sheet1", conn=None, plant=PLANT):
    merged = lookup_by_attributes(read_input(input_path, sheet_name=sheet_name, dtype=str), conn=conn, plant=plant)
    output_path = output_path or with_suffix(input_path, "_with_pv_by_attributes")
    drop = ["_row_id", "material", "resource", "tool", "lubricant"]
    saved = write_output(merged[[c for c in merged.columns if c not in drop]], output_path)
    print(f"\nOutput saved to: {saved}")
    return merged


# ============================================================
# GROUP FIRST, THEN ATTRIBUTES
# ============================================================
def lookup_with_fallback(df, conn=None, plant=PLANT):
    """1) Match on group + group counter.
    2) Rows with blank group / counter, or not found, fall back to Material + Resource (+ Tool / Lubricant)."""
    df = df.copy()
    df.columns = df.columns.str.strip()
    df["_row_id"] = range(len(df))

    result_cols = ["_row_id", "production_version", "description", "match_method"]

    grp = df["group"].fillna("").str.strip()
    cnt = df["group counter"].fillna("").str.strip()
    has_group = (grp != "") & (cnt != "")

    with snowflake_session(conn) as c:
        step1 = pd.DataFrame(columns=result_cols)
        if has_group.any():
            print("--- Step 1: group + group counter ---")
            r1 = lookup_by_group(df[has_group], conn=c, plant=plant)
            r1 = r1[r1["_merge"] == "both"]
            if len(r1):
                step1 = (r1.groupby("_row_id")
                           .agg(production_version=("production_version", lambda s: _join_sorted(s, ", ")),
                                description=("description", lambda s: _join_sorted(s, " | ")))
                           .reset_index())
                step1["match_method"] = "group"

        rest = df[~df["_row_id"].isin(step1["_row_id"])]
        step2 = pd.DataFrame(columns=result_cols)
        if len(rest):
            print("\n--- Step 2: Material + Resource / Tool / Lubricant ---")
            r2 = lookup_by_attributes(rest, conn=c, plant=plant)
            r2 = r2[r2["match_count"] > 0]
            step2 = r2[["_row_id", "production_version", "description"]].copy()
            step2["match_method"] = "attributes"

    results = pd.concat([step1, step2], ignore_index=True)
    out = df.merge(results, on="_row_id", how="left")
    out["match_method"] = out["match_method"].fillna("not found")

    print("\n--- Summary ---")
    print(out["match_method"].value_counts().to_string())
    return out.drop(columns=["_row_id"])


def run_with_fallback(input_path, output_path=None, sheet_name="Sheet1", conn=None, plant=PLANT):
    out = lookup_with_fallback(read_input(input_path, sheet_name=sheet_name, dtype=str), conn=conn, plant=plant)
    saved = write_output(out, output_path or with_suffix(input_path, "_with_pv"))
    print(f"\nOutput saved to: {saved}")
    return out
