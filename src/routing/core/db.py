import os
from contextlib import contextmanager

import pandas as pd

from routing.core.config import BATCH_SIZE, SNOWFLAKE_CONNECTION


def snowflake_conn():
    import snowflake.connector
    return snowflake.connector.connect(connection_name=SNOWFLAKE_CONNECTION)


def mssql_conn():
    import pyodbc
    conn_str = (
        f"DRIVER={{{os.getenv('SQL_DRIVER', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={os.getenv('SQL_SERVER')};"
        f"DATABASE={os.getenv('SQL_DATABASE')};"
        f"UID={os.getenv('SQL_USERNAME')};"
        f"PWD={os.getenv('SQL_PASSWORD')};"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str)


@contextmanager
def snowflake_session(conn=None):
    """Use the given connection, or open one and close it afterwards."""
    if conn is not None:
        yield conn
        return
    own = snowflake_conn()
    try:
        yield own
    finally:
        own.close()


def query(conn, sql, params=None):
    """Run a Snowflake query with bound params (%s) and return a DataFrame.
    Decimals become floats, same as pd.read_sql."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params or [])
        columns = [c[0] for c in cur.description]
        return pd.DataFrame.from_records(cur.fetchall(), columns=columns, coerce_float=True)
    finally:
        cur.close()


def placeholders(values):
    return ", ".join(["%s"] * len(values))


def batches(values, size=BATCH_SIZE):
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def query_in_batches(conn, sql_template, values, params_before=(), params_after=(), columns=()):
    """Run sql_template once per batch of `values` and stack the results.
    sql_template must contain {placeholders} where the IN list goes.
    `columns` is the result shape to return when `values` is empty."""
    values = list(dict.fromkeys(values))
    frames = [
        query(conn, sql_template.format(placeholders=placeholders(batch)),
              [*params_before, *batch, *params_after])
        for batch in batches(values)
    ]
    if not frames:
        return pd.DataFrame(columns=list(columns))
    return pd.concat(frames, ignore_index=True)
