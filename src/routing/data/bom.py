"""BOM queries (MAST / STKO)."""
from routing.core.clean import to_sap_matnr
from routing.core.config import PLANT
from routing.core.db import query_in_batches

SQL_ALT_BOM_COUNT = """
    SELECT m.MATNR, COUNT(DISTINCT m.STLAL) AS ALT_BOM_COUNT
    FROM MLX_DATALAKE.MLX_SAP_ECC.MAST m
    JOIN MLX_DATALAKE.MLX_SAP_ECC.STKO s
        ON m.STLNR = s.STLNR AND m.STLAL = s.STLAL
    WHERE m.STLAN = '1' AND m.WERKS = %s AND s.STLST = '01'
        AND m.MATNR IN ({placeholders})
    GROUP BY m.MATNR
"""


def alt_bom_count(conn, materials, plant=PLANT):
    """Active alternative BOMs (usage 1, status 01) per material. Columns: MATNR, ALT_BOM_COUNT."""
    return query_in_batches(conn, SQL_ALT_BOM_COUNT, [to_sap_matnr(m) for m in materials],
                            params_before=[plant], columns=["MATNR", "ALT_BOM_COUNT"])
