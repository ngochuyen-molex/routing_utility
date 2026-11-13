"""Check logic with a fake connection: no Snowflake needed."""
import pandas as pd

from routing.checks import alt_bom, routing_condition
from routing.pipelines import pre_uipath


class FakeCursor:
    def __init__(self, responses):
        self.responses = responses
        self.description = None
        self._rows = []
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))
        for key, (columns, rows) in self.responses.items():
            if key in sql:
                self.description = [(c,) for c in columns]
                self._rows = rows
                return
        raise AssertionError(f"unexpected SQL: {sql[:80]}")

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class FakeConn:
    def __init__(self, responses):
        self.cur = FakeCursor(responses)

    def cursor(self):
        return self.cur


MAT = "000000000000012345"
RESPONSES = {
    "SELECT DISTINCT mp.MATNR\n": (["MATNR"], [(MAT,)]),
    "pk.KTEXT AS ROUTING_DESCRIPTION": (
        ["MATNR", "RESOURCE", "ROUTING_DESCRIPTION", "ROUTING_GROUP", "GROUP_COUNTER"],
        [(MAT, "MD01", "MD01 T555 production", "M0001", "02")]),
    "ALT_BOM_COUNT": (["MATNR", "ALT_BOM_COUNT"], [(MAT, 2)]),
}


def input_df():
    return pd.DataFrame({
        "Material": [12345.0, 12345.0, 12345.0, 99999.0],
        "Resource": ["MD01", "MD01", "MD02", "MD01"],
        "Tool": ["T555", "T777", "", ""],
    })


def test_routing_condition_flags():
    out = routing_condition.check_routing_exists(input_df(), conn=FakeConn(RESPONSES))
    assert out["SKIP"].tolist() == [1, 0, 0, 2]
    assert out.loc[0, "group"] == "M0001"
    assert out.loc[0, "group counter"] == "2"
    assert out["SKIP_REASON"].tolist()[-1] == "Material not at plant"


def test_queries_use_bound_params():
    conn = FakeConn(RESPONSES)
    routing_condition.check_routing_exists(input_df(), conn=conn)
    for sql, params in conn.cur.executed:
        assert MAT not in sql          # material is a parameter, not pasted into SQL
        assert "1901" in params


def test_alt_bom_count_fills_zero():
    df = pd.DataFrame({"Material": ["12345", "99999"]})
    out = alt_bom.check_alt_bom_count(df, conn=FakeConn(RESPONSES))
    assert out["ALT_BOM_COUNT"].tolist() == [2, 0]


def test_pre_uipath_adds_both_results():
    out = pre_uipath.pre_uipath_checks(input_df(), conn=FakeConn(RESPONSES))
    assert {"SKIP", "SKIP_REASON", "ALT_BOM_COUNT"} <= set(out.columns)
    assert out["ALT_BOM_COUNT"].tolist() == [2, 2, 2, 0]
