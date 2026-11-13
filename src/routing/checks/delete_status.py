"""Is the routing at operation 0020 deleted for each Material + Resource pair?

Excel columns: Material, Resource
Adds: ROUTING_GROUP, GROUP_COUNTER, IS_DELETED, MATERIAL_STATUS
Note: duplicate routings (same material + resource) add extra rows.
"""
from routing.core.config import PLANT
from routing.core.db import snowflake_session
from routing.core.excel import read_input, write_output
from routing.data import routing as routing_data

RESULT_COLUMNS = ["ROUTING_GROUP", "GROUP_COUNTER", "IS_DELETED", "MATERIAL_STATUS"]


def check_routing_deleted_status(df, conn=None, plant=PLANT):
    df = df.copy()
    df["Material"] = df["Material"].astype(str).str.strip()
    df["Resource"] = df["Resource"].astype(str).str.strip()

    with snowflake_session(conn) as c:
        result_df = routing_data.deleted_status_0020(
            c, df["Material"].unique().tolist(), df["Resource"].unique().tolist(), plant)

    result_df["Material"] = result_df["MATNR"].astype(str).str.lstrip("0")
    result_df["Resource"] = result_df["RESOURCE"].astype(str).str.strip()
    result_df["IS_DELETED"] = result_df["ROUTING_DELETED"].str.strip() == "X"
    result_df["MATERIAL_STATUS"] = result_df["MATERIAL_STATUS"].str.strip()

    merge_cols = result_df[["Material", "Resource", *RESULT_COLUMNS]].drop_duplicates()

    df = df.drop(columns=[c for c in RESULT_COLUMNS if c in df.columns])
    df = df.merge(merge_cols, on=["Material", "Resource"], how="left")
    df["IS_DELETED"] = df["IS_DELETED"].fillna(False)
    df["MATERIAL_STATUS"] = df["MATERIAL_STATUS"].fillna("")
    return df


def run(input_path, output_path=None, conn=None, plant=PLANT):
    df = check_routing_deleted_status(read_input(input_path), conn=conn, plant=plant)
    saved = write_output(df, output_path or input_path)
    print(f"Done. {len(df)} rows processed. Saved to: {saved}")
    return df
