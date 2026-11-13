SELECT
        pk.PLNNR AS ROUTING_GROUP,
        pk.PLNAL AS GROUP_COUNTER,
        pk.PLNTY AS TASK_LIST_TYPE,
        pk.WERKS AS PLANT,
        pk.KTEXT AS ROUTING_DESCRIPTION,
        pk.STATU AS STATUS,
        pk.LOEKZ AS DELETION_FLAG,
        pk.DELKZ AS DELETION_CODE,
        po.VORNR AS OPERATION_NUMBER,
        po.LTXA1 AS OPERATION_TEXT,
        cr.ARBPL AS RESOURCE_NAME,
        po.BMSCH AS BASE_QUANTITY,
        po.MEINH AS BASE_QUANTITY_UNIT
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
        AND pk.PLNAL = ps.PLNAL -- ties to specific group counter
        AND ps.LOEKZ = ' '
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLPO po
        ON ps.MANDT = po.MANDT
        AND ps.PLNTY = po.PLNTY
        AND ps.PLNNR = po.PLNNR
        AND ps.PLNKN = po.PLNKN
    LEFT JOIN MLX_DATALAKE.MLX_SAP_ECC.CRHD cr
        ON po.ARBID = cr.OBJID
        AND po.MANDT = cr.MANDT
    WHERE pk.WERKS = '1901'
        AND pk.LOEKZ = ' '
        --AND po.VORNR IN ('0020', '0030')
        --   AND cr.ARBPL = :resource
        AND pk.DW_SOFT_DELETE_FLAG = 0
        AND mp.DW_SOFT_DELETE_FLAG = 0
        AND TRIM(pk.DELKZ) != 'X'
        




