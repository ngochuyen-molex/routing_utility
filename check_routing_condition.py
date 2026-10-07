import pandas as pd
import snowflake.connector


def check_routing_exists(file_path: str, output_path: str = None):
    """Check if routing already exists for material/resource pairs in the given Excel file.
    Excel columns: Material, Resource, Tool (optional), WorkCenter (optional)
    """
    if output_path is None:
        output_path = file_path

    df = pd.read_excel(file_path)
    df['Material'] = df['Material'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    df['Resource'] = df['Resource'].astype(str).str.strip()

    # Handle optional columns - fill blanks
    for col in ['Tool', 'WorkCenter', 'Sorting/ Lubricant']:
        if col not in df.columns:
            df[col] = ''
        else:
            df[col] = df[col].fillna('').astype(str).str.strip()

    conn = snowflake.connector.connect(connection_name="default")

    matnr_list = ", ".join(
        f"'{str(val).zfill(18)}'" for val in df['Material'].unique()
    )

    # Query 1: Check which materials are assigned to plant 1901
    sql_plant = f"""
        SELECT DISTINCT mp.MATNR
        FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL mp
        WHERE mp.WERKS = '1901'
            AND mp.PLNTY = 'N'
            AND mp.DW_SOFT_DELETE_FLAG = 0
            AND mp.MATNR IN ({matnr_list})
    """

    # Query 2: Get all existing routings with resources at plant 1901
    sql_routing = f"""
        SELECT DISTINCT
            mp.MATNR,
            cr.ARBPL AS RESOURCE,
            pk.KTEXT AS ROUTING_DESCRIPTION,
            pk.PLNNR AS ROUTING_GROUP,
            pk.PLNAL AS GROUP_COUNTER
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
            AND pk.DW_SOFT_DELETE_FLAG = 0
            AND mp.DW_SOFT_DELETE_FLAG = 0
            AND mp.MATNR IN ({matnr_list})
    """

    plant_df = pd.read_sql(sql_plant, conn)
    routing_df = pd.read_sql(sql_routing, conn)
    conn.close()

    # JUST KINDA STRIP THE MATERIAL NUMBER EXTRA 0 FROM SAP 
    plant_df['Material'] = plant_df['MATNR'].str.lstrip('0')
    routing_df['Material'] = routing_df['MATNR'].str.lstrip('0')

    materials_at_plant = set(plant_df['Material'])

    skip_flags = []
    routing_descriptions = []
    routing_groups = []
    group_counters = []

    for _, row in df.iterrows():
        mat = row['Material']
        res = row['Resource']

        # Check 1: Is material at plant 1901?
        if mat not in materials_at_plant:
            skip_flags.append(2)
            routing_descriptions.append('')
            routing_groups.append('')
            group_counters.append('')
            continue

        # Check 2: Does routing with this resource already exist?
        if res:
            match = routing_df[
                (routing_df['Material'] == mat) &
                (routing_df['RESOURCE'] == res)
            ]
        else:
            match = pd.DataFrame()

        if not match.empty:
            desc = str(match.iloc[0]['ROUTING_DESCRIPTION'])

            tool = row['Tool']
            wc = row['WorkCenter']
            sorting = row['Sorting/ Lubricant']

            tool_ok = (not tool) or (tool in desc)
            wc_ok = (not wc) or (wc in desc)
            sorting_ok = (not sorting) or (sorting in desc)

            if tool_ok and wc_ok and sorting_ok:
                skip_flags.append(1)
                routing_descriptions.append(desc)
                routing_groups.append(match.iloc[0]['ROUTING_GROUP'])
                group_counters.append(match.iloc[0]['GROUP_COUNTER'])
            else:
                skip_flags.append(0)
                routing_descriptions.append('')
                routing_groups.append('')
                group_counters.append('')
        else:
            skip_flags.append(0)
            routing_descriptions.append('')
            routing_groups.append('')
            group_counters.append('')

    df['group'] = routing_groups
    df['group counter'] = group_counters

    df['SKIP'] = skip_flags
    df['SKIP_REASON'] = df['SKIP'].map({
        0: 'Safe to add',
        1: 'Routing already exists',
        2: 'Material not at plant'
    })
    df['ROUTING_DESCRIPTION'] = routing_descriptions

    df.to_excel(output_path, index=False)

    print(f"Done. {len(df)} rows processed. Saved to: {output_path}")
    print(f"  Safe to add (0): {(df['SKIP'] == 0).sum()}")
    print(f"  Routing exists (1): {(df['SKIP'] == 1).sum()}")
    print(f"  Not at plant (2): {(df['SKIP'] == 2).sum()}")


if __name__ == '__main__':
    path = input("Enter Excel file path (or drag & drop): ").strip().strip('"')
    check_routing_exists(path)


    # def matches_description(row, desc):
    #     """Check if resource/tool/workcenter from Excel row exist in routing description."""
    #     if not desc:
    #         return False
    #     parts_to_check = [row['Resource']]
    #     if row.get('Tool'):
    #         parts_to_check.append(row['Tool'])
    #     if row.get('WorkCenter'):
    #         parts_to_check.append(row['WorkCenter'])
    #     return all(part in desc for part in parts_to_check if part)