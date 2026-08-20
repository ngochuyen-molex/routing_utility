import pandas as pd
import snowflake.connector

def check_alt_bom_count(file_path: str, output_path: str = None):
    """Check active alt BOM count for materials in the given Excel file."""
    if output_path is None:
        output_path = file_path  # overwrite in place

    df = pd.read_excel(file_path)
    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df['Material'].astype(str).tolist()
    )

    sql = f"""
        SELECT m.MATNR, COUNT(DISTINCT m.STLAL) AS ALT_BOM_COUNT
        FROM MLX_DATALAKE.MLX_SAP_ECC.MAST m
        JOIN MLX_DATALAKE.MLX_SAP_ECC.STKO s
            ON m.STLNR = s.STLNR AND m.STLAL = s.STLAL
        WHERE m.STLAN = '1' AND m.WERKS = '1901' AND s.STLST = '01'
            AND m.MATNR IN ({matnr_list})
        GROUP BY m.MATNR
    """

    bom_df = pd.read_sql(sql, conn)
    conn.close()

    bom_df['Material'] = bom_df['MATNR'].astype(str).str.lstrip('0')
    df['Material'] = df['Material'].astype(str)

    if 'ALT_BOM_COUNT' in df.columns:
        df = df.drop(columns=['ALT_BOM_COUNT'])

    df = df.merge(bom_df[['Material', 'ALT_BOM_COUNT']], on='Material', how='left')
    df['ALT_BOM_COUNT'] = df['ALT_BOM_COUNT'].fillna(0).astype(int)

    df.to_excel(output_path, index=False)
    print(f"Done. {len(df)} materials processed. Saved to: {output_path}")


if __name__ == '__main__':
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    check_alt_bom_count(path)