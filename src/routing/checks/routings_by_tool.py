"""Find the work center at operation 0020 for each Material + Tool pair.

Excel columns: Material, a column containing "tool", optional "resource" / "cavity" columns
Writes two sheets: Summary (one row per input) and Sheet1 (one row per work center).
"""
import pandas as pd

from routing.core.clean import clean_material_series
from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input, with_suffix, write_sheets
from routing.data import routing as routing_data


def _find_column(df, word):
    return next((col for col in df.columns if word in str(col).lower()), None)


def find_work_centers(df, conn=None, plant=PLANT):
    """Returns (summary_df, expanded_df)."""
    df = df.copy()
    df["Material"] = clean_material_series(df["Material"])

    tool_col = _find_column(df, "tool")
    if tool_col is None:
        raise ValueError(f"No Tool column found. Columns: {df.columns.tolist()}")

    res_col = _find_column(df, "resource")
    if res_col is None:
        res_col = "Resource"
        df[res_col] = ""

    df["_Tool"] = df[tool_col].fillna("").astype(str).str.strip()

    with snowflake_session(conn) as c:
        sf_df = routing_data.work_centers_0020(c, df["Material"].unique().tolist(), plant)

    sf_df["ROUTING_DESCRIPTION"] = sf_df["ROUTING_DESCRIPTION"].fillna("").astype(str).str.strip()
    sf_df["WORK_CENTER"] = sf_df["WORK_CENTER"].astype(str).str.strip()

    # looked up after the Tool column, same order as before ("Tool Cavity" also contains "tool")
    cavity_col = _find_column(df, "cavity")
    if cavity_col is None:
        cavity_col = "Tool Cavity"
        df[cavity_col] = ""

    work_centers, match_info, conv_numerators = [], [], []

    for _, row in df.iterrows():
        tool = row["_Tool"]
        mat_routings = sf_df[sf_df["MATERIAL"] == row["Material"]]

        if tool:
            matched = mat_routings[mat_routings["ROUTING_DESCRIPTION"].str.contains(tool, na=False)]
            matched = matched[matched["WORK_CENTER"] != tool]  # the tool itself is not a work center
        else:
            matched = mat_routings

        if matched.empty:
            work_centers.append("")
            match_info.append("No routing found")
            conv_numerators.append("")
            continue

        unique_wcs = matched.drop_duplicates(subset=["WORK_CENTER"])
        if len(unique_wcs) == 1:
            work_centers.append(unique_wcs.iloc[0]["WORK_CENTER"])
            match_info.append("Found")
            conv_numerators.append(unique_wcs.iloc[0]["CONV_NUMERATOR"])
        else:
            work_centers.append(", ".join(sorted(unique_wcs["WORK_CENTER"])))
            match_info.append(f"Multiple ({len(unique_wcs)})")
            conv_numerators.append(", ".join(
                str(int(r["CONV_NUMERATOR"])) if pd.notna(r["CONV_NUMERATOR"]) else ""
                for _, r in unique_wcs.sort_values("WORK_CENTER").iterrows()
            ))

    df[res_col] = work_centers
    df[cavity_col] = conv_numerators
    df["MATCH_STATUS"] = match_info

    # One row per work center
    expanded_rows = []
    for _, row in df.iterrows():
        wc_val = row[res_col]
        cav_val = str(row[cavity_col]) if row[cavity_col] else ""
        if wc_val and ", " in str(wc_val):
            wc_list = str(wc_val).split(", ")
            cav_list = cav_val.split(", ") if cav_val else [""] * len(wc_list)
            for wc, cav in zip(wc_list, cav_list):
                new_row = row.copy()
                new_row[res_col] = wc
                new_row[cavity_col] = cav
                new_row["MATCH_STATUS"] = "Found"
                expanded_rows.append(new_row)
        else:
            expanded_rows.append(row)

    expanded_df = pd.DataFrame(expanded_rows)
    df = df.drop(columns=["_Tool"])
    expanded_df = expanded_df.drop(columns=["_Tool"], errors="ignore")
    return df, expanded_df


def run(input_path, output_path=None, conn=None, plant=PLANT):
    output_path = output_path or with_suffix(input_path, "_with_resource_idealcycletime")
    df, expanded_df = find_work_centers(read_input(input_path), conn=conn, plant=plant)
    saved = write_sheets({"Summary": df, "Sheet1": expanded_df}, output_path)

    status = df["MATCH_STATUS"]
    print(f"Done. {len(df)} rows processed. Saved to: {saved}")
    print(f"  Single work center found: {(status == 'Found').sum()}")
    print(f"  Multiple work centers: {status.str.startswith('Multiple').sum()}")
    print(f"  No routing found: {(status == 'No routing found').sum()}")
    print(f"  Expanded rows (Sheet 2): {len(expanded_df)}")
    return df, expanded_df
