import pandas as pd
import snowflake.connector

def compare_routing_eff_util(excel_path: str, sheet_name: str = 'Sheet1'):
    # 1. Query Snowflake
    conn = snowflake.connector.connect(connection_name="default")

    sql = """
    SELECT DISTINCT
        LTRIM(m.MATNR, '0') AS material,
        m.PLNNR AS routing_group,
        s.PLNAL AS group_counter,
        k.KTEXT AS routing_name,
        p.VORNR AS operation,
        p.USR04 AS efficiency,
        p.USR05 AS utilization
    FROM MAPL m
    JOIN PLAS s ON m.PLNTY = s.PLNTY AND m.PLNNR = s.PLNNR AND m.PLNAL = s.PLNAL
        AND s.DW_SOFT_DELETE_FLAG = 0 AND TRIM(s.LOEKZ) = ''
    JOIN PLKO k ON m.PLNTY = k.PLNTY AND m.PLNNR = k.PLNNR AND m.PLNAL = k.PLNAL
        AND k.DW_SOFT_DELETE_FLAG = 0 AND TRIM(k.LOEKZ) = ''
    JOIN PLPO p ON s.PLNTY = p.PLNTY AND s.PLNNR = p.PLNNR AND s.PLNKN = p.PLNKN
        AND p.DW_SOFT_DELETE_FLAG = 0 AND TRIM(p.LOEKZ) = ''
    JOIN CRHD w ON p.ARBID = w.OBJID AND w.OBJTY = 'A' AND w.DW_SOFT_DELETE_FLAG = 0
    JOIN MARC marc ON m.MATNR = marc.MATNR AND m.WERKS = marc.WERKS
        AND marc.DW_SOFT_DELETE_FLAG = 0 AND TRIM(marc.LVORM) = ''
        AND marc.MMSTA != 'E3'
    WHERE m.WERKS = '1901'
        AND m.DW_SOFT_DELETE_FLAG = 0 AND TRIM(m.LOEKZ) = ''
        AND p.VORNR = '0020'
    ORDER BY material, s.PLNAL
    """

    df_sf = pd.read_sql(sql, conn)
    conn.close()

    # 2. Read Excel
    df_excel = pd.read_excel(excel_path, sheet_name=sheet_name)

    # Adjust these column names to match your Excel headers exactly
    df_excel.rename(columns={
        'Material': 'material',
        'Group': 'group_counter',       # adjust if needed
        'Group Counter': 'group_counter',
        'Efficiency': 'excel_eff',
        'Utilization': 'excel_util',
        'Resource and Tool': 'routing_name_excel'
    }, inplace=True)

    # Normalize keys for matching
    df_sf['material'] = df_sf['material'].astype(str).str.strip()
    df_excel['material'] = df_excel['material'].astype(str).str.strip()
    df_sf['group_counter'] = df_sf['group_counter'].astype(str).str.strip()
    df_excel['group_counter'] = df_excel['group_counter'].astype(str).str.strip()

    # 3. Merge on material + group_counter
    merged = df_sf.merge(df_excel, on=['material', 'group_counter'], how='outer', indicator=True)

    # 4. Compare
    merged['eff_match'] = merged['efficiency'] == merged['excel_eff']
    merged['util_match'] = merged['utilization'] == merged['excel_util']

    mismatches = merged[(merged['eff_match'] == False) | (merged['util_match'] == False)]

    print(f"Total rows compared: {len(merged)}")
    print(f"Mismatches found: {len(mismatches)}\n")

    if not mismatches.empty:
        print("=== MISMATCHES ===")
        print(mismatches[['material', 'group_counter', 'routing_name',
                            'efficiency', 'excel_eff', 'utilization', 'excel_util']].to_string(index=False))

    # Also show rows only in one source
    only_sf = merged[merged['_merge'] == 'left_only']
    only_excel = merged[merged['_merge'] == 'right_only']
    if not only_sf.empty:
        print(f"\n=== In Snowflake only ({len(only_sf)} rows) ===")
        print(only_sf[['material', 'group_counter', 'routing_name']].to_string(index=False))
    if not only_excel.empty:
        print(f"\n=== In Excel only ({len(only_excel)} rows) ===")
        print(only_excel[['material', 'group_counter']].to_string(index=False))

    return merged


if __name__ == '__main__':
    compare_routing_eff_util(r'C:\path\to\your\file.xlsx')