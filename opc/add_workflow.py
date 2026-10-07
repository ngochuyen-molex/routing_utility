from pathlib import Path

import pandas as pd

from tpm_common import clean_string, get_sql_connection, validate_input_columns


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\OneDrive - kochind.com\add_routing_chau_sorting.xlsx")
OUTPUT_FILE = Path("output/generated_workflow_sorting.xlsx")

REQUIRED_COLUMNS = ["Material", "group counter", "Resource"]

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


def prepare_input(input_df):
    prepared_df = input_df.copy()

    for column in ["Material", "group counter", "Resource"]:
        prepared_df[column] = prepared_df[column].apply(clean_string)

    prepared_df["Tool"] = prepared_df["Tool"].apply(clean_string) if "Tool" in prepared_df.columns else ""

    blank_key_df = prepared_df[(prepared_df["Material"] == "") | (prepared_df["group counter"] == "")].copy()
    prepared_df = prepared_df[(prepared_df["Material"] != "") & (prepared_df["group counter"] != "")].copy()

    prepared_df["TargetWorkflowName"] = prepared_df["Material"] + "-" + prepared_df["group counter"]
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


# ============================================================
# FETCH ONE SOURCE WORKFLOW PER MATERIAL
# ============================================================

def fetch_source_workflows(materials):
    materials = list(dict.fromkeys(clean_string(material) for material in materials if clean_string(material)))
    if not materials:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(materials))

    query = f"""
WITH WorkflowCandidates AS (
    SELECT
        LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) AS MaterialKey,
        wfb.WorkflowName,
        wf.WorkflowId,
        wf.WorkflowRevision,
        wf.ERPRouteId,
        wf.ERPRouteBaseId,
        wf.Description AS SourceDescription,
        ROW_NUMBER() OVER (
            PARTITION BY LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1)
            ORDER BY
                CASE
                    WHEN wfb.WorkflowName = LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) THEN 0
                    ELSE 1
                END,
                TRY_CONVERT(
                    INT,
                    NULLIF(
                        SUBSTRING(
                            wfb.WorkflowName,
                            CHARINDEX('-', wfb.WorkflowName + '-') + 1,
                            LEN(wfb.WorkflowName)
                        ),
                        wfb.WorkflowName
                    )
                ),
                wfb.WorkflowName
        ) AS SourceRank
    FROM [STDS].[EXCRSCh].Workflow wf
    INNER JOIN [STDS].[EXCRSCh].WorkflowBase wfb WITH (NOLOCK)
        ON wf.WorkflowId = wfb.RevOfRcdId
    WHERE LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) IN ({placeholders})
),
SelectedWorkflow AS (
    SELECT *
    FROM WorkflowCandidates
    WHERE SourceRank = 1
)

SELECT
    selected.MaterialKey,
    selected.WorkflowName AS SourceWorkflowName,
    selected.WorkflowRevision,
    erp.ERPRouteRevision,
    erp.Status,
    selected.SourceDescription,
    ws.WorkflowStepName AS StepName,
    ws.RouteStepId,
    rs.Name AS RouteStepName,
    ws.Sequence,
    erb.ERPRouteName,
    LEAD(ws.WorkflowStepName) OVER (
        PARTITION BY selected.WorkflowName
        ORDER BY ws.Sequence
    ) AS ToSpec
FROM SelectedWorkflow selected
LEFT JOIN [STDS].[EXCRSCh].WorkflowStep ws WITH (NOLOCK)
    ON ws.WorkflowId = selected.WorkflowId
LEFT JOIN [STDS].[EXCRSCh].RouteStep rs WITH (NOLOCK)
    ON rs.RouteStepId = ws.RouteStepId
LEFT JOIN [STDS].[EXCRSCh].ERPRoute erp WITH (NOLOCK)
    ON erp.ERPRouteId = CASE
        WHEN selected.ERPRouteId = '0000000000000000' THEN (
            SELECT eb.RevOfRcdId
            FROM [STDS].[EXCRSCh].ERPRouteBase eb
            WHERE eb.ERPRouteBaseId = selected.ERPRouteBaseId
        )
        ELSE selected.ERPRouteId
    END
LEFT JOIN [STDS].[EXCRSCh].ERPRouteBase erb WITH (NOLOCK)
    ON erb.ERPRouteBaseId = erp.ERPRouteBaseId
ORDER BY selected.MaterialKey, selected.WorkflowName, ws.Sequence;
    """

    with get_sql_connection() as conn:
        workflow_df = pd.read_sql(query, conn, params=materials)

    string_columns = [
        "MaterialKey",
        "SourceWorkflowName",
        "WorkflowRevision",
        "ERPRouteRevision",
        "Status",
        "SourceDescription",
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
# CHECK WHETHER TARGET WORKFLOWS ALREADY EXIST
# ============================================================

def fetch_existing_target_workflows(target_workflows):
    target_workflows = list(dict.fromkeys(clean_string(name) for name in target_workflows if clean_string(name)))

    if not target_workflows:
        return set()

    placeholders = ",".join(["?"] * len(target_workflows))

    query = f"""
    SELECT DISTINCT wfb.WorkflowName
    FROM [STDS].[EXCRSCh].WorkflowBase wfb WITH (NOLOCK)
    WHERE wfb.WorkflowName IN ({placeholders})
    """

    with get_sql_connection() as conn:
        existing_target_df = pd.read_sql(query, conn, params=target_workflows)

    return set(existing_target_df["WorkflowName"].apply(clean_string))


# ============================================================
# GENERATE NEW WORKFLOWS
# ============================================================

def build_erp_route(target_workflow, revision):
    target_workflow = clean_string(target_workflow)
    revision = clean_string(revision)
    return f"{target_workflow} ({revision})" if target_workflow and revision else target_workflow


def generate_new_workflows(prepared_df, source_df, existing_target_names):
    generated_frames = []
    missing_source_rows = []
    target_exists_rows = []

    for _, input_row in prepared_df.iterrows():
        material = input_row["Material"]
        target_workflow = input_row["TargetWorkflowName"]

        if target_workflow in existing_target_names:
            target_exists_rows.append({
                "Material": material,
                "group counter": input_row["group counter"],
                "Resource": input_row["Resource"],
                "Tool": input_row["Tool"],
                "TargetWorkflowName": target_workflow,
                "Reason": "Target workflow already exists"
            })
            continue

        material_source_df = source_df[source_df["MaterialKey"] == material].copy()

        if material_source_df.empty:
            missing_source_rows.append({
                "Material": material,
                "group counter": input_row["group counter"],
                "Resource": input_row["Resource"],
                "Tool": input_row["Tool"],
                "TargetWorkflowName": target_workflow,
                "Reason": "No source workflow found for material"
            })
            continue

        source_workflow = material_source_df["SourceWorkflowName"].iloc[0]
        new_df = pd.DataFrame(index=material_source_df.index)

        new_df["WorkflowName"] = target_workflow
        new_df["Revision"] = material_source_df["WorkflowRevision"]
        new_df["IsRevOfRcd"] = ""
        new_df["Description"] = input_row["NewDescription"]
        new_df["Notes"] = ""
        new_df["Status"] = material_source_df["Status"]
        new_df["ECO"] = ""

        new_df["ERP Route"] = [
            build_erp_route(target_workflow, revision)
            for revision in material_source_df["ERPRouteRevision"]
        ]

        # Second Name and Spec always contain exactly the same value.
        new_df["StepName"] = material_source_df["StepName"]
        new_df["Spec"] = new_df["StepName"]

        new_df["Sub Workflow"] = ""
        new_df["X Location"] = ""
        new_df["Y Location"] = ""

        new_df["Route Step"] = material_source_df["RouteStepName"]
        new_df["to spec"] = material_source_df["ToSpec"]

        new_df["LineType"] = ""
        new_df["Is Last Step"] = (new_df["Spec"] == "End Spec").astype(int)

        # These columns are for audit and sorting only.
        new_df["_SourceWorkflow"] = source_workflow
        new_df["_Sequence"] = material_source_df["Sequence"]

        generated_frames.append(new_df)

    if generated_frames:
        generated_df = pd.concat(generated_frames, ignore_index=True)
        generated_df = generated_df.sort_values(by=["WorkflowName", "_Sequence"], na_position="last")
    else:
        generated_df = pd.DataFrame()

    return generated_df, pd.DataFrame(missing_source_rows), pd.DataFrame(target_exists_rows)


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
    if generated_df.empty:
        return pd.DataFrame(columns=["TargetWorkflowName", "SourceWorkflowName", "StepCount"])

    audit_df = (
        generated_df.groupby(["WorkflowName", "_SourceWorkflow"])
        .size()
        .reset_index(name="StepCount")
        .rename(columns={
            "WorkflowName": "TargetWorkflowName",
            "_SourceWorkflow": "SourceWorkflowName"
        })
    )

    return audit_df.sort_values(by=["TargetWorkflowName"])


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

    print(f"Found {len(materials)} material numbers.")
    print("Loading one source workflow per material...")

    source_df = fetch_source_workflows(materials)
    existing_target_names = fetch_existing_target_workflows(target_workflows)

    source_workflow_count = source_df["SourceWorkflowName"].nunique() if not source_df.empty else 0

    print(f"Found {source_workflow_count} selected source workflows with {len(source_df)} step rows.")

    generated_df, missing_source_df, target_exists_df = generate_new_workflows(
        prepared_df,
        source_df,
        existing_target_names
    )

    upload_df = build_upload_output(generated_df)
    generation_audit_df = build_generation_audit(generated_df)

    generated_workflow_count = generated_df["WorkflowName"].nunique() if not generated_df.empty else 0

    print(f"Generated {generated_workflow_count} workflows with {len(upload_df)} workflow-step rows.")
    print(f"Missing source workflows: {len(missing_source_df)}.")
    print(f"Existing target workflows skipped: {len(target_exists_df)}.")
    print(f"Conflicting target inputs skipped: {len(conflict_df)}.")
    print(f"Blank Material/group counter rows skipped: {len(blank_key_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        upload_df.to_excel(writer, sheet_name="Workflow To Add", index=False)
        generation_audit_df.to_excel(writer, sheet_name="Generation Audit", index=False)
        missing_source_df.to_excel(writer, sheet_name="Source Workflow Not Found", index=False)
        target_exists_df.to_excel(writer, sheet_name="Target Already Exists", index=False)
        conflict_df.to_excel(writer, sheet_name="Conflicting Target", index=False)
        blank_key_df.to_excel(writer, sheet_name="Blank Material Counter", index=False)

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()