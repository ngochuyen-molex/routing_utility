"""Base quantity at operations 0020 / 0030 (PLPO.BMSCH)."""
from routing.core.clean import to_sap_matnr
from routing.core.config import PLANT
from routing.core.db import query_in_batches

SQL_BASE_QUANTITY = """
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
    WHERE pk.WERKS = %s
        AND pk.LOEKZ = ' '
        AND mp.PLNTY = 'N' -- show only visible routing in sap
        AND po.VORNR IN ('0020', '0030') -- should include 0040 for sorting case
        AND pk.DW_SOFT_DELETE_FLAG = 0
        AND mp.DW_SOFT_DELETE_FLAG = 0
        AND ps.DW_SOFT_DELETE_FLAG = 0 -- deleted sequences (e.g. old A505110D at GC 00)
        AND po.DW_SOFT_DELETE_FLAG = 0 -- deleted operations
        AND pk.DELKZ != 'X'
        AND mp.MATNR IN ({placeholders})
"""


def base_quantity_0020_0030(conn, materials, plant=PLANT):
    return query_in_batches(
        conn, SQL_BASE_QUANTITY, [to_sap_matnr(m) for m in materials], params_before=[plant],
        columns=["MATNR", "ROUTING_GROUP", "GROUP_COUNTER", "ROUTING_DESCRIPTION",
                 "OPERATION_NUMBER", "RESOURCE_NAME", "BASE_QUANTITY", "BASE_QUANTITY_UNIT"])
