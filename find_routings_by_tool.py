import pandas as pd
import snowflake.connector


def find_work_centers(file_path: str, output_path: str = None):
    """For each Material+Tool pair in Excel, find the work center at operation 0020
    and update the Resource column."""
    if output_path is None:
        output_path = file_path.replace('.xlsx', '_with_resource_idealcycletime.xlsx')

    df = pd.read_excel(file_path)
    df['Material'] = df['Material'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)

    # Find the Tool column
    tool_col = None
    for col in df.columns:
        if 'tool' in str(col).lower():
            tool_col = col
            break
    if tool_col is None:
        raise ValueError(f"No Tool column found. Columns: {df.columns.tolist()}")

    # Find the Resource column
    res_col = None
    for col in df.columns:
        if 'resource' in str(col).lower():
            res_col = col
            break
    if res_col is None:
        res_col = 'Resource'
        df[res_col] = ''

    df['_Tool'] = df[tool_col].fillna('').astype(str).str.strip()

    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df['Material'].unique()
    )

    sql = f"""
        SELECT DISTINCT
            LTRIM(mp.MATNR, '0') AS MATERIAL,
            cr.ARBPL AS WORK_CENTER,
            pk.KTEXT AS ROUTING_DESCRIPTION,
            pk.PLNNR AS ROUTING_GROUP,
            pk.PLNAL AS GROUP_COUNTER,
            po.UMREZ AS CONV_NUMERATOR,
            po.UMREN AS CONV_DENOMINATOR
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
            AND ps.LOEKZ = ' '
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO po
            ON ps.MANDT = po.MANDT
            AND ps.PLNTY = po.PLNTY
            AND ps.PLNNR = po.PLNNR
            AND ps.PLNKN = po.PLNKN
        JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD cr
            ON po.ARBID = cr.OBJID
            AND po.MANDT = cr.MANDT
        WHERE pk.WERKS = '1901'
            AND pk.LOEKZ = ' '
            AND mp.PLNTY = 'N'
            AND po.VORNR = '0020'
            AND pk.DW_SOFT_DELETE_FLAG = 0
            AND mp.DW_SOFT_DELETE_FLAG = 0
            AND ps.DW_SOFT_DELETE_FLAG = 0
            AND po.DW_SOFT_DELETE_FLAG = 0
            AND pk.DELKZ != 'X'
            AND mp.MATNR IN ({matnr_list})
    """

    sf_df = pd.read_sql(sql, conn)
    conn.close()

    sf_df['ROUTING_DESCRIPTION'] = sf_df['ROUTING_DESCRIPTION'].fillna('').astype(str).str.strip()
    sf_df['WORK_CENTER'] = sf_df['WORK_CENTER'].astype(str).str.strip()

    # Find the Tool Cavity column
    cavity_col = None
    for col in df.columns:
        if 'cavity' in str(col).lower():
            cavity_col = col
            break
    if cavity_col is None:
        cavity_col = 'Tool Cavity'
        df[cavity_col] = ''

    # For each Excel row, find work center(s) at op 0020 where tool is in description
    work_centers = []
    match_info = []
    conv_numerators = []

    for _, row in df.iterrows():
        mat = row['Material']
        tool = row['_Tool']

        # Get all op 0020 routings for this material
        mat_routings = sf_df[sf_df['MATERIAL'] == mat]

        # Filter by tool in description
        if tool:
            matched = mat_routings[mat_routings['ROUTING_DESCRIPTION'].str.contains(tool, na=False)]
            # Exclude rows where work center IS the tool value
            matched = matched[matched['WORK_CENTER'] != tool]
        else:
            matched = mat_routings

        if matched.empty:
            work_centers.append('')
            match_info.append('No routing found')
            conv_numerators.append('')
        else:
            unique_wcs = matched.drop_duplicates(subset=['WORK_CENTER'])
            if len(unique_wcs) == 1:
                work_centers.append(unique_wcs.iloc[0]['WORK_CENTER'])
                match_info.append('Found')
                conv_numerators.append(unique_wcs.iloc[0]['CONV_NUMERATOR'])
            else:
                work_centers.append(', '.join(sorted(unique_wcs['WORK_CENTER'])))
                match_info.append(f'Multiple ({len(unique_wcs)})')
                conv_numerators.append(', '.join(
                    str(int(r['CONV_NUMERATOR'])) if pd.notna(r['CONV_NUMERATOR']) else ''
                    for _, r in unique_wcs.sort_values('WORK_CENTER').iterrows()
                ))

    df[res_col] = work_centers
    df[cavity_col] = conv_numerators
    df['MATCH_STATUS'] = match_info

    # Sheet 2: Expand rows so each work center gets its own row
    expanded_rows = []
    for _, row in df.iterrows():
        wc_val = row[res_col]
        cav_val = str(row[cavity_col]) if row[cavity_col] else ''
        if wc_val and ', ' in str(wc_val):
            wc_list = str(wc_val).split(', ')
            cav_list = cav_val.split(', ') if cav_val else [''] * len(wc_list)
            for wc, cav in zip(wc_list, cav_list):
                new_row = row.copy()
                new_row[res_col] = wc
                new_row[cavity_col] = cav
                new_row['MATCH_STATUS'] = 'Found'
                expanded_rows.append(new_row)
        else:
            expanded_rows.append(row)

    expanded_df = pd.DataFrame(expanded_rows)

    df.drop(columns=['_Tool'], inplace=True)
    expanded_df.drop(columns=['_Tool'], inplace=True, errors='ignore')

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Summary', index=False)
        expanded_df.to_excel(writer, sheet_name='Sheet1', index=False)

    found = sum(1 for m in match_info if m == 'Found')
    multiple = sum(1 for m in match_info if m.startswith('Multiple'))
    not_found = sum(1 for m in match_info if m == 'No routing found')

    print(f"Done. {len(df)} rows processed. Saved to: {output_path}")
    print(f"  Single work center found: {found}")
    print(f"  Multiple work centers: {multiple}")
    print(f"  No routing found: {not_found}")
    print(f"  Expanded rows (Sheet 2): {len(expanded_df)}")


if __name__ == '__main__':
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    find_work_centers(path)
