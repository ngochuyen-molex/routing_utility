
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