"""Efficiency (PLPO.USR04) / utilization (PLPO.USR05) at operation 0020, whole plant."""
from routing.core.config import PLANT
from routing.core.db import query

SQL_EFF_UTIL_0020 = """
    SELECT DISTINCT
        LTRIM(m.MATNR, '0') AS material,
        m.PLNNR AS routing_group,
        s.PLNAL AS group_counter,
        k.KTEXT AS routing_name,
        p.VORNR AS operation,
        p.LTXA1 AS operation_description,
        w.ARBPL AS work_center,
        p.USR04 AS efficiency,
        p.USR05 AS utilization
    FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL m
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLAS s ON m.PLNTY = s.PLNTY AND m.PLNNR = s.PLNNR AND m.PLNAL = s.PLNAL
        AND s.DW_SOFT_DELETE_FLAG = 0 AND TRIM(s.LOEKZ) = ''
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLKO k ON m.PLNTY = k.PLNTY AND m.PLNNR = k.PLNNR AND m.PLNAL = k.PLNAL
        AND k.DW_SOFT_DELETE_FLAG = 0 AND TRIM(k.LOEKZ) = ''
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO p ON s.PLNTY = p.PLNTY AND s.PLNNR = p.PLNNR AND s.PLNKN = p.PLNKN
        AND p.DW_SOFT_DELETE_FLAG = 0 AND TRIM(p.LOEKZ) = ''
    JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD w ON p.ARBID = w.OBJID AND w.OBJTY = 'A' AND w.DW_SOFT_DELETE_FLAG = 0
    JOIN MLX_DATALAKE.MLX_SAP_ECC.MARC marc ON m.MATNR = marc.MATNR AND m.WERKS = marc.WERKS
        AND marc.DW_SOFT_DELETE_FLAG = 0 AND TRIM(marc.LVORM) = ''
        AND marc.MMSTA != 'E3'
    WHERE m.WERKS = %s
        AND m.DW_SOFT_DELETE_FLAG = 0 AND TRIM(m.LOEKZ) = ''
        AND p.VORNR = '0020'
    ORDER BY material, s.PLNAL
"""


def eff_util_0020(conn, plant=PLANT):
    """All routings at the plant (no material filter, same as the original script)."""
    return query(conn, SQL_EFF_UTIL_0020, [plant])
