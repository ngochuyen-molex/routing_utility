# Routing Workflow Tools

Two scripts that build and check MES workflows from SAP routings for the same material.

| Script | Purpose |
|---|---|
| `add_workflow.py` | Generate new MES workflows (upload file) by copying an existing source workflow |
| `compare_workflow.py` | Compare target workflows step by step against the source workflow |

**Data sources**
- SAP routings: Snowflake (`MLX_DATALAKE.MLX_SAP_ECC`), connection `default`
- MES workflows: SQL Server `[STDS].[EXCRSCh]` via `tpm_common.get_sql_connection`

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
**Case 1 - target does not exist in MES**
- Copy all steps of the source workflow into the target.
- Revision = `A`.
- Description = new description; Status = source ERP route status; ERP Route = `<target> (<source ERP route revision>)`.

**Case 2 - target already exists in MES**
The output contains two blocks for the same workflow name:
1. **Existing workflow** (current revision): its own steps, description and ERP route unchanged, only **Status = 2**.
2. **New revision** built from the source as in Case 1, with the next free revision.

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
| Name | Target workflow name |
| Revision | `A` or next free revision |
| Description | `Resource-Tool-Material` |
| Status | Source ERP route status (existing block: `2`) |
| ERP Route | `<target> (<ERP route revision>)` |
| Name (2nd) / Spec | Source step name |
| X / Y Location | Source X / Y |
| Route Step | Source route step |
| to spec | Next step name |
| Is Last Step | `1` when Spec = `End Spec` |

### Output (`OUTPUT_FILE`)
| Sheet | Content |
|---|---|
| Workflow To Add | Upload file (existing block with status 2, then new revision) |
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
