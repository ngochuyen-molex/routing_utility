from pathlib import Path
import pandas as pd
import snowflake.connector
from tpm_common import clean_string, get_sql_connection, validate_input_columns


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\add_routing_chau_september.xlsx")
OUTPUT_FILE = Path("output/generated_workflow_molding_oct.xlsx")

REQUIRED_COLUMNS = ["Material", "group counter", "Resource"]

SAP_PLANT = "1901"

REVISION_CYCLE = ["A", "B", "C"]
NEW_WORKFLOW_REVISION = "A"
EXISTING_WORKFLOW_STATUS = 2

EXCEL_OUTPUT_COLUMNS = [
    "Name",
    "Revision",
    "IsRevOfRcd",
    "Description",
    "Notes",
    "Status",
    "ECO",
    "ERP Route",
    "Name",
    "Spec",
    "Sub Workflow",
    "X Location",
    "Y Location",
    "Route Step",
    "to spec",
    "LineType",
    "Is Last Step"
]

LOG_COLUMNS = ["Material", "group counter", "Resource", "Tool", "TargetWorkflowName", "Reason"]


# ============================================================
# PREPARE INPUT
# ============================================================

def build_description(row):
    resource = clean_string(row["Resource"])
    tool = clean_string(row["Tool"])
    material = clean_string(row["Material"])
    if tool in ["0", "0.0"]:
        tool = ""
    return "-".join(part for part in [resource, tool, material] if part)


def build_workflow_name(material, counter_number):
    # group counter 1 workflow is named with the material only
    return material if counter_number == 1 else f"{material}-{counter_number}"


def prepare_input(input_df):
    prepared_df = input_df.copy()

    for column in ["Material", "group counter", "Resource"]:
        prepared_df[column] = prepared_df[column].apply(clean_string)

    prepared_df["Tool"] = prepared_df["Tool"].apply(clean_string) if "Tool" in prepared_df.columns else ""

    blank_key_df = prepared_df[(prepared_df["Material"] == "") | (prepared_df["group counter"] == "")].copy()
    prepared_df = prepared_df[(prepared_df["Material"] != "") & (prepared_df["group counter"] != "")].copy()

    prepared_df["TargetWorkflowName"] = prepared_df["Material"] + "-" + prepared_df["group counter"]
    first_counter_mask = prepared_df["group counter"] == "1"
    prepared_df.loc[first_counter_mask, "TargetWorkflowName"] = prepared_df.loc[first_counter_mask, "Material"]
    prepared_df["NewDescription"] = prepared_df.apply(build_description, axis=1)

    target_summary = (
        prepared_df.groupby("TargetWorkflowName")
        .agg(
            DescriptionCount=("NewDescription", "nunique"),
            ResourceCount=("Resource", "nunique"),
            ToolCount=("Tool", "nunique")
        )
        .reset_index()
    )

    conflict_targets = target_summary[
        (target_summary["DescriptionCount"] > 1)
        | (target_summary["ResourceCount"] > 1)
        | (target_summary["ToolCount"] > 1)
    ]["TargetWorkflowName"]

    conflict_df = prepared_df[prepared_df["TargetWorkflowName"].isin(conflict_targets)].copy()

    prepared_df = (
        prepared_df[~prepared_df["TargetWorkflowName"].isin(conflict_targets)]
        .drop_duplicates(subset=["TargetWorkflowName"], keep="last")
        .copy()
    )

    return prepared_df, blank_key_df, conflict_df


def build_log_row(input_row, reason):
    return {
        "Material": input_row["Material"],
        "group counter": input_row["group counter"],
        "Resource": input_row["Resource"],
        "Tool": input_row["Tool"],
        "TargetWorkflowName": input_row["TargetWorkflowName"],
        "Reason": reason
    }


# ============================================================
# FETCH SAP ROUTING GROUP COUNTERS
# ============================================================

def fetch_sap_counters(materials):
    materials = list(dict.fromkeys(clean_string(material) for material in materials if clean_string(material)))

    if not materials:
        return pd.DataFrame(columns=["Material", "CounterNumber"])

    placeholders = ",".join(["%s"] * len(materials))

    query = f"""
    SELECT DISTINCT
        LTRIM(m.MATNR, '0') AS MATERIAL,
        m.PLNAL AS GROUP_COUNTER
    FROM MLX_DATALAKE.MLX_SAP_ECC.MAPL m
    JOIN MLX_DATALAKE.MLX_SAP_ECC.PLKO k
        ON m.PLNTY = k.PLNTY AND m.PLNNR = k.PLNNR AND m.PLNAL = k.PLNAL
        AND k.DW_SOFT_DELETE_FLAG = 0 AND TRIM(k.LOEKZ) = ''
    JOIN MLX_DATALAKE.MLX_SAP_ECC.MARC marc
        ON m.MATNR = marc.MATNR AND m.WERKS = marc.WERKS
        AND marc.DW_SOFT_DELETE_FLAG = 0 AND TRIM(marc.LVORM) = ''
        AND marc.MMSTA != 'E3'
    WHERE m.WERKS = %s
        AND m.PLNTY = 'N'
        AND m.DW_SOFT_DELETE_FLAG = 0 AND TRIM(m.LOEKZ) = ''
        AND LTRIM(m.MATNR, '0') IN ({placeholders})
    """

    conn = snowflake.connector.connect(connection_name="default")
    try:
        cursor = conn.cursor()
        cursor.execute(query, [SAP_PLANT] + materials)
        counter_df = pd.DataFrame(cursor.fetchall(), columns=["Material", "GroupCounter"])
    finally:
        conn.close()

    counter_df["Material"] = counter_df["Material"].apply(clean_string)
    counter_df["CounterNumber"] = pd.to_numeric(counter_df["GroupCounter"], errors="coerce")
    counter_df = counter_df.dropna(subset=["CounterNumber"])
    counter_df["CounterNumber"] = counter_df["CounterNumber"].astype(int)

    return counter_df[["Material", "CounterNumber"]].drop_duplicates()


def build_source_candidates(counter_df, prepared_df):
    target_counters = prepared_df[["Material", "group counter", "Resource", "Tool", "TargetWorkflowName"]].copy()
    target_counters["CounterNumber"] = pd.to_numeric(target_counters["group counter"], errors="coerce")

    # input counters without an active SAP routing: warning only
    sap_keys = set(zip(counter_df["Material"], counter_df["CounterNumber"]))
    not_in_sap_mask = [
        (material, counter) not in sap_keys
        for material, counter in zip(target_counters["Material"], target_counters["CounterNumber"])
    ]
    target_not_in_sap_df = target_counters[not_in_sap_mask][LOG_COLUMNS[:-1]].copy()
    target_not_in_sap_df["Reason"] = f"No active SAP routing for this group counter (plant {SAP_PLANT}, PLNTY=N)"

    # target counters are never used as source
    candidate_df = counter_df.merge(target_counters[["Material", "CounterNumber"]], on=["Material", "CounterNumber"], how="left", indicator=True)
    candidate_df = candidate_df[candidate_df["_merge"] == "left_only"].drop(columns="_merge")

    candidate_df["SourceWorkflowName"] = [
        build_workflow_name(material, counter)
        for material, counter in zip(candidate_df["Material"], candidate_df["CounterNumber"])
    ]
    candidate_df = candidate_df.sort_values(by=["Material", "CounterNumber"], ascending=[True, False])

    return candidate_df, target_not_in_sap_df


# ============================================================
# FETCH WORKFLOW STEPS BY NAME (CURRENT REVISION)
# ============================================================

def fetch_workflow_steps(workflow_names):
    workflow_names = list(dict.fromkeys(clean_string(name) for name in workflow_names if clean_string(name)))
    if not workflow_names:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(workflow_names))

    query = f"""
SELECT
    LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) AS MaterialKey,
    wfb.WorkflowName,
    wf.WorkflowRevision,
    erp.ERPRouteRevision,
    erp.Status,
    wf.Description AS WorkflowDescription,
    ws.WorkflowStepName AS StepName,
    ws.Xlocation,
    ws.Ylocation,
    ws.RouteStepId,
    rs.Name AS RouteStepName,
    ws.Sequence,
    erb.ERPRouteName,
    LEAD(ws.WorkflowStepName) OVER (
        PARTITION BY wfb.WorkflowName
        ORDER BY ws.Sequence
    ) AS ToSpec,
    ws.IsLastStep
FROM [STDS].[EXCRSCh].Workflow wf
INNER JOIN [STDS].[EXCRSCh].WorkflowBase wfb WITH (NOLOCK)
    ON wf.WorkflowId = wfb.RevOfRcdId
LEFT JOIN [STDS].[EXCRSCh].WorkflowStep ws WITH (NOLOCK)
    ON ws.WorkflowId = wf.WorkflowId
LEFT JOIN [STDS].[EXCRSCh].RouteStep rs WITH (NOLOCK)
    ON rs.RouteStepId = ws.RouteStepId
LEFT JOIN [STDS].[EXCRSCh].ERPRoute erp WITH (NOLOCK)
    ON erp.ERPRouteId = CASE
        WHEN wf.ERPRouteId = '0000000000000000' THEN (
            SELECT eb.RevOfRcdId
            FROM [STDS].[EXCRSCh].ERPRouteBase eb
            WHERE eb.ERPRouteBaseId = wf.ERPRouteBaseId
        )
        ELSE wf.ERPRouteId
    END
LEFT JOIN [STDS].[EXCRSCh].ERPRouteBase erb WITH (NOLOCK)
    ON erb.ERPRouteBaseId = erp.ERPRouteBaseId
WHERE wfb.WorkflowName IN ({placeholders})
ORDER BY wfb.WorkflowName, ws.Sequence;
    """

    with get_sql_connection() as conn:
        workflow_df = pd.read_sql(query, conn, params=workflow_names)

    string_columns = [
        "MaterialKey",
        "WorkflowName",
        "WorkflowRevision",
        "ERPRouteRevision",
        "Status",
        "WorkflowDescription",
        "StepName",
        "RouteStepId",
        "RouteStepName",
        "ERPRouteName",
        "ToSpec"
    ]

    for column in string_columns:
        workflow_df[column] = workflow_df[column].apply(clean_string)

    workflow_df["Sequence"] = pd.to_numeric(workflow_df["Sequence"], errors="coerce")

    return workflow_df


# ============================================================
# FETCH ALL STORED REVISIONS OF TARGET WORKFLOWS
# ============================================================

def fetch_workflow_revisions(workflow_names):
    workflow_names = list(dict.fromkeys(clean_string(name) for name in workflow_names if clean_string(name)))
    if not workflow_names:
        return {}

    placeholders = ",".join(["?"] * len(workflow_names))

    query = f"""
    SELECT DISTINCT wfb.WorkflowName, wf.WorkflowRevision
    FROM [STDS].[EXCRSCh].Workflow wf WITH (NOLOCK)
    INNER JOIN [STDS].[EXCRSCh].WorkflowBase wfb WITH (NOLOCK)
        ON wf.WorkflowBaseId = wfb.WorkflowBaseId
    WHERE wfb.WorkflowName IN ({placeholders})
    """

    with get_sql_connection() as conn:
        revision_df = pd.read_sql(query, conn, params=workflow_names)

    revision_df["WorkflowName"] = revision_df["WorkflowName"].apply(clean_string)
    revision_df["WorkflowRevision"] = revision_df["WorkflowRevision"].apply(clean_string).str.upper()

    return revision_df.groupby("WorkflowName")["WorkflowRevision"].apply(set).to_dict()


# ============================================================
# SELECT ONE SOURCE WORKFLOW PER MATERIAL
# ============================================================

def select_source_workflows(candidate_df):
    selection_columns = ["Material", "SourceGroupCounter", "SourceWorkflowName", "CandidateCounters", "SkippedCounters"]

    if candidate_df.empty:
        return pd.DataFrame(), pd.DataFrame(columns=selection_columns)

    candidate_steps_df = fetch_workflow_steps(candidate_df["SourceWorkflowName"].tolist())
    found_workflows = set(candidate_steps_df["WorkflowName"]) if not candidate_steps_df.empty else set()

    # highest SAP counter that exists in MES, falling back to the next highest
    selection_rows = []

    for material, group_df in candidate_df.groupby("Material", sort=False):
        counters = group_df["CounterNumber"].astype(str).tolist()
        selected = group_df[group_df["SourceWorkflowName"].isin(found_workflows)].head(1)

        if selected.empty:
            continue

        selected_counter = str(selected["CounterNumber"].iloc[0])

        selection_rows.append({
            "Material": material,
            "SourceGroupCounter": selected_counter,
            "SourceWorkflowName": selected["SourceWorkflowName"].iloc[0],
            "CandidateCounters": ", ".join(counters),
            "SkippedCounters": ", ".join(counters[:counters.index(selected_counter)])
        })

    selection_df = pd.DataFrame(selection_rows, columns=selection_columns)

    if selection_df.empty:
        return pd.DataFrame(), selection_df

    source_df = candidate_steps_df[candidate_steps_df["WorkflowName"].isin(selection_df["SourceWorkflowName"])].copy()
    source_df = source_df.merge(selection_df[["Material", "SourceWorkflowName"]], left_on="WorkflowName", right_on="SourceWorkflowName", how="inner")

    return source_df, selection_df


# ============================================================
# REVISION RULE
# ============================================================

def next_revision(current_revision, used_revisions):
    current_revision = clean_string(current_revision).upper()
    used_revisions = {clean_string(revision).upper() for revision in used_revisions}

    start = REVISION_CYCLE.index(current_revision) if current_revision in REVISION_CYCLE else -1

    for step in range(1, len(REVISION_CYCLE) + 1):
        candidate = REVISION_CYCLE[(start + step) % len(REVISION_CYCLE)]
        if candidate not in used_revisions:
            return candidate

    return None


# ============================================================
# GENERATE WORKFLOW ROWS
# ============================================================

def build_erp_route(route_name, revision):
    route_name = clean_string(route_name)
    revision = clean_string(revision)
    return f"{route_name} ({revision})" if route_name and revision else route_name


def build_workflow_rows(steps_df, workflow_name, revision, description, status, erp_route_name, source_workflow, block_order):
    new_df = pd.DataFrame(index=steps_df.index)

    new_df["WorkflowName"] = workflow_name
    new_df["Revision"] = revision
    new_df["IsRevOfRcd"] = ""
    new_df["Description"] = description
    new_df["Notes"] = ""
    new_df["Status"] = status
    new_df["ECO"] = ""

    new_df["ERP Route"] = [
        build_erp_route(erp_route_name, erp_revision)
        for erp_revision in steps_df["ERPRouteRevision"]
    ]

    # Second Name and Spec always contain exactly the same value.
    new_df["StepName"] = steps_df["StepName"]
    new_df["Spec"] = new_df["StepName"]

    new_df["Sub Workflow"] = ""
    new_df["X Location"] = steps_df["Xlocation"]
    new_df["Y Location"] = steps_df["Ylocation"]

    new_df["Route Step"] = steps_df["RouteStepName"]
    new_df["to spec"] = steps_df["ToSpec"]

    new_df["LineType"] = ""
    new_df["Is Last Step"] = (new_df["Spec"] == "End Spec").astype(int)

    # These columns are for audit and sorting only.
    new_df["_SourceWorkflow"] = source_workflow
    new_df["_BlockOrder"] = block_order
    new_df["_Sequence"] = steps_df["Sequence"]

    return new_df


def generate_new_workflows(prepared_df, source_df, existing_df, revision_map):
    generated_frames = []
    missing_source_rows = []
    no_revision_rows = []
    revised_rows = []

    for _, input_row in prepared_df.iterrows():
        material = input_row["Material"]
        target_workflow = input_row["TargetWorkflowName"]

        material_source_df = source_df[source_df["Material"] == material] if not source_df.empty else pd.DataFrame()

        if material_source_df.empty:
            missing_source_rows.append(build_log_row(input_row, "No source workflow found for material"))
            continue

        source_workflow = material_source_df["SourceWorkflowName"].iloc[0]
        existing_steps_df = existing_df[existing_df["WorkflowName"] == target_workflow] if not existing_df.empty else pd.DataFrame()

        if existing_steps_df.empty:
            new_revision = NEW_WORKFLOW_REVISION
        else:
            existing_revision = existing_steps_df["WorkflowRevision"].iloc[0]
            new_revision = next_revision(existing_revision, revision_map.get(target_workflow, {existing_revision}))

            if new_revision is None:
                no_revision_rows.append(build_log_row(input_row, f"No free revision ({'/'.join(REVISION_CYCLE)} all used)"))
                continue

            # existing workflow kept as is, only status reset
            generated_frames.append(build_workflow_rows(
                existing_steps_df,
                target_workflow,
                existing_revision,
                existing_steps_df["WorkflowDescription"].iloc[0],
                EXISTING_WORKFLOW_STATUS,
                existing_steps_df["ERPRouteName"].iloc[0] or target_workflow,
                "",
                0
            ))

            revised_rows.append({
                "Material": material,
                "TargetWorkflowName": target_workflow,
                "ExistingRevision": existing_revision,
                "ExistingNewStatus": EXISTING_WORKFLOW_STATUS,
                "NewRevision": new_revision,
                "SourceWorkflowName": source_workflow
            })

        generated_frames.append(build_workflow_rows(
            material_source_df,
            target_workflow,
            new_revision,
            input_row["NewDescription"],
            material_source_df["Status"],
            target_workflow,
            source_workflow,
            1
        ))

    if generated_frames:
        generated_df = pd.concat(generated_frames, ignore_index=True)
        generated_df = generated_df.sort_values(by=["WorkflowName", "_BlockOrder", "_Sequence"], na_position="last")
    else:
        generated_df = pd.DataFrame()

    return (
        generated_df,
        pd.DataFrame(missing_source_rows, columns=LOG_COLUMNS),
        pd.DataFrame(no_revision_rows, columns=LOG_COLUMNS),
        pd.DataFrame(revised_rows, columns=["Material", "TargetWorkflowName", "ExistingRevision", "ExistingNewStatus", "NewRevision", "SourceWorkflowName"])
    )


# ============================================================
# BUILD OUTPUT
# ============================================================

def build_upload_output(generated_df):
    if generated_df.empty:
        return pd.DataFrame(columns=EXCEL_OUTPUT_COLUMNS)

    output_df = generated_df[
    [
        "WorkflowName",
        "Revision",
        "IsRevOfRcd",
        "Description",
        "Notes",
        "Status",
        "ECO",
        "ERP Route",
        "StepName",
        "Spec",
        "Sub Workflow",
        "X Location",
        "Y Location",
        "Route Step",
        "to spec",
        "LineType",
        "Is Last Step"]].copy()

    # Duplicate Name headers are created only at the final Excel export stage.
    output_df.columns = EXCEL_OUTPUT_COLUMNS

    return output_df


def build_generation_audit(generated_df):
    audit_columns = ["TargetWorkflowName", "Revision", "Status", "SourceWorkflowName", "StepCount"]

    if generated_df.empty:
        return pd.DataFrame(columns=audit_columns)

    audit_df = (
        generated_df.assign(Status=generated_df["Status"].astype(str))
        .groupby(["WorkflowName", "Revision", "Status", "_SourceWorkflow", "_BlockOrder"])
        .size()
        .reset_index(name="StepCount")
        .rename(columns={
            "WorkflowName": "TargetWorkflowName",
            "_SourceWorkflow": "SourceWorkflowName"
        })
    )

    return audit_df.sort_values(by=["TargetWorkflowName", "_BlockOrder"])[audit_columns]


def build_missing_source_reasons(missing_source_df, candidate_df):
    if missing_source_df.empty:
        return missing_source_df

    sap_found = set(candidate_df["Material"]) if not candidate_df.empty else set()

    missing_source_df["Reason"] = f"No SAP routing group counter found (plant {SAP_PLANT}, PLNTY=N) after excluding target counters"
    missing_source_df.loc[missing_source_df["Material"].isin(sap_found), "Reason"] = "No MES workflow found for any SAP routing group counter"

    return missing_source_df


def build_issues(issue_frames):
    issue_columns = LOG_COLUMNS[:-1] + ["Result", "Reason"]
    frames = []

    for issue_df, result, default_reason in issue_frames:
        if issue_df.empty:
            continue

        issue_df = issue_df.reindex(columns=LOG_COLUMNS).copy()
        issue_df["Result"] = result
        if default_reason:
            issue_df["Reason"] = default_reason

        frames.append(issue_df[issue_columns])

    if not frames:
        return pd.DataFrame(columns=issue_columns)

    return pd.concat(frames, ignore_index=True)


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading workflow input file...")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    prepared_df, blank_key_df, conflict_df = prepare_input(input_df)

    materials = prepared_df["Material"].drop_duplicates().tolist()
    target_workflows = prepared_df["TargetWorkflowName"].drop_duplicates().tolist()

    print(f"Found {len(materials)} material numbers and {len(target_workflows)} target workflows.")
    print("Loading SAP routing group counters...")

    counter_df = fetch_sap_counters(materials)
    candidate_df, target_not_in_sap_df = build_source_candidates(counter_df, prepared_df)

    print(f"Found {len(candidate_df)} candidate source counters. {len(target_not_in_sap_df)} target counters not in SAP.")
    print("Loading one source workflow per material...")

    source_df, selection_df = select_source_workflows(candidate_df)

    source_workflow_count = source_df["SourceWorkflowName"].nunique() if not source_df.empty else 0
    print(f"Found {source_workflow_count} selected source workflows with {len(source_df)} step rows.")

    print("Loading existing target workflows...")

    existing_df = fetch_workflow_steps(target_workflows)
    revision_map = fetch_workflow_revisions(target_workflows)

    existing_count = existing_df["WorkflowName"].nunique() if not existing_df.empty else 0
    print(f"Found {existing_count} existing target workflows.")

    generated_df, missing_source_df, no_revision_df, revised_df = generate_new_workflows(
        prepared_df,
        source_df,
        existing_df,
        revision_map
    )

    missing_source_df = build_missing_source_reasons(missing_source_df, candidate_df)

    issues_df = build_issues([
        (missing_source_df, "Skipped", ""),
        (no_revision_df, "Skipped", ""),
        (conflict_df, "Skipped", "Same target workflow with different Resource/Tool/Description in input"),
        (blank_key_df, "Skipped", "Blank Material or group counter"),
        (target_not_in_sap_df, "Generated with warning", "")
    ])

    upload_df = build_upload_output(generated_df)
    generation_audit_df = build_generation_audit(generated_df)

    new_workflow_count = generated_df[generated_df["_BlockOrder"] == 1]["WorkflowName"].nunique() if not generated_df.empty else 0

    print(f"Generated {new_workflow_count} new workflow revisions with {len(upload_df)} workflow-step rows in total.")
    print(f"Existing workflows set to status {EXISTING_WORKFLOW_STATUS}: {len(revised_df)}.")
    print(f"Missing source workflows: {len(missing_source_df)}.")
    print(f"No free revision: {len(no_revision_df)}.")
    print(f"Target counters not in SAP (warning): {len(target_not_in_sap_df)}.")
    print(f"Conflicting target inputs skipped: {len(conflict_df)}.")
    print(f"Blank Material/group counter rows skipped: {len(blank_key_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        upload_df.to_excel(writer, sheet_name="Workflow To Add", index=False)
        generation_audit_df.to_excel(writer, sheet_name="Generation Audit", index=False)
        revised_df.to_excel(writer, sheet_name="Target Revised", index=False)
        selection_df.to_excel(writer, sheet_name="Source Counter Selection", index=False)
        issues_df.to_excel(writer, sheet_name="Issues", index=False)

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
