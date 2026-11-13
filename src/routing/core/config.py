import os
from pathlib import Path

from dotenv import load_dotenv

# repo root = src/routing/core/config.py -> up 3
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

PLANT = os.getenv("ROUTING_PLANT", "1901")
SNOWFLAKE_CONNECTION = os.getenv("SNOWFLAKE_CONNECTION", "default")

OUTPUT_DIR = Path(os.getenv("ROUTING_OUTPUT_DIR", PROJECT_ROOT / "output"))

EFFICIENCY_FILE = Path(
    r"\\MLXVHAVWPAPP2\MXV_Shared\PUBLIC\OperationGroup(OPG)\DATA_OE\huyen_data\Eff_Util_workcenter.xlsx"
)

# Max values per IN (...) list in one query
BATCH_SIZE = 500
