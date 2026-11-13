"""Command line entry point.

    routing pre-uipath FILE
    routing check routing-condition FILE [-o OUT]
    routing opc add-tpm [-i FILE] [-o OUT]
    routing list

FILE is optional: when missing you are asked for it (drag & drop works).
Exit code 0 = success, 1 = error (for UiPath).
"""
import argparse
import importlib
import sys
import traceback

from routing.core.excel import ask_path

# command -> (module, function, accepts sheet_name)
CHECKS = {
    "routing-condition": ("routing.checks.routing_condition", "run", False),
    "alt-bom": ("routing.checks.alt_bom", "run", False),
    "delete-status": ("routing.checks.delete_status", "run", False),
    "operation-capacity": ("routing.checks.operation_capacity", "run", True),
    "util-eff": ("routing.checks.util_eff", "run", True),
    "routings-by-tool": ("routing.checks.routings_by_tool", "run", False),
    "tpm-exist": ("routing.checks.tpm_exist", "run", True),
    "pv-count": ("routing.checks.production_version", "run_count", True),
    "pv-by-group": ("routing.checks.production_version", "run_by_group", True),
    "pv-by-attributes": ("routing.checks.production_version", "run_by_attributes", True),
    "pv-fallback": ("routing.checks.production_version", "run_with_fallback", True),
}

OPC = {
    "add-tpm": "routing.opc.add_tpm",
    "add-workflow": "routing.opc.add_workflow",
    "compare-workflow": "routing.opc.compare_workflow",
    "delete-tpm": "routing.opc.delete_tpm",
    "update-ideal-cycle-time": "routing.opc.update_ideal_cycle_time",
    "update-tpm-priority": "routing.opc.update_tpm_priority",
}

# run() functions without an output_path argument
NO_OUTPUT = {"util-eff"}


def _load(module, function):
    return getattr(importlib.import_module(module), function)


def run_check(name, file=None, output=None, sheet=None):
    module, function, has_sheet = CHECKS[name]
    kwargs = {}
    if output and name not in NO_OUTPUT:
        kwargs["output_path"] = output
    if sheet is not None and has_sheet:
        kwargs["sheet_name"] = sheet
    return _load(module, function)(file or ask_path(), **kwargs)


def run_opc(name, file=None, output=None):
    module = importlib.import_module(OPC[name])
    return module.main(input_file=file or module.INPUT_FILE, output_file=output or module.OUTPUT_FILE)


def build_parser():
    parser = argparse.ArgumentParser(prog="routing", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("pre-uipath", help="routing condition -> alt BOM count (before UiPath)")
    pre.add_argument("file", nargs="?")
    pre.add_argument("-o", "--output")

    check = sub.add_parser("check", help="run one Snowflake / OpCenter check")
    check.add_argument("name", choices=sorted(CHECKS))
    check.add_argument("file", nargs="?")
    check.add_argument("-o", "--output")
    check.add_argument("--sheet", help="sheet name (checks that read one sheet)")

    opc = sub.add_parser("opc", help="generate an OpCenter upload file")
    opc.add_argument("name", choices=sorted(OPC))
    opc.add_argument("-i", "--input", help="input Excel (default: INPUT_FILE in the script)")
    opc.add_argument("-o", "--output", help="output Excel (default: output/<name>.xlsx)")

    sub.add_parser("list", help="show all commands")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pre-uipath":
            from routing.pipelines.pre_uipath import run
            run(args.file or ask_path(), output_path=args.output)
        elif args.command == "check":
            run_check(args.name, args.file, args.output, args.sheet)
        elif args.command == "opc":
            run_opc(args.name, args.input, args.output)
        elif args.command == "list":
            print("pre-uipath\n" + "\n".join(f"check {n}" for n in sorted(CHECKS))
                  + "\n" + "\n".join(f"opc {n}" for n in sorted(OPC)))
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def legacy_script(name):
    """Entry for root scripts, e.g. `python pre_uipath.py [FILE]`."""
    try:
        if name == "pre-uipath":
            from routing.pipelines.pre_uipath import run
            run(sys.argv[1] if len(sys.argv) > 1 else ask_path())
        else:
            run_check(name, sys.argv[1] if len(sys.argv) > 1 else None)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    sys.exit(main())
