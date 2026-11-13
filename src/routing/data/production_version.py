"""Production version queries (MKAL, plus routing ops / PRTs for attribute matching)."""
from routing.core.clean import to_sap_matnr
from routing.core.config import BATCH_SIZE, PLANT
from routing.core.db import batches, query, query_in_batches

SQL_COUNT = """
    SELECT
        LTRIM(MATNR, '0')      AS material,
        COUNT(DISTINCT VERID)   AS production_version_count
    FROM MLX_DATALAKE.MLX_SAP_ECC.MKAL
    WHERE MATNR IN ({placeholders})
        AND WERKS = %s
    GROUP BY MATNR
"""

SQL_BY_GROUP = """
    SELECT
        LTRIM(MATNR, '0')  AS material,
        PLNNR               AS routing_group,
        LTRIM(ALNAL, '0')   AS group_counter,
        VERID               AS production_version,
        TEXT1               AS description
    FROM MLX_DATALAKE.MLX_SAP_ECC.MKAL
    WHERE (MATNR, PLNNR, LPAD(ALNAL, 2, '0')) IN ({placeholders})
    AND WERKS = %s
    ORDER BY material, routing_group, group_counter
"""

# One row per production version / work center / PRT combination
SQL_BY_ATTRIBUTES = """
    WITH pv AS (
        SELECT MATNR, WERKS, VERID, TEXT1, PLNTY, PLNNR, ALNAL
        FROM MLX_DATALAKE.MLX_SAP_ECC.MKAL
        WHERE WERKS = %s AND MATNR IN ({placeholders})
    ),
    ops AS (
        SELECT pv.MATNR, pv.VERID, po.PLNNR, po.PLNKN, c.ARBPL
        FROM pv
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLAS pa
          ON pa.PLNTY = pv.PLNTY AND pa.PLNNR = pv.PLNNR AND pa.PLNAL = pv.ALNAL
         AND pa.LOEKZ = ''
        JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO po
          ON po.PLNTY = pa.PLNTY AND po.PLNNR = pa.PLNNR AND po.PLNKN = pa.PLNKN
         AND po.ZAEHL = pa.ZAEHL
        JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD c
          ON c.OBJID = po.ARBID AND c.OBJTY = 'A'
    ),
    prt AS (   -- PRT materials (tools / lubricants) per operation
        SELECT f.PLNNR, f.PLNKN, LTRIM(v.MATNR, '0') AS PRT_MATNR
        FROM MLX_DATALAKE.MLX_SAP_ECC.PLFH f
        JOIN MLX_DATALAKE.MLX_SAP_ECC.CRVM_A v ON v.OBJID = f.OBJID AND v.OBJTY = f.OBJTY
        WHERE f.LOEKZ = ''
    )
    SELECT LTRIM(pv.MATNR, '0') AS material,
           pv.VERID             AS production_version,
           pv.TEXT1             AS description,
           pv.PLNNR             AS routing_group,
           LTRIM(pv.ALNAL, '0') AS group_counter,
           UPPER(o.ARBPL)       AS resource,
           UPPER(p.PRT_MATNR)   AS prt
    FROM pv
    JOIN ops o ON o.MATNR = pv.MATNR AND o.VERID = pv.VERID
    LEFT JOIN prt p ON p.PLNNR = o.PLNNR AND p.PLNKN = o.PLNKN
"""


def count_by_material(conn, materials, plant=PLANT):
    """Columns: MATERIAL, PRODUCTION_VERSION_COUNT."""
    return query_in_batches(conn, SQL_COUNT, [to_sap_matnr(m) for m in materials],
                            params_after=[plant],
                            columns=["MATERIAL", "PRODUCTION_VERSION_COUNT"])


def by_group(conn, triples, plant=PLANT):
    """triples = [(material, routing_group, group_counter), ...] (no leading zeros).
    Columns: MATERIAL, ROUTING_GROUP, GROUP_COUNTER, PRODUCTION_VERSION, DESCRIPTION."""
    import pandas as pd
    triples = list(dict.fromkeys(triples))
    frames = []
    for batch in batches(triples, BATCH_SIZE):
        tuple_sql = ", ".join(["(LPAD(%s, 18, '0'), %s, LPAD(%s, 2, '0'))"] * len(batch))
        params = [value for triple in batch for value in triple] + [plant]
        frames.append(query(conn, SQL_BY_GROUP.format(placeholders=tuple_sql), params))
    columns = ["MATERIAL", "ROUTING_GROUP", "GROUP_COUNTER", "PRODUCTION_VERSION", "DESCRIPTION"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)


def by_attributes(conn, materials, plant=PLANT):
    """Every production version with its resources and PRTs (tools / lubricants)."""
    return query_in_batches(
        conn, SQL_BY_ATTRIBUTES, [to_sap_matnr(m) for m in materials], params_before=[plant],
        columns=["MATERIAL", "PRODUCTION_VERSION", "DESCRIPTION", "ROUTING_GROUP",
                 "GROUP_COUNTER", "RESOURCE", "PRT"])
