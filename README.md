# ROUTING

SAP routing checks (Snowflake) that run before the UiPath routing automation, and
OpCenter upload-file generators (Tool Plan Matrix, workflows).

## Setup (once)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env      # fill in the OpCenter SQL Server values
```

`pip install -e .` makes `routing` importable from any folder and adds the `routing` command.
Snowflake uses the `default` connection from your Snowflake `connections.toml`.

## Before UiPath

```powershell
routing pre-uipath C:\path\input.xlsx
# or, without installing:
python pre_uipath.py C:\path\input.xlsx
```

Runs routing condition, then alt BOM count, on one Snowflake connection and writes the
results back to the file (`SKIP`, `SKIP_REASON`, `group`, `group counter`, `ALT_BOM_COUNT`).
Exit code `0` = success, `1` = error, so UiPath can branch on it.

## All commands

```powershell
routing list
routing check routing-condition FILE [-o OUT]
routing check alt-bom FILE
routing check delete-status FILE
routing check operation-capacity FILE [--sheet Sheet1]
routing check util-eff FILE
routing check routings-by-tool FILE
routing check tpm-exist FILE
routing check pv-count | pv-by-group | pv-by-attributes | pv-fallback FILE
routing opc add-tpm | add-workflow | compare-workflow | delete-tpm |
            update-ideal-cycle-time | update-tpm-priority  [-i INPUT] [-o OUTPUT]
```

If FILE is left out you are asked for it (drag & drop works).

## Use from other code

```python
from routing.checks.routing_condition import check_routing_exists
from routing.pipelines.pre_uipath import pre_uipath_checks

df = pre_uipath_checks(df)            # DataFrame in, DataFrame out
```

Every check has a pure `check_xxx(df, conn=None, plant=PLANT)` function and a `run(path)`
wrapper that reads and writes Excel. Pass `conn` to reuse one Snowflake connection.

## Layout

| Folder | Contains |
|---|---|
| `src/routing/core/` | config (plant, connection name, paths), DB connections, cleaning, Excel I/O |
| `src/routing/data/` | SQL queries only, one file per topic, return DataFrames |
| `src/routing/checks/` | pre-UiPath checks (business logic) |
| `src/routing/opc/` | OpCenter upload-file generators, see `docs/opc.md` |
| `src/routing/pipelines/` | chained checks (`pre_uipath`) |
| `src/routing/cli.py` | the `routing` command |
| `sql/`, `notebooks/`, `docs/` | ad-hoc SQL, notebook, notes |
| `tests/` | `pytest` (no Snowflake needed) |
| `output/` | generated Excel files (git-ignored) |

Rules: imports only go downward (cli -> checks/opc -> data -> core); queries use bound
parameters, never values pasted into SQL; plant / connection / paths come from `core/config.py`
or `.env` (`ROUTING_PLANT`, `SNOWFLAKE_CONNECTION`, `ROUTING_OUTPUT_DIR`).

## Tests

```powershell
pytest
```
