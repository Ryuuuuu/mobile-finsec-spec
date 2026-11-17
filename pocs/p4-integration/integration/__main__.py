"""Cloud-only CLI demonstrations of synthetic providers and existing P2/P3 tools."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .contracts import ContractError, Item, Plan
from .history import History, validate_final
from .supervisor import Supervisor


SCENARIOS = (
    "normal", "proxy-off", "main-error", "main-hang", "item-hang", "tool-timeout",
    "cancel", "ignored-cancel", "cleanup-failed", "disconnect",
)


def scenario_plan(scenario: str) -> Plan:
    normal = (Item("chk07-pass", "pass"), Item("chk07-fail", "fail"),
              Item("chk07-inconclusive", "inconclusive"))
    options = {}
    if scenario in {"normal", "proxy-off"}:
        items = normal
        options["proxy_on"] = scenario != "proxy-off"
    else:
        first = {}
        options.update(progress_timeout=0.1, heartbeat_timeout=0.12)
        if scenario == "main-error":
            options["main_behavior"] = "error"
        elif scenario == "main-hang":
            options["main_behavior"] = "hang"
        elif scenario in {"item-hang", "cancel"}:
            first["provider_behavior"] = "hang"
        elif scenario == "ignored-cancel":
            first["provider_behavior"] = "ignores_cancel"
        elif scenario == "tool-timeout":
            first["tool_fault"] = "timeout"
            options["tool_timeout"] = 0.15
        elif scenario == "cleanup-failed":
            first.update(variant="fail", cleanup_fault="failed")
        elif scenario == "disconnect":
            first["tool_fault"] = "disconnect"
        else:
            raise ContractError("UNKNOWN_DEMO_SCENARIO")
        items = (Item("chk07-first", **first), Item("chk07-pending", "pass"))
    return Plan(command_id="synthetic-demo-" + scenario, items=items, **options)


async def _cancel_when_item_started(supervisor, handle):
    """Use observed lifecycle events; never guess a provider startup delay."""
    first = handle.plan.items[0].item_id
    async with asyncio.timeout(handle.plan.run_timeout):
        while not handle.task.done():
            events = supervisor.events_after(handle.run_id)
            running = any(e["type"] == "item_running" and e["item_id"] == first for e in events)
            provider = any(e["type"] == "provider_started" and e["item_id"] == first
                           and e["payload"]["role"] == "item" for e in events)
            if running and provider:
                supervisor.cancel(handle.run_id)
                return
            await asyncio.sleep(0.001)
    raise ContractError("CANCEL_TARGET_NOT_REACHED")


def _exit_code(state, reason):
    if state == "completed":
        return 0
    if state == "cancelled":
        return 4
    if state != "finalizing_failed" and any(word in reason for word in ("TIMEOUT", "HANG", "HEARTBEAT")):
        return 3
    return 2


async def demo(scenario, output):
    plan = scenario_plan(scenario)
    output = Path(output).resolve()
    # mkdir is the exclusive admission gate; never reuse or replace old results.
    output.mkdir(parents=True, exist_ok=False)
    supervisor = Supervisor(output)
    try:
        handle = supervisor.start(plan)
        if scenario in {"cancel", "ignored-cancel"}:
            await _cancel_when_item_started(supervisor, handle)
        await handle.task
        result = handle.result
        reason = result["reason_code"] if result else handle.error_code or "FINALIZATION_FAILED"
        summary = {
            "schema_version": "1.0", "synthetic": True, "scenario": scenario,
            "state": handle.state, "run_id": handle.run_id,
            "output": str(handle.output), "workspace": str(output),
            "verdict_counts": result["verdict_counts"] if result else None,
            "reason_code": reason, "recovery": handle.recovery_required,
        }
        return summary, _exit_code(handle.state, reason)
    finally:
        # This can wait for the finite ignored-cancel fake. Persisted quarantine
        # and sealed results remain unchanged even if that fake eventually exits.
        await supervisor.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("demo", help="run one synthetic scenario into a NEW output directory")
    run.add_argument("--scenario", choices=SCENARIOS, default="normal")
    run.add_argument("--output", type=Path, required=True)
    history = commands.add_parser("history", help="read sealed final results; excludes live events")
    history.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate", help="verify a run's final result and real P2/P3 references")
    validate.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == "demo":
            value, code = asyncio.run(demo(args.scenario, args.output))
        elif args.command == "history":
            path = args.output / "history.sqlite"
            if not path.is_file() or path.is_symlink():
                raise ContractError("HISTORY_NOT_FOUND")
            value = History(path).list()
        else:
            root = args.run.resolve()
            run_data = json.loads((root / "run.json").read_text(encoding="utf-8"))
            result = json.loads((root / "final.json").read_text(encoding="utf-8"))
            if result["run_id"] != run_data["run_id"] or result["session_id"] != run_data["session_id"]:
                raise ContractError("RUN_SNAPSHOT_MISMATCH")
            validate_final(result, root=root, snapshot=run_data["contract_snapshot"])
            value = {"schema_version": "1.0", "synthetic": True, "valid": True,
                     "run_id": result["run_id"]}
    except FileExistsError:
        value, code = {"synthetic": True, "state": "command_error", "reason_code": "OUTPUT_EXISTS"}, 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        # Do not copy arbitrary exception text or supplied file content to logs.
        value, code = {"synthetic": True, "state": "command_error", "reason_code": "COMMAND_OR_VALIDATION_ERROR"}, 2
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
