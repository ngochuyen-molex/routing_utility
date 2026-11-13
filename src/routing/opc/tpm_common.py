"""Helpers shared by the OpCenter TPM generators.
clean / validate / connection helpers live in routing.core; TPM query in routing.data.tpm."""
from routing.core.clean import clean_string, clean_tool, validate_input_columns  # noqa: F401 (re-exported)
from routing.core.db import mssql_conn as get_sql_connection  # noqa: F401 (re-exported)
from routing.data.tpm import OUTPUT_COLUMNS, fetch_existing_tool_plan_matrix  # noqa: F401 (re-exported)


def add_material_resource_key(
    df,
    material_column,
    resource_column,
    key_column="_key"
):
    result_df = df.copy()

    material = result_df[material_column].apply(clean_string)
    resource = result_df[resource_column].apply(clean_string)

    result_df[key_column] = material + "_" + resource

    return result_df


def get_missing_input_rows(
    input_df,
    existing_df,
    input_material_column="Material",
    input_resource_column="Resource"
):
    keyed_input = add_material_resource_key(
        input_df,
        input_material_column,
        input_resource_column
    )

    keyed_existing = add_material_resource_key(
        existing_df,
        "Name",
        "Resource"
    )

    existing_keys = set(keyed_existing["_key"])

    return (
        keyed_input[~keyed_input["_key"].isin(existing_keys)]
        .drop(columns="_key")
        .drop_duplicates(
            subset=[input_material_column, input_resource_column]
        )
        .copy()
    )