from pathlib import Path

import pandas as pd

from tpm_common import clean_string, get_sql_connection, validate_input_columns


# ============================================================
# CONFIG
# ============================================================

INPUT_FILE = Path(r"C:\Users\nguyeb3\Downloads\master\add_routing_chau.xlsx")
OUTPUT_FILE = Path("output/workflow_comparison.xlsx")

REQUIRED_COLUMNS = ["Material", "group counter"]

STEP_COLUMNS = [
    "Material",
    "WorkflowName",
    "WorkflowRevision",
    "StepName",
    "RouteStepId",
    "RouteStepName",
    "Sequence",
    "ERPRouteName"
]

# ============================================================
# PREPARE INPUT
# ============================================================

def prepare_input(input_df):
    prepared_df = input_df.copy()

    prepared_df["Material"] = prepared_df["Material"].apply(clean_string)
    prepared_df["group counter"] = prepared_df["group counter"].apply(clean_string)

    blank_key_df = prepared_df[(prepared_df["Material"] == "") | (prepared_df["group counter"] == "")].copy()
    prepared_df = prepared_df[(prepared_df["Material"] != "") & (prepared_df["group counter"] != "")].copy()

    prepared_df["TargetWorkflowName"] = prepared_df["Material"] + "-" + prepared_df["group counter"]

    conflict_targets = prepared_df.groupby("TargetWorkflowName")["Material"].nunique()
    conflict_targets = conflict_targets[conflict_targets > 1].index

    conflict_df = prepared_df[prepared_df["TargetWorkflowName"].isin(conflict_targets)].copy()
    prepared_df = prepared_df[~prepared_df["TargetWorkflowName"].isin(conflict_targets)].drop_duplicates(subset=["TargetWorkflowName"], keep="last").copy()

    return prepared_df, blank_key_df, conflict_df


# ============================================================
# CLEAN WORKFLOW RESULTS
# ============================================================

def clean_workflow_df(workflow_df):
    if workflow_df.empty:
        return workflow_df

    for column in ["Material", "WorkflowName", "WorkflowRevision", "StepName", "RouteStepId", "RouteStepName", "ERPRouteName"]:
        workflow_df[column] = workflow_df[column].apply(clean_string)

    workflow_df["Sequence"] = pd.to_numeric(workflow_df["Sequence"], errors="coerce")
    return workflow_df


# ============================================================
# FETCH TARGET WORKFLOWS
# ============================================================

def fetch_target_workflows(target_workflows):
    target_workflows = list(dict.fromkeys(clean_string(name) for name in target_workflows if clean_string(name)))

    if not target_workflows:
        return pd.DataFrame(columns=STEP_COLUMNS)

    placeholders = ",".join(["?"] * len(target_workflows))

    query = f"""
    SELECT
        LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) AS Material,
        wfb.WorkflowName,
        wf.WorkflowRevision,
        ws.WorkflowStepName AS StepName,
        ws.RouteStepId,
        rs.Name AS RouteStepName,
        ws.Sequence,
        erb.ERPRouteName
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

    ORDER BY wfb.WorkflowName, ws.Sequence
    """

    with get_sql_connection() as conn:
        target_df = pd.read_sql(query, conn, params=target_workflows)

    return clean_workflow_df(target_df)


# ============================================================
# FETCH ONE SOURCE WORKFLOW PER MATERIAL
# ============================================================

def fetch_source_workflows(materials, target_workflows):
    materials = list(dict.fromkeys(clean_string(material) for material in materials if clean_string(material)))
    target_workflows = list(dict.fromkeys(clean_string(name) for name in target_workflows if clean_string(name)))

    if not materials:
        return pd.DataFrame(columns=STEP_COLUMNS + ["TargetWorkflowName"])

    material_placeholders = ",".join(["?"] * len(materials))
    target_filter = ""

    if target_workflows:
        target_placeholders = ",".join(["?"] * len(target_workflows))
        target_filter = f"AND wfb.WorkflowName NOT IN ({target_placeholders})"

    query = f"""
    WITH WorkflowCandidates AS (
        SELECT
            LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) AS Material,
            wfb.WorkflowName,
            wf.WorkflowId,
            wf.WorkflowRevision,
            wf.ERPRouteId,
            wf.ERPRouteBaseId,

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

        WHERE LEFT(wfb.WorkflowName, CHARINDEX('-', wfb.WorkflowName + '-') - 1) IN ({material_placeholders})
        {target_filter}
    ),

    SelectedWorkflow AS (
        SELECT *
        FROM WorkflowCandidates
        WHERE SourceRank = 1
    )

    SELECT
        selected.Material,
        selected.WorkflowName,
        selected.WorkflowRevision,
        ws.WorkflowStepName AS StepName,
        ws.RouteStepId,
        rs.Name AS RouteStepName,
        ws.Sequence,
        erb.ERPRouteName
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

    ORDER BY selected.Material, selected.WorkflowName, ws.Sequence
    """

    params = materials + target_workflows

    with get_sql_connection() as conn:
        source_df = pd.read_sql(query, conn, params=params)

    return clean_workflow_df(source_df)


# ============================================================
# DUPLICATE SEQUENCE CHECK
# ============================================================

def prepare_steps(workflow_df, workflow_type):
    if workflow_df.empty:
        return workflow_df.copy(), pd.DataFrame()

    counts = workflow_df.groupby(["WorkflowName", "Sequence"], dropna=False).size().reset_index(name="RowCount")
    duplicate_keys = counts[counts["RowCount"] > 1][["WorkflowName", "Sequence"]]

    duplicate_df = workflow_df.merge(duplicate_keys, on=["WorkflowName", "Sequence"], how="inner")
    duplicate_df["WorkflowType"] = workflow_type

    prepared_df = workflow_df.drop_duplicates(subset=["WorkflowName", "Sequence"], keep="first").copy()
    return prepared_df, duplicate_df


# ============================================================
# COMPARE WORKFLOW STEPS
# ============================================================

def compare_workflows(prepared_df, target_df, source_df):
    target_df, target_duplicate_df = prepare_steps(target_df, "Target")
    source_df, source_duplicate_df = prepare_steps(source_df, "Source")

    target_map = prepared_df[["Material", "TargetWorkflowName"]].drop_duplicates()
    target_df = target_map.merge(target_df, left_on=["Material", "TargetWorkflowName"], right_on=["Material", "WorkflowName"], how="left")
    target_df = target_df.drop(columns="WorkflowName").rename(columns={
        "WorkflowRevision": "TargetRevision",
        "StepName": "TargetStepName",
        "RouteStepId": "TargetRouteStepId",
        "RouteStepName": "TargetRouteStepName",
        "ERPRouteName": "TargetERPRouteName"
    })

    source_df = source_df.rename(columns={
        "WorkflowName": "SourceWorkflowName",
        "WorkflowRevision": "SourceRevision",
        "StepName": "SourceStepName",
        "RouteStepId": "SourceRouteStepId",
        "RouteStepName": "SourceRouteStepName",
        "ERPRouteName": "SourceERPRouteName"
    })

    comparison_df = target_df.merge(source_df, on=["Material", "Sequence"], how="outer", indicator=True)

    comparison_df["TargetStepClean"] = comparison_df["TargetStepName"].apply(clean_string)
    comparison_df["SourceStepClean"] = comparison_df["SourceStepName"].apply(clean_string)
    comparison_df["StepNameMatch"] = comparison_df["TargetStepClean"] == comparison_df["SourceStepClean"]

    comparison_df["ComparisonStatus"] = "Matched"
    comparison_df.loc[comparison_df["_merge"] == "left_only", "ComparisonStatus"] = "Sequence only in target"
    comparison_df.loc[comparison_df["_merge"] == "right_only", "ComparisonStatus"] = "Sequence only in source"
    comparison_df.loc[(comparison_df["_merge"] == "both") & (~comparison_df["StepNameMatch"]), "ComparisonStatus"] = "StepName mismatch"

    comparison_df = comparison_df.drop(columns=["TargetStepClean", "SourceStepClean", "_merge"])
    comparison_df = comparison_df.sort_values(by=["Material", "TargetWorkflowName", "Sequence"], na_position="last")

    duplicate_df = pd.concat([target_duplicate_df, source_duplicate_df], ignore_index=True)
    return comparison_df, duplicate_df


# ============================================================
# WORKFLOW SUMMARY
# ============================================================

def build_summary(comparison_df):
    if comparison_df.empty:
        return pd.DataFrame(columns=[
            "Material",
            "TargetWorkflowName",
            "SourceWorkflowName",
            "TotalComparedRows",
            "MatchedRows",
            "MismatchRows",
            "WorkflowMatch"
        ])

    summary_df = (
        comparison_df.groupby(
            ["Material", "TargetWorkflowName", "SourceWorkflowName"],
            dropna=False
        )
        .agg(
            TotalComparedRows=("ComparisonStatus", "size"),
            MatchedRows=("ComparisonStatus", lambda values: (values == "Matched").sum()),
            MismatchRows=("ComparisonStatus", lambda values: (values != "Matched").sum())
        )
        .reset_index()
    )

    summary_df["WorkflowMatch"] = summary_df["MismatchRows"] == 0
    return summary_df


# ============================================================
# MISSING WORKFLOW CHECKS
# ============================================================

def build_missing_workflows(prepared_df, target_df, source_df):
    target_found = set(target_df["WorkflowName"].apply(clean_string)) if not target_df.empty else set()
    source_found = set(source_df["Material"].apply(clean_string)) if not source_df.empty else set()

    missing_target_df = prepared_df[
        ~prepared_df["TargetWorkflowName"].isin(target_found)
    ][["Material", "group counter", "TargetWorkflowName"]].copy()

    missing_target_df["Reason"] = "Target workflow not found"

    missing_source_df = prepared_df[
        ~prepared_df["Material"].isin(source_found)
    ][["Material", "group counter", "TargetWorkflowName"]].copy()

    missing_source_df["Reason"] = "Source workflow not found after excluding target workflow"

    return missing_target_df, missing_source_df


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    print("Reading workflow comparison input...")

    input_df = pd.read_excel(INPUT_FILE, dtype=str)
    validate_input_columns(input_df, REQUIRED_COLUMNS)

    prepared_df, blank_key_df, conflict_df = prepare_input(input_df)

    materials = prepared_df["Material"].drop_duplicates().tolist()
    target_workflows = prepared_df["TargetWorkflowName"].drop_duplicates().tolist()

    print(f"Found {len(materials)} materials and {len(target_workflows)} target workflows.")
    print("Loading target workflows...")

    target_df = fetch_target_workflows(target_workflows)

    print(f"Found {target_df['WorkflowName'].nunique() if not target_df.empty else 0} target workflows with {len(target_df)} step rows.")
    print("Loading one source workflow per material...")

    source_df = fetch_source_workflows(materials, target_workflows)

    print(f"Found {source_df['WorkflowName'].nunique() if not source_df.empty else 0} source workflows with {len(source_df)} step rows.")

    missing_target_df, missing_source_df = build_missing_workflows(prepared_df, target_df, source_df)
    comparison_df, duplicate_sequence_df = compare_workflows(prepared_df, target_df, source_df)
    summary_df = build_summary(comparison_df)

    print(f"Comparison rows: {len(comparison_df)}.")
    print(f"Matched rows: {(comparison_df['ComparisonStatus'] == 'Matched').sum() if not comparison_df.empty else 0}.")
    print(f"Mismatched rows: {(comparison_df['ComparisonStatus'] != 'Matched').sum() if not comparison_df.empty else 0}.")
    print(f"Missing target workflows: {len(missing_target_df)}.")
    print(f"Missing source workflows: {len(missing_source_df)}.")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        comparison_df.to_excel(writer, sheet_name="Step Comparison", index=False)
        summary_df.to_excel(writer, sheet_name="Workflow Summary", index=False)
        target_df.to_excel(writer, sheet_name="Target Workflow Steps", index=False)
        source_df.to_excel(writer, sheet_name="Source Workflow Steps", index=False)
        missing_target_df.to_excel(writer, sheet_name="Target Not Found", index=False)
        missing_source_df.to_excel(writer, sheet_name="Source Not Found", index=False)
        duplicate_sequence_df.to_excel(writer, sheet_name="Duplicate Sequence", index=False)
        conflict_df.to_excel(writer, sheet_name="Conflicting Input", index=False)
        blank_key_df.to_excel(writer, sheet_name="Blank Material Counter", index=False)

    print(f"Finished: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()