# Routing Workflow Tools

Scripts that build and check MES workflows and Tool Plan Matrix rows from SAP routings for the same material.
Code lives in `src/routing/opc/`. Run with `routing opc <name> -i INPUT.xlsx [-o OUTPUT.xlsx]`
(without `-i` / `-o` the `INPUT_FILE` / `OUTPUT_FILE` defaults at the top of each script are used).

| Script | Command | Purpose |
|---|---|---|
| `add_workflow.py` | `routing opc add-workflow` | Generate new MES workflows (upload file) by copying an existing source workflow |
| `compare_workflow.py` | `routing opc compare-workflow` | Compare target workflows step by step against the source workflow |
| `add_tpm.py` | `routing opc add-tpm` | Add or update Tool Plan Matrix rows (ideal cycle time) from an Excel routing file |

**Data sources**
- SAP routings: Snowflake (`MLX_DATALAKE.MLX_SAP_ECC`), connection `default`, group counters via `routing.data.routing.group_counters`
- MES workflows: SQL Server `[STDS].[EXCRSCh]` via `routing.core.db.mssql_conn`

---

## Shared logic

### Workflow naming
- Workflow name = `Material-<group counter>`, e.g. `5019506039-22`. No zero padding.
- Group counter `1` is named with the material only, e.g. `2216982000` (source and target, both scripts).

### Source selection (one source per material)
1. Read the material's routing group counters from SAP (`MAPL`, `PLKO`, `MARC`):
   - plant `1901`
   - `PLNTY = 'N'` (routings only; inspection plans `Q` are ignored)
   - not deleted (`LOEKZ` blank, `DW_SOFT_DELETE_FLAG = 0`)
   - material not marked for deletion and status not `E3`
2. Exclude the counters that are targets in the input file (a target is never its own source).
3. Sort the remaining counters from highest to lowest.
4. Use the highest counter whose workflow exists in MES. If it does not exist, fall back to the next highest.
5. The choice is logged on the **Source Counter Selection** sheet (chosen counter, all candidates, skipped counters).

Example: material `5019506039` has SAP counters 15, 17, 19, 21, 22 and the input targets 22 → candidates 21, 19, 17, 15 → source is `5019506039-21` if it exists in MES, else `5019506039-19`, etc.

---

## add_workflow.py

### Input
Excel file (`INPUT_FILE`) with columns `Material`, `group counter`, `Resource`, optional `Tool`.

- **Target name**: see Workflow naming.
- **New description**: `Resource-Tool-Material` (tool left out if blank or `0`).
- **Duplicate rows** (same target, resource, tool): collapsed, last row kept.
- **Conflicting rows** (same target with different resource/tool/description): all skipped.
- **Blank material or group counter**: skipped.

### Generation
**Case 1 - target does not exist in MES** → `Execution = INSERT`
- Copy all steps of the source workflow into the target.
- Revision = `A`.
- Description = new description; Status = source ERP route status; ERP Route = `<target> (<revision>)`.

**Case 2 - target already exists in MES** (checked by workflow name, current revision)
The output contains two blocks for the same workflow name:
1. **Existing workflow** (current revision) → `Execution = UPDATE`: its own steps and description unchanged, **Status = 2**, ERP Route = `<target> (<existing revision>)`.
2. **New revision** → `Execution = INSERT`: built from the source as in Case 1, with the next free revision.

Example: `5034780419-11` exists at revision B →
| Execution | Name | Revision | Status | ERP Route |
|---|---|---|---|---|
| UPDATE | 5034780419-11 | B | 2 | 5034780419-11 (B) |
| INSERT | 5034780419-11 | C | source status | 5034780419-11 (C) |

**Revision rule**
- Cycle `A → B → C → A` (`REVISION_CYCLE`).
- Revisions already stored in MES for that name are skipped.
- If all revisions are used, the target is skipped and logged.

| Current | Stored revisions | New revision |
|---|---|---|
| (new) | - | A |
| B | B | C |
| C | C | A |
| C | A, C | B |
| B | A, B, C | none (skipped) |

**Safety rule**: if a target exists but there is no source or no free revision, the existing workflow is **not** set to status 2 and nothing is generated for it.

### Step mapping (source → new workflow)
| Output column | Value |
|---|---|
| Execution | `UPDATE` for the existing revision (status 2), `INSERT` for the new workflow |
| Completion Message | Blank |
| Name | Target workflow name |
| Revision | `A` or next free revision |
| Description | `Resource-Tool-Material` |
| Status | Source ERP route status (existing block: `2`) |
| ERP Route | `<target> (<workflow revision>)`, e.g. `5034780419-11 (B)`; the revision in brackets always matches the Revision column |
| Name (2nd) / Spec | Source step name |
| X / Y Location | Source X / Y |
| Route Step | Source route step |
| to spec | Next step name |
| Is Last Step | `1` when Spec = `End Spec` |

### Output (`OUTPUT_FILE`)
| Sheet | Content |
|---|---|
| Workflow To Add | Upload file: `Execution` and `Completion Message` (blank) first; existing block (UPDATE, status 2), then new revision (INSERT) |
| Generation Audit | Per workflow block: revision, status, source, step count |
| Target Revised | Existing targets: old revision, status set, new revision, source |
| Source Counter Selection | Chosen source counter per material |
| Issues | All problem rows with `Result` and `Reason` |

**Issues sheet**
| Result | Reason |
|---|---|
| Skipped | No SAP routing group counter found after excluding target counters |
| Skipped | No MES workflow found for any SAP routing group counter |
| Skipped | No free revision (A/B/C all used) |
| Skipped | Same target workflow with different Resource/Tool/Description in input |
| Skipped | Blank Material or group counter |
| Generated with warning | No active SAP routing for this group counter (typo, deleted routing or not a routing) |

### Config (top of file)
| Setting | Default |
|---|---|
| `SAP_PLANT` | `1901` |
| `REVISION_CYCLE` | `["A", "B", "C"]` |
| `NEW_WORKFLOW_REVISION` | `A` |
| `EXISTING_WORKFLOW_STATUS` | `2` |

### Assumption
Stored revisions are read by joining `Workflow.WorkflowBaseId = WorkflowBase.WorkflowBaseId` (`fetch_workflow_revisions`). Adjust if the MES column name differs.

---

## compare_workflow.py

### Input
Excel file (`INPUT_FILE`) with columns `Material` and `group counter`.
- Rows with blank material or counter, and target names used by more than one material, are moved to their own sheets.

### Comparison
- Each target workflow is paired with its material's source and compared on `Sequence`.
- Step status: `Matched`, `StepName mismatch`, `Sequence only in target`, `Sequence only in source`.
- Extra steps on either side count as mismatches.
- `WorkflowMatch = TRUE` only when every compared row is `Matched`.
- One summary row per target workflow.
- Steps are compared by sequence number, so one missing step shifts all following steps into mismatches.

### Output (`workflow_comparison.xlsx`)
| Sheet | Content |
|---|---|
| Step Comparison | Side-by-side steps for each target and source |
| Workflow Summary | One row per target: compared, matched, mismatched counts |
| Target / Source Workflow Steps | Raw steps fetched from MES |
| Source Counter Selection | Chosen source counter per material |
| Target Already In SAP | Target counters that already exist as SAP routings (excluded from source) |
| Target Not Found / Source Not Found | Missing workflows with the reason |
| Duplicate Sequence | Workflows with repeated sequence numbers (only the first is compared) |
| Conflicting Input / Blank Material Counter | Rejected input rows |

---

## add_tpm.py

Adds new Tool Plan Matrix (TPM) rows and updates the ideal cycle time of existing ones.

### Input
Excel file (`INPUT_FILE`), first worksheet. Required columns:

`Material`, `Resource`, `Tool`, `group counter`, `Efficiency`, `Utilization`, `Tool Cavity`, `Dept`, `Priority`, `Sorting/ Lubricant`, `Sorting/ Lubricant Capacity`

Optional columns: `Capacity(Pcs/hr)`, `Capacity` (shots/hr), `Ideal cycle time`.

Existing TPM rows are read for the input materials via `routing.data.tpm.fetch_existing_tool_plan_matrix`. Efficiency and utilization per work center come from `EFFICIENCY_FILE`.

### ERP Route
| group counter | `mlxERPRoute` |
|---|---|
| `1` or blank | `<material>`, e.g. `12345` |
| anything else | `<material>-<group counter>`, e.g. `12345-2` |

### Ideal cycle time
Capacity source, first match wins: `Ideal cycle time` (used as is) → `Capacity(Pcs/hr)` → `Capacity` (shots/hr, multiplied by Tool Cavity, default 1).

| Dept | Formula |
|---|---|
| `MD` | Capacity × Efficiency (Excel, 0 treated as blank → work center lookup → 1) |
| `AS` | Capacity × Utilization (Excel → lookup → 1) |
| `STP`, `PLT` | Capacity × Efficiency × Utilization. Tool populated → both from the lookup file; tool blank → both from the Excel input |

The result is rounded to a whole number. Only `MD`, `AS`, `STP` and `PLT` are processed.

### Matching existing TPM rows
| Request | Key |
|---|---|
| Tool populated | Material + Resource + ERPRoute + Tool |
| Tool blank | Material + Resource + ERPRoute |

- Existing rows use their stored `mlxERPRoute` as is; a null route never matches a request.
- Key matches → the existing row's cycle time is updated (`Updated TPM Cycle Time`).
- No match → the request is added (`Add New TPM`).
- A blank-tool request updates every existing row with the same Material + Resource + ERPRoute that no tool request already matched.

**Sorting / Lubricant** rows use Material + Resource only (resource = the `Sorting/ Lubricant` column, cycle time = `Sorting/ Lubricant Capacity`), and are added with a blank ToolPlan, Priority and ERP Route.

### Duplicate input rows
Rows with the same Material + Resource + Tool (a blank tool only groups with other blank tools) but different group counters: the **highest group counter** is kept, the rest are skipped and logged with the `KeptGroupCounter` that won.

### Spec for new rows
| Resource | Spec taken from the material's existing rows |
|---|---|
| Contains `YMHI` (any case) | First non-blank Spec that does **not** contain `production` **and** does contain `sort` or `lubrication` (case-insensitive). None found → blank, logged on **Spec Warning** |
| Anything else | First non-blank Spec |

Existing rows keep their own Spec.

### Output (`OUTPUT_FILE`)
| Sheet | Content |
|---|---|
| Tool Plan Matrix Output | Upload file: `Execute` (`Insert/Update` for new rows, `Update` for existing) and blank `Completion Message`, then the TPM columns. Sorted by Material, RowType, Priority |
| Normal Update Audit | Updated existing TPM rows: old / new cycle time, `IdealCycleTimeChanged` |
| Sorting Update Audit | The same for Sorting / Lubricant rows |
| Calculation Audit | Per request: Dept, capacity source, capacity, tool cavity, Excel / lookup / final efficiency and utilization, resulting cycle time |
| Skipped Rows | All skipped rows with a `SkipReason` column |
| Spec Warning | New rows with a `YMHI` resource whose Spec was left blank |

`RowType` values: `Existing`, `Updated TPM Cycle Time`, `Updated Sorting Cycle Time`, `Add New TPM`, `Add New Sorting`.

**Skipped Rows reasons**
| SkipReason |
|---|
| Material not found in Tool Plan Matrix |
| Excluded resource (C_RFE / C_RE / C_FE) |
| Invalid Dept (not MD / AS / STP / PLT) |
| Blank Material or Resource |
| Missing Capacity / Ideal cycle time |
| Lower group counter duplicate (higher group counter kept) |
| Conflicting cycle time for same Material / Resource / ERPRoute / Tool |
| Conflicting Sorting/Lubricant cycle time |

Columns differ per reason; a column that does not apply to a reason is left blank.

### Config (top of file)
| Setting | Default |
|---|---|
| `INPUT_FILE` | `add_routing_mold.xlsx` in Downloads (override with `-i`) |
| `OUTPUT_FILE` | `output/add_mld.xlsx` in the repo (override with `-o`) |
| `EFFICIENCY_FILE` | `Eff_Util_workcenter.xlsx` on the MXV share (`routing.core.config`) |
| `EXCLUDED_RESOURCES` | `C_RFE`, `C_RE`, `C_FE` |

### Notes
- Unchanged existing rows are still written with `Execute = Update`.
- Existing TPM rows with a null `mlxERPRoute` are never updated by this script.
