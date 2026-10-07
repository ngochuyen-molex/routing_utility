import pandas as pd
import snowflake.connector
# can fix lai tai sao k hien tren check_0030 -> solve capacity 0030
# voi with sorting -> capacity from snowflake 0040
# ATTENTION: for cases routing not found-> check delete status again
def check_routing_capacity(excel_path: str, output_path: str = None, sheet_name: str = 'Sheet1'):
    if output_path is None:
        output_path = excel_path

    # 1. Read Excel
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    df['Material'] = df['Material'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    df['Resource'] = df['Resource'].astype(str).str.strip()
    df['group counter'] = pd.to_numeric(df['group counter'], errors='coerce').astype('Int64').astype(str)

    for col in ['Tool', 'group', 'group counter']:
        if col not in df.columns:
            df[col] = ''
        else:
            df[col] = df[col].fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)

    df['Capacity'] = pd.to_numeric(df['Capacity'], errors='coerce')

    # 2. Query Snowflake for base quantities at 0020 and 0030
    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df['Material'].unique()
    )

    sql = f"""
        SELECT DISTINCT
            mp.MATNR,
            pk.PLNNR AS ROUTING_GROUP,
            pk.PLNAL AS GROUP_COUNTER,
            pk.KTEXT AS ROUTING_DESCRIPTION,
            po.VORNR AS OPERATION_NUMBER,
            cr.ARBPL AS RESOURCE_NAME,
            po.BMSCH AS BASE_QUANTITY,
            po.MEINH AS BASE_QUANTITY_UNIT
        FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL mp
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLKO pk
            ON mp.MANDT = pk.MANDT AND mp.PLNTY = pk.PLNTY
            AND mp.PLNNR = pk.PLNNR AND mp.PLNAL = pk.PLNAL
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLAS ps
            ON pk.MANDT = ps.MANDT AND pk.PLNTY = ps.PLNTY
            AND pk.PLNNR = ps.PLNNR AND pk.PLNAL = ps.PLNAL
            AND ps.LOEKZ = ' '
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO po
            ON ps.MANDT = po.MANDT AND ps.PLNTY = po.PLNTY
            AND ps.PLNNR = po.PLNNR AND ps.PLNKN = po.PLNKN
        LEFT JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD cr
            ON po.ARBID = cr.OBJID AND po.MANDT = cr.MANDT
        WHERE pk.WERKS = '1901'
            AND pk.LOEKZ = ' '
            AND mp.PLNTY = 'N' -- show only visible routing in sap
            AND po.VORNR IN ('0020', '0030') --should include 0040 for sorting case
            AND pk.DW_SOFT_DELETE_FLAG = 0
            AND mp.DW_SOFT_DELETE_FLAG = 0
            AND ps.DW_SOFT_DELETE_FLAG = 0 --Deleted sequences (e.g. old A505110D at GC 00)
            and po.DW_SOFT_DELETE_FLAG = 0 --Deleted operations
            and pk.DELKZ != 'X'
            AND mp.MATNR IN ({matnr_list})
    """

    sf_df = pd.read_sql(sql, conn)
    conn.close()

    # 3. Clean Snowflake results
    sf_df['Material'] = sf_df['MATNR'].str.lstrip('0')
    sf_df['ROUTING_GROUP'] = sf_df['ROUTING_GROUP'].astype(str).str.strip()
    sf_df['GROUP_COUNTER'] = pd.to_numeric(sf_df['GROUP_COUNTER'], errors='coerce').astype('Int64').astype(str)
    sf_df['RESOURCE_NAME'] = sf_df['RESOURCE_NAME'].astype(str).str.strip()
    sf_df['ROUTING_DESCRIPTION'] = sf_df['ROUTING_DESCRIPTION'].fillna('').astype(str).str.strip()
    sf_df['BASE_QUANTITY'] = pd.to_numeric(sf_df['BASE_QUANTITY'], errors='coerce')

    # 4. Match and compare
    bq_0020 = []
    bq_0030 = []
    match_0020 = []
    match_0030 = []
    matched_groups = []
    matched_counters = []
    matched_descs = []
    match_methods = []

    for _, row in df.iterrows():
        mat = row['Material']
        grp = row.get('group', '')
        gc = row.get('group counter', '')
        res = row['Resource']
        tool = row.get('Tool', '')
        capacity = row['Capacity']
        capacity_30 = row['Capacity']*row['Tool Cavity']

        # Pick matching strategy
        if grp and gc:
            matches = sf_df[
                (sf_df['Material'] == mat) &
                (sf_df['ROUTING_GROUP'] == grp) &
                (sf_df['GROUP_COUNTER'] == gc)
            ]
            method = 'Group+Counter'
        else:
            matches = sf_df[
                (sf_df['Material'] == mat) &
                (sf_df['RESOURCE_NAME'] == res)
            ]
            if tool:
                matches = matches[matches['ROUTING_DESCRIPTION'].str.contains(tool, na=False)]
                method = 'Resource+Tool'
            else:
                method = 'Resource'

        # Get base quantity at 0020
        op20 = matches[matches['OPERATION_NUMBER'] == '0020']
        qty_20 = op20.iloc[0]['BASE_QUANTITY'] if not op20.empty else None

        # Get base quantity at 0030
        op30 = matches[matches['OPERATION_NUMBER'] == '0030']
        qty_30 = op30.iloc[0]['BASE_QUANTITY'] if not op30.empty else None

        bq_0020.append(qty_20)
        bq_0030.append(qty_30)

        # Compare against Excel Capacity
        if pd.notna(capacity) and qty_20 is not None:
            match_0020.append('Match' if abs(qty_20 - capacity) < 0.001 else 'Mismatch')
        elif qty_20 is None:
            match_0020.append('No routing found')
        else:
            match_0020.append('Missing capacity')

        if pd.notna(capacity_30) and qty_30 is not None:
            match_0030.append('Match' if abs(qty_30 - capacity_30) < 0.001 else 'Mismatch')
        elif qty_30 is None:
            match_0030.append('No routing found')
        else:
            match_0030.append('Missing capacity')

        # Store matched routing info
        if not matches.empty:
            matched_groups.append(matches.iloc[0]['ROUTING_GROUP'])
            matched_counters.append(matches.iloc[0]['GROUP_COUNTER'])
            matched_descs.append(matches.iloc[0]['ROUTING_DESCRIPTION'])
        else:
            matched_groups.append('')
            matched_counters.append('')
            matched_descs.append('')

        match_methods.append(method)

    # 5. Build output
    df['MATCH_METHOD'] = match_methods
    df['ROUTING_GROUP'] = matched_groups
    df['ROUTING_GROUP_COUNTER'] = matched_counters
    df['ROUTING_DESCRIPTION'] = matched_descs
    df['BASE_QTY_0020'] = bq_0020
    df['BASE_QTY_0030'] = bq_0030
    df['CHECK_0020'] = match_0020
    df['CHECK_0030'] = match_0030

    df.to_excel(output_path, index=False)

    mismatch_count = ((df['CHECK_0020'] == 'Mismatch') | (df['CHECK_0030'] == 'Mismatch')).sum()
    no_routing = ((df['CHECK_0020'] == 'No routing found') & (df['CHECK_0030'] == 'No routing found')).sum()
    all_match = ((df['CHECK_0020'] == 'Match') & (df['CHECK_0030'] == 'Match')).sum()

    print(f"Done. {len(df)} rows processed. Saved to: {output_path}")
    print(f"  Both match: {all_match}")
    print(f"  Mismatch (0020 or 0030): {mismatch_count}")
    print(f"  No routing found: {no_routing}")


if __name__ == '__main__':
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    check_routing_capacity(path)