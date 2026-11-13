import pandas as pd

from routing.core.clean import (
    clean_material_series,
    clean_string,
    clean_tool,
    from_sap_matnr,
    to_sap_matnr,
    validate_input_columns,
)
from routing.core.db import batches, placeholders
from routing.core.excel import clean_path, with_suffix


def test_clean_string():
    assert clean_string(12345.0) == "12345"
    assert clean_string(" 12345.0 ") == "12345"
    assert clean_string(None) == ""
    assert clean_string(float("nan")) == ""


def test_clean_tool_blank_values():
    for value in ["0", "0.0", "NULL", "none", "nan", None]:
        assert clean_tool(value) == ""
    assert clean_tool("T123") == "T123"


def test_material_series():
    s = pd.Series([12345.0, "  678 ", "A1.0"])
    assert clean_material_series(s).tolist() == ["12345", "678", "A1"]


def test_sap_matnr_round_trip():
    assert to_sap_matnr("12345") == "000000000000012345"
    assert len(to_sap_matnr("1")) == 18
    assert from_sap_matnr("000000000000012345") == "12345"


def test_validate_input_columns():
    df = pd.DataFrame(columns=["Material"])
    validate_input_columns(df, ["Material"])
    try:
        validate_input_columns(df, ["Material", "Resource"])
    except ValueError as e:
        assert "Resource" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_batches_and_placeholders():
    assert [len(b) for b in batches(range(1201), 500)] == [500, 500, 201]
    assert placeholders([1, 2, 3]) == "%s, %s, %s"


def test_paths():
    assert clean_path(' "C:\\x\\a.xlsx" ') == "C:\\x\\a.xlsx"
    assert with_suffix("C:/x/input.xlsx", "_checked") == "C:/x/input_checked.xlsx"
