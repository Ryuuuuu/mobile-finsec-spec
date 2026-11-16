"""Small synthetic-only CLI. Exit status reports execution, never security verdict."""

import argparse
import json
import sys

from .engine import run, validate_bundle
from .protocol import ContractError, load_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="CHK-07 synthetic fixture PoC; no real device adapter")
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run", help="evaluate a synthetic fixture into a NEW output directory")
    execute.add_argument("--input", required=True)
    execute.add_argument("--output", required=True)
    execute.add_argument("--cancel", action="store_true", help="synthetic pre-start cancellation")
    verify = commands.add_parser("validate", help="check a finalized synthetic bundle without mutation")
    verify.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(load_json(args.input), args.output, cancel=args.cancel) if args.command == "run" else validate_bundle(args.output)
    except (ContractError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, ContractError) else "STORAGE_OR_INPUT_IO_ERROR"
        print(json.dumps({"schema_version": "1.0", "synthetic": True, "source": "synthetic_fixture",
                          "command_status": "error", "reason_code": code}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"schema_version": "1.0", "synthetic": True, "source": "synthetic_fixture",
                      "command_status": "validated" if args.command == "validate" else "finalized",
                      "run_id": result["run_id"], "execution_status": result["execution_status"],
                      "verdict": result["verdict"], "reason_code": result["reason_code"],
                      "cleanup_status": result["cleanup_status"], "follow_up_blocked": result["follow_up_blocked"]}, ensure_ascii=False))
    if args.command == "validate":
        return 0
    return {"completed": 0, "failed": 2, "timed_out": 3, "cancelled": 4, "not_run": 5}[result["execution_status"]]


if __name__ == "__main__":
    raise SystemExit(main())
