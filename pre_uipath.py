"""Run before the UiPath routing automation: routing condition -> alt BOM count.

    python pre_uipath.py FILE        (or: routing pre-uipath FILE)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

if __name__ == "__main__":
    from routing.cli import legacy_script
    legacy_script("pre-uipath")
