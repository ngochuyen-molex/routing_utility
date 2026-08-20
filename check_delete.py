import pandas as pd
import snowflake.connector


def check_routing_deleted_status(file_path: str, output_path: str = None):
    """Check if routing at operation 0020 is deleted for materials in the Excel file."""
    if output_path is None:
        output_path = file_path

    df = pd.read_excel(file_path)
    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df["Material"].astype(str).tolist()
    )

    sql = f"""
        SELECT DISTINCT
            mp.MATNR,
            cr.ARBPL AS RESOURCE,
            po.VORNR AS OPERATION,
            pk.LOEKZ AS ROUTING_DELETED,
            po.LOEKZ AS OPERATION_DELETED
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
        WHERE pk.WERKS = '1901'
            AND po.VORNR = '0020'
            AND mp.MATNR IN ({matnr_list})
    """

    result_df = pd.read_sql(sql, conn)
    conn.close()

    result_df["Material"] = result_df["MATNR"].astype(str).str.lstrip("0")
    result_df["IS_DELETED"] = (
        (result_df["ROUTING_DELETED"].str.strip() != "")
        | (result_df["OPERATION_DELETED"].str.strip() != "")
    )

    df["Material"] = df["Material"].astype(str)

    merge_cols = result_df[["Material", "RESOURCE", "IS_DELETED"]].drop_duplicates()

    for col in ["RESOURCE", "IS_DELETED"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    df = df.merge(merge_cols, on="Material", how="left")
    df["IS_DELETED"] = df["IS_DELETED"].fillna(False)

    df.to_excel(output_path, index=False)
    print(f"Done. {len(df)} rows processed. Saved to: {output_path}")


if __name__ == "__main__":
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    check_routing_deleted_status(path)