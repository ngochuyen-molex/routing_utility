"""Routing queries (MAPL / PLKO / PLAS / PLPO / CRHD) at one plant.

This module holds every routing-related query, one SQL constant + function per
query (materials_at_plant, routings_with_resource, deleted_status_0020,
work_centers_0020, group_counters). They share the same MAPL->PLKO->PLAS->PLPO
join chain because that is the correct SAP path to a routing, but each selects
different columns/filters and is called from exactly one consumer (see the
"Used by" comment above each function). This is NOT duplication to collapse -
it is the data-access-layer pattern for this repo: one data/<domain>.py module
per SAP table domain, checks/pipelines import from here instead of writing SQL
inline, so a join/filter fix happens in one place.
"""
from routing.core.clean import to_sap_matnr
from routing.core.config import PLANT
from routing.core.db import query_in_batches

SQL_MATERIALS_AT_PLANT = """
    SELECT DISTINCT mp.MATNR
    FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL mp
    WHERE mp.WERKS = %s
        AND mp.PLNTY = 'N'
        AND mp.LOEKZ = ' '
        AND mp.DW_SOFT_DELETE_FLAG = 0
        AND mp.MATNR IN ({placeholders})
"""

SQL_ROUTINGS_WITH_RESOURCE = """
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
    WHERE pk.WERKS = %s
        AND pk.LOEKZ = ' '
        AND mp.LOEKZ = ' '
        AND pk.DW_SOFT_DELETE_FLAG = 0
        AND mp.DW_SOFT_DELETE_FLAG = 0
        AND mp.MATNR IN ({placeholders})
"""

SQL_DELETED_STATUS_0020 = """
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
    WHERE pk.WERKS = %s
        AND po.VORNR = '0020'
        AND mp.PLNTY = 'N' -- show only visible routing in sap
        AND mp.DW_SOFT_DELETE_FLAG = 0 -- routing assignments deleted from SAP and marked for cleanup in the data lake
        AND pk.DW_SOFT_DELETE_FLAG = 0 -- routing headers that were fully removed
        AND mp.LOEKZ != 'X' -- exclude material-to-routing links flagged as deleted in SAP
        AND ps.DW_SOFT_DELETE_FLAG = 0 -- deleted sequences (e.g. old A505110D at GC 00)
        AND po.DW_SOFT_DELETE_FLAG = 0 -- deleted operations
        AND mp.MATNR IN ({placeholders})
        AND cr.ARBPL IN ({resource_placeholders})
"""

SQL_WORK_CENTERS_0020 = """
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
    WHERE pk.WERKS = %s
        AND pk.LOEKZ = ' '
        AND mp.PLNTY = 'N'
        AND po.VORNR = '0020'
        AND pk.DW_SOFT_DELETE_FLAG = 0
        AND mp.DW_SOFT_DELETE_FLAG = 0
        AND ps.DW_SOFT_DELETE_FLAG = 0
        AND po.DW_SOFT_DELETE_FLAG = 0
        AND pk.DELKZ != 'X'
        AND mp.MATNR IN ({placeholders})
"""

# Used by opc/add_workflow and opc/compare_workflow (materials without leading zeros)
SQL_GROUP_COUNTERS = """
    SELECT DISTINCT
        LTRIM(m.MATNR, '0') AS MATERIAL,
        m.PLNAL AS GROUP_COUNTER
    FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL m
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLKO k
        ON m.PLNTY = k.PLNTY AND m.PLNNR = k.PLNNR AND m.PLNAL = k.PLNAL
        AND k.DW_SOFT_DELETE_FLAG = 0 AND TRIM(k.LOEKZ) = ''
    JOIN MLX_DATALAKE.MLX_SAP_ECC.MARC marc
        ON m.MATNR = marc.MATNR AND m.WERKS = marc.WERKS
        AND marc.DW_SOFT_DELETE_FLAG = 0 AND TRIM(marc.LVORM) = ''
        AND marc.MMSTA != 'E3'
    WHERE m.WERKS = %s
        AND m.PLNTY = 'N'
        AND m.DW_SOFT_DELETE_FLAG = 0 AND TRIM(m.LOEKZ) = ''
        AND LTRIM(m.MATNR, '0') IN ({placeholders})
"""


def _matnrs(materials):
    return [to_sap_matnr(m) for m in materials]


def materials_at_plant(conn, materials, plant=PLANT):
    """Materials with a standard routing at the plant. Columns: MATNR (18 chars).
    Used by: checks/routing_condition.py"""
    return query_in_batches(conn, SQL_MATERIALS_AT_PLANT, _matnrs(materials),
                            params_before=[plant], columns=["MATNR"])


def routings_with_resource(conn, materials, plant=PLANT):
    """All active routings + their work centers.
    Columns: MATNR, RESOURCE, ROUTING_DESCRIPTION, ROUTING_GROUP, GROUP_COUNTER.
    Used by: checks/routing_condition.py"""
    return query_in_batches(
        conn, SQL_ROUTINGS_WITH_RESOURCE, _matnrs(materials), params_before=[plant],
        columns=["MATNR", "RESOURCE", "ROUTING_DESCRIPTION", "ROUTING_GROUP", "GROUP_COUNTER"])


def deleted_status_0020(conn, materials, resources, plant=PLANT):
    """Routing delete flag + material status at operation 0020 for material/resource pairs.
    Used by: checks/delete_status.py"""
    resources = list(dict.fromkeys(resources))
    sql = SQL_DELETED_STATUS_0020.replace(
        "{resource_placeholders}", ", ".join(["%s"] * len(resources)))
    return query_in_batches(
        conn, sql, _matnrs(materials), params_before=[plant], params_after=resources,
        columns=["MATNR", "RESOURCE", "OPERATION", "ROUTING_DELETED", "ROUTING_GROUP",
                 "GROUP_COUNTER", "OPERATION_DELETED", "MATERIAL_STATUS"])


def work_centers_0020(conn, materials, plant=PLANT):
    """Work center + unit conversion at operation 0020 of every active routing.
    Used by: checks/routings_by_tool.py"""
    return query_in_batches(
        conn, SQL_WORK_CENTERS_0020, _matnrs(materials), params_before=[plant],
        columns=["MATERIAL", "WORK_CENTER", "ROUTING_DESCRIPTION", "ROUTING_GROUP",
                 "GROUP_COUNTER", "CONV_NUMERATOR", "CONV_DENOMINATOR"])


def group_counters(conn, materials, plant=PLANT):
    """Group counters per material (materials without leading zeros).
    Columns: MATERIAL, GROUP_COUNTER.
    Used by: opc/add_workflow.py, opc/compare_workflow.py"""
    return query_in_batches(conn, SQL_GROUP_COUNTERS, materials, params_before=[plant],
                            columns=["MATERIAL", "GROUP_COUNTER"])
