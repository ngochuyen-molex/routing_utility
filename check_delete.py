import pandas as pd
import snowflake.connector
# list even duplicate routings(same material+resource) -> increase the size of rows

def check_routing_deleted_status(file_path: str, output_path: str = None):
    """Check if routing at operation 0020 is deleted for each material+resource pair."""
    if output_path is None:
        output_path = file_path

    df = pd.read_excel(file_path)

    df["Material"] = df["Material"].astype(str).str.strip()
    df["Resource"] = df["Resource"].astype(str).str.strip()

    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df["Material"].unique())
    resource_list = ", ".join(
        f"'{val}'" for val in df["Resource"].unique())

    sql = f"""
        SELECT DISTINCT
            mp.MATNR,
            cr.ARBPL AS RESOURCE,
            po.VORNR AS OPERATION,
            pk.DELKZ AS ROUTING_DELETED,
            pk.PLNNR AS ROUTING_GROUP,
            pk.PLNAL AS GROUP_COUNTER,
            po.LOEKZ AS OPERATION_DELETED,
            mc.MMSTA AS MATERIAL_STATUS
        FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL mp
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLKO pk
            ON mp.MANDT = pk.MANDT
            AND mp.PLNTY = pk.PLNTY
            AND mp.PLNNR = pk.PLNNR
            AND mp.PLNAL = pk.PLNAL
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLAS ps
            ON pk.MANDT = ps.MANDT
            AND pk.PLNTY = ps.PLNTY
            AND pk.PLNNR = ps.PLNNR
            AND pk.PLNAL = ps.PLNAL
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO po
            ON ps.MANDT = po.MANDT
            AND ps.PLNTY = po.PLNTY
            AND ps.PLNNR = po.PLNNR
            AND ps.PLNKN = po.PLNKN
        JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD cr
            ON po.ARBID = cr.OBJID
            AND po.MANDT = cr.MANDT
        JOIN MLX_DATALAKE.MLX_SAP_ECC.MARC mc
            ON mp.MATNR = mc.MATNR
            AND pk.WERKS = mc.WERKS
        WHERE pk.WERKS = '1901'
            AND po.VORNR = '0020'
            AND mp.PLNTY = 'N' -- show only visible routing in sap
            AND mp.DW_SOFT_DELETE_FLAG = 0 --Routing assignments deleted from SAP and marked for cleanup in the data lake
            AND pk.DW_SOFT_DELETE_FLAG = 0 --Routing headers that were fully removed
            AND mp.LOEKZ != 'X' -- exclude Material-to-routing links flagged as deleted in SAP ->Non-deleted MAPL assignments
            AND ps.DW_SOFT_DELETE_FLAG = 0 --Deleted sequences (e.g. old A505110D at GC 00)
            and po.DW_SOFT_DELETE_FLAG = 0 --Deleted operations
            AND mp.MATNR IN ({matnr_list})
            AND cr.ARBPL IN ({resource_list})
    """

    result_df = pd.read_sql(sql, conn)
    conn.close()

    result_df["Material"] = result_df["MATNR"].astype(str).str.lstrip("0")
    result_df["Resource"] = result_df["RESOURCE"].astype(str).str.strip()

    result_df["IS_DELETED"] = (
        (result_df["ROUTING_DELETED"].str.strip() == "X")
    )

    result_df["MATERIAL_STATUS"] = result_df["MATERIAL_STATUS"].str.strip()

    merge_cols = result_df[
            ["Material", "Resource", "ROUTING_GROUP", "GROUP_COUNTER", "IS_DELETED", "MATERIAL_STATUS"]
        ].drop_duplicates()

    for col in ["ROUTING_GROUP", "GROUP_COUNTER", "IS_DELETED", "MATERIAL_STATUS"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    df = df.merge(merge_cols, on=["Material", "Resource"], how="left")
    df["IS_DELETED"] = df["IS_DELETED"].fillna(False)
    df["MATERIAL_STATUS"] = df["MATERIAL_STATUS"].fillna("")

    df.to_excel(output_path, index=False)
    print(f"Done. {len(df)} rows processed. Saved to: {output_path}")


if __name__ == "__main__":
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    check_routing_deleted_status(path)