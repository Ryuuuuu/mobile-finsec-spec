"""Run only the active structural suites; exclude historical P3 judgement tests."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    'test_http_child.py', 'test_loopback_api.py', 'test_stdio_recordings.py', 'test_stdio_cleanup.py', 'test_stdio_client.py', 'test_mock_stdio.py', 'test_ui_wire.py', 'test_ui_bridge.py', 'test_integrated_structure.py',
    'test_start_api.py', 'test_run_journal.py', 'test_packet_access.py',
    'test_artifact_reader.py', 'test_recording_context.py',
    'test_structure_supervisor.py', 'test_skill_structure.py',
    'test_ollama_http.py', 'test_providers.py', 'test_lease.py',
)

if __name__ == '__main__':
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.discover('tests', pattern=p) for p in PATTERNS)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
