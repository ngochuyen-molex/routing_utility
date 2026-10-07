import pandas as pd
import snowflake.connector


def count_production_versions(excel_path: str, sheet_name: str = 'Sheet1'):
    # 1. Read Excel and extract unique material numbers
    df_excel = pd.read_excel(excel_path, sheet_name=sheet_name)
    df_excel.columns = df_excel.columns.str.strip()

    df_excel['material'] = df_excel['Material'].astype(str).str.strip()
    materials = df_excel['material'].unique().tolist()

    # 2. Query Snowflake MKAL for production version counts
    conn = snowflake.connector.connect(connection_name="default")
    cur = conn.cursor()

    # Pre-pad in Python so IN list contains plain string constants (avoids 50-item LPAD limit)
    padded = [m.zfill(18) for m in materials]

    # Query in batches of 500 to stay within Snowflake limits
    batch_size = 500
    results = []
    for i in range(0, len(padded), batch_size):
        batch = padded[i:i + batch_size]
        values_list = ", ".join(f"'{v}'" for v in batch)
        sql = f"""
        SELECT
            LTRIM(MATNR, '0')      AS material,
            COUNT(DISTINCT VERID)   AS production_version_count
        FROM MLX_DATALAKE.MLX_SAP_ECC.MKAL
        WHERE MATNR IN ({values_list})
            AND WERKS = '1901'
        GROUP BY MATNR
        """
        cur.execute(sql)
        results.extend(cur.fetchall())

    df_sf = pd.DataFrame(results, columns=['material', 'production_version_count'])
    cur.close()
    conn.close()

    df_sf['material'] = df_sf['material'].astype(str).str.strip()

    # 3. Merge back to Excel
    merged = df_excel.merge(df_sf, on='material', how='left')
    merged['production_version_count'] = merged['production_version_count'].fillna(0).astype(int)

    # 4. Report
    print(f"Total Excel rows:           {len(df_excel)}")
    print(f"Unique materials:           {len(materials)}")
    print(f"Materials with versions:    {merged[merged['production_version_count'] > 0]['material'].nunique()}")
    print(f"Materials without versions: {merged[merged['production_version_count'] == 0]['material'].nunique()}")

    # 5. Save output
    output_path = excel_path.replace('.xlsx', '_version_counts.xlsx')
    cols_to_save = [c for c in merged.columns if c != 'material']
    merged[cols_to_save].to_excel(output_path, index=False)
    print(f"\nOutput saved to: {output_path}")

    return merged


if __name__ == '__main__':
    excel_path = input("Enter the Excel file path: ").strip().strip('"')
    count_production_versions(excel_path)