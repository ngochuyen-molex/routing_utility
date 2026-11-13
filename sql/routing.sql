-- WITH materials AS (
--     SELECT '5032951728' AS mat, 'MN15-04' AS res UNION ALL
--     SELECT '1703591100', 'SK60-4F4' UNION ALL
--     -- ... add your material/resource pairs here
--     SELECT '2066160318', 'SK60-4F4'
-- ),
-- -- Step 1: Check if material is assigned to plant 1901 in MAPL
-- material_at_plant AS (
--     SELECT DISTINCT mp.MATNR
--     FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL mp
--     WHERE mp.WERKS = '1901'
--         AND mp.PLNTY = 'N'
--         AND mp.DW_SOFT_DELETE_FLAG = 0
-- ),
-- Step 2: Check if routing with that resource already exists at plant 1901
WITH routing_exists AS (
    SELECT
        trim(mp.MATNR, '0') as Material,
        cr.ARBPL AS WORK_CENTER,
        po.VORNR AS OPERATION,
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
        AND mp.MATNR = '000000000522691620'
        AND po.VORNR = '0020'
)
SELECT * FROM routing_exists;
-- SELECT
--     m.mat AS MATERIAL,
--     m.res AS RESOURCE,
--     CASE
--         WHEN map.MATNR IS NULL THEN 2           -- Material not assigned to plant 1901
--         WHEN re.MATNR IS NOT NULL THEN 1        -- Routing with resource already exists
--         ELSE 0                                   -- Safe to add routing
--     END AS SKIP
-- FROM materials m
-- LEFT JOIN material_at_plant map2
--     ON map.MATNR = LPAD(m.mat, 18, '0')
-- LEFT JOIN routing_exists re
--     ON re.MATNR = LPAD(m.mat, 18, '0')
--     AND re.RESOURCE = m.res
-- ORDER BY m.mat  


-- • Material number padding: SAP stores material numbers with leading zeros (18 chars). Use LPAD('1726920031', 18, '0')
--   to get '000000001726920031'.
--   • Deletion check: pk.LOEKZ = ' ' filters out deleted routings.
--   • Soft delete: DW_SOFT_DELETE_FLAG = 0 excludes records soft-deleted in the data lake.
--   • If the query returns rows, a duplicate exists - skip the routing creation in SAP.


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
WHERE pk.WERKS = '1901'
    AND po.VORNR = '0020'
    AND mp.PLNTY = 'N' -- show only visible routing in sap
    AND mp.DW_SOFT_DELETE_FLAG = 0 --Routing assignments deleted from SAP and marked for cleanup in the data lake
    AND pk.DW_SOFT_DELETE_FLAG = 0 --Routing headers that were fully removed
    AND mp.LOEKZ != 'X' -- exclude Material-to-routing links flagged as deleted in SAP ->Non-deleted MAPL assignments
    AND ps.DW_SOFT_DELETE_FLAG = 0 --Deleted sequences (e.g. old A505110D at GC 00)
    and po.DW_SOFT_DELETE_FLAG = 0 --Deleted operations
    AND mp.MATNR IN ('000000000522691620')