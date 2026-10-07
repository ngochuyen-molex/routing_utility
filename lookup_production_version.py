#
import pandas as pd
import snowflake.connector
def lookup_production_version_text(excel_path: str, sheet_name: str = 'Sheet1'):
    # 1. Read Excel
    df_excel = pd.read_excel(excel_path, sheet_name=sheet_name)
    df_excel.columns = df_excel.columns.str.strip()

    df_excel.rename(columns={
        'group': 'routing_group',
        'group counter': 'group_counter',
    }, inplace=True)

    df_excel['material'] = df_excel['Material'].astype(str).str.strip()
    df_excel['routing_group'] = df_excel['routing_group'].astype(str).str.strip()
    df_excel['group_counter'] = df_excel['group_counter'].astype(str).str.strip()

    # Build unique (material, group, group_counter) pairs for the WHERE clause
    pairs = df_excel[['material', 'routing_group', 'group_counter']].drop_duplicates()

    # 2. Query Snowflake MKAL
    conn = snowflake.connector.connect(connection_name="default")

    # Build VALUES list for filtering
    values_list = ", ".join(
        f"(LPAD('{row.material}', 18, '0'), '{row.routing_group}', LPAD('{row.group_counter}', 2, '0'))"
        for _, row in pairs.iterrows()
    )

    sql = f"""
    SELECT
        LTRIM(MATNR, '0')  AS material,
        PLNNR               AS routing_group,
        LTRIM(ALNAL, '0')   AS group_counter,
        VERID               AS production_version,
        TEXT1               AS description
    FROM MLX_DATALAKE.MLX_SAP_ECC.MKAL
    WHERE (MATNR, PLNNR, LPAD(ALNAL, 2, '0')) IN ({values_list})
    and  WERKS = '1901'
    ORDER BY material, routing_group, group_counter
    """

    df_sf = pd.read_sql(sql, conn)
    df_sf.columns = df_sf.columns.str.strip().str.lower()
    conn.close()

    # Normalize keys
    df_sf['material'] = df_sf['material'].astype(str).str.strip()
    df_sf['routing_group'] = df_sf['routing_group'].astype(str).str.strip()
    df_sf['group_counter'] = df_sf['group_counter'].astype(str).str.strip()

    # 3. Merge Excel with Snowflake results
    merged = df_excel.merge(
        df_sf,
        on=['material', 'routing_group', 'group_counter'],
        how='left',
        indicator=True,
    )

    # 4. Report results
    found = merged[merged['_merge'] == 'both']
    not_found = merged[merged['_merge'] == 'left_only']

    print(f"Total Excel rows: {len(df_excel)}")
    print(f"Matched in MKAL:  {len(found)}")
    print(f"Not found:        {len(not_found)}")

    # 5. Save output — drop helper columns and Snowflake-only extras
    output_path = excel_path.replace('.xlsx', '_with_description.xlsx')
    cols_to_drop = ['_merge', 'material']
    cols_to_save = [c for c in merged.columns if c not in cols_to_drop]
    merged[cols_to_save].to_excel(output_path, index=False)
    print(f"\nOutput saved to: {output_path}")

    return merged


if __name__ == '__main__':
    lookup_production_version_text(
        r'C:\Users\nguyeb3\OneDrive - kochind.com\delete_routing.xlsx'
    )
