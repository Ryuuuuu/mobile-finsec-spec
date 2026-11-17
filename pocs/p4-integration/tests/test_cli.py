"""Real CLI subprocess acceptance: synthetic loopback only, no user/device data."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p4-cli-")
        self.output = Path(self.temp.name) / "new-workspace"

    def tearDown(self):
        self.temp.cleanup()

    def command(self, *arguments, expected=0):
        process = subprocess.run([sys.executable, "-m", "integration", *map(str, arguments)],
                                 cwd=ROOT, text=True, capture_output=True, timeout=25)
        self.assertEqual(process.returncode, expected, (process.stdout, process.stderr))
        self.assertEqual(process.stderr, "", process.stderr)
        return json.loads(process.stdout)

    def demo(self, scenario="normal", expected=0, output=None):
        report = self.command("demo", "--scenario", scenario, "--output", output or self.output,
                              expected=expected)
        self.assertTrue(report["synthetic"])
        return report

    def final(self, report):
        return json.loads((Path(report["output"]) / "final.json").read_text())

    def test_normal_three_verdicts_final_only_history_and_validation(self):
        report = self.demo()
        self.assertEqual(report["state"], "completed")
        self.assertEqual(report["verdict_counts"], {"pass": 1, "fail": 1, "inconclusive": 1})
        self.assertFalse(report["recovery"])
        result = self.final(report)
        self.assertEqual(result["p2"]["persisted_packets"], 1)
        self.assertEqual([r["execution_status"] for r in result["items"]], ["completed"] * 3)
        validated = self.command("validate", "--run", report["output"])
        self.assertTrue(validated["valid"])
        self.assertEqual(validated["run_id"], report["run_id"])
        history = self.command("history", "--output", self.output)
        self.assertEqual(history, [result])
        self.assertNotIn("events", history[0])
        self.assertNotIn("heartbeat", history[0])

    def test_proxy_off_is_none_while_independent_chk07_still_runs(self):
        report = self.demo("proxy-off")
        result = self.final(report)
        self.assertEqual(result["p2"]["network_coverage"], "none")
        self.assertEqual(result["p2"]["packet_ids"], [])
        self.assertEqual(report["verdict_counts"], {"pass": 1, "fail": 1, "inconclusive": 1})

    def test_tool_timeout_preserves_not_run_followup_and_releases_after_cleanup(self):
        report = self.demo("tool-timeout", expected=3)
        self.assertEqual(report["reason_code"], "TOOL_TIMEOUT")
        self.assertEqual(report["state"], "failed")
        self.assertFalse(report["recovery"])
        self.assertEqual([r["execution_status"] for r in self.final(report)["items"]],
                         ["timed_out", "not_run"])

    def test_cancel_waits_for_observed_item_start_and_leaves_no_followup(self):
        report = self.demo("cancel", expected=4)
        self.assertEqual(report["reason_code"], "RUN_CANCELLED")
        self.assertFalse(report["recovery"])
        self.assertEqual([r["execution_status"] for r in self.final(report)["items"]],
                         ["cancelled", "not_run"])

    def test_ignored_cancel_persists_recovery_even_after_finite_fake_exits(self):
        report = self.demo("ignored-cancel", expected=4)
        self.assertTrue(report["recovery"])
        self.assertEqual(self.final(report)["cleanup_status"], "unknown")
        history = self.command("history", "--output", self.output)
        self.assertTrue(history[0]["recovery_required"])

    def test_cleanup_failure_preserves_proven_vulnerability_and_blocks_followup(self):
        report = self.demo("cleanup-failed", expected=2)
        self.assertTrue(report["recovery"])
        self.assertEqual(report["reason_code"], "CLEANUP_FAILED")
        rows = self.final(report)["items"]
        self.assertEqual(rows[0]["verdict"], "fail")
        self.assertEqual(rows[0]["cleanup_status"], "failed")
        self.assertEqual(rows[1]["execution_status"], "not_run")

    def test_main_and_item_faults_have_distinct_reason_codes(self):
        for scenario, expected, reason in (("main-error", 2, "MAIN_ERROR"),
                                           ("main-hang", 3, "MAIN_HANG"),
                                           ("item-hang", 3, "ITEM_HANG")):
            with self.subTest(scenario=scenario):
                report = self.demo(scenario, expected, Path(self.temp.name) / scenario)
                self.assertEqual(report["reason_code"], reason)
                self.assertEqual(report["verdict_counts"], {"pass": 0, "fail": 0, "inconclusive": 2})

    def test_fake_disconnect_requires_recovery(self):
        report = self.demo("disconnect", expected=2)
        self.assertEqual(report["reason_code"], "DEVICE_DISCONNECTED")
        self.assertTrue(report["recovery"])
        self.assertEqual(self.final(report)["items"][1]["execution_status"], "not_run")

    def test_existing_output_is_rejected_without_overwriting_result(self):
        report = self.demo("proxy-off")
        path = Path(report["output"]) / "final.json"
        original = path.read_bytes()
        duplicate = self.command("demo", "--output", self.output, expected=2)
        self.assertEqual(duplicate["reason_code"], "OUTPUT_EXISTS")
        self.assertEqual(path.read_bytes(), original)

    def test_validation_rejects_corrupted_final_and_missing_history(self):
        self.command("history", "--output", self.output, expected=2)
        self.assertFalse(self.output.exists())
        report = self.demo("proxy-off")
        path = Path(report["output"]) / "final.json"
        result = json.loads(path.read_text())
        result["items"][0]["verdict"] = "fail"
        path.write_text(json.dumps(result))
        failed = self.command("validate", "--run", report["output"], expected=2)
        self.assertEqual(failed["state"], "command_error")


if __name__ == "__main__":
    unittest.main()
