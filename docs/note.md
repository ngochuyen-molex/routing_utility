
IF ideal cycle time exist values:
    
IF capacity(pcs/hrs) not blank
    MLD:
    Tool blank → Capacity × (Input Excel Efficiency → resource lookup Efficiency → 1)
    Tool populated → Capacity × (Input Excel Efficiency →lookup-> 1)

    AS:
    Capacity × Input_Excel Utilization(-> Lookup Utilization) -> 1
    Blank Utilization → 1

    STP / PLT:
    Tool populated → Capacity × lookup Efficiency × lookup Utilization
    Tool blank  → Capacity × input_Excel Efficiency × input_Excel Utilization
    Blank Efficiency or Utilization → 1

ELSE use capacity(shot/hrs):
    MLD:
    Tool blank → Capacity × Tool Cavity × (Excel Efficiency → resource lookup Efficiency → 1)
    Tool populated → Capacity × Tool Cavity × (Excel Efficiency →lookup-> 1)

    AS:
    Capacity x Tool Cavity × Excel Utilization(-> Lookup Utilization) 
    -> 1
    Blank Utilization → 1

    STP / PLT:
    Tool populated → Capacity × lookup Efficiency × lookup Utilization x tool_cavity
    Tool blank     → Capacity × Excel Efficiency × Excel Utilization x tool_cavity
    Blank Efficiency or Utilization → 1

SPEC FOR NEW ROWS (Add New TPM / Add New Sorting) — taken from an existing row of the same material (Name):
    YMHI resource (sorting/lubrication):
    Spec must contain "sort" / "sorting" / "lubrication" AND must NOT contain "production"
    → never takes a normal resource spec (e.g. MD_production)

    Normal resource (non-YMHI):
    Spec must NOT contain "sort" / "sorting" / "lubrication"
    → never takes a YMHI spec (e.g. MD_lubrication)

    No valid spec found → Spec left blank, row listed in "Spec Warning" sheet
    Existing rows keep their current Spec (not changed)