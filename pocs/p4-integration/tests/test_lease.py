"""Synthetic lease and fencing tests, including independent process contention."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from integration.lease import DEVICE_ID, LeaseError, LeaseStore


def _acquire_in_process(path, index, gate, results):
    store = LeaseStore(path)
    gate.wait(10)
    token = store.acquire(f"synthetic-process-{index}", f"boot-{index}")
    results.put(token is not None)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "state.sqlite"
        self.store = LeaseStore(self.path)

    def token(self):
        return self.store.acquire("synthetic-run-one", "boot-one")

    def assert_code(self, code, method, *args, **kwargs):
        with self.assertRaises(LeaseError) as caught:
            method(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_lease_requires_explicit_revoke_and_proven_cleanup(self):
        token = self.token()
        self.assertEqual(token.device_id, DEVICE_ID)
        self.assertEqual(token.generation, 1)
        self.assertTrue(self.store.authorize(token, "p2.capture"))
        self.assert_code("INVALID_LEASE_TRANSITION", self.store.release,
                         token, True, "completed")
        self.store.begin_cleanup(token)
        self.assert_code("LEASE_REVOKED", self.store.authorize, token, "p2.capture")
        self.assertTrue(self.store.release(token, True, "completed"))
        self.assertEqual(self.store.inspect()["lifecycle"], "free")

    def test_ten_concurrent_managers_have_only_one_owner(self):
        def acquire(index):
            return LeaseStore(self.path).acquire(f"synthetic-run-{index}", f"boot-{index}")
        with ThreadPoolExecutor(max_workers=10) as pool:
            tokens = list(pool.map(acquire, range(10)))
        self.assertEqual(sum(token is not None for token in tokens), 1)
        self.assertEqual(self.store.inspect()["generation"], 1)

    def test_independent_processes_cannot_both_acquire(self):
        context = multiprocessing.get_context("spawn")
        gate, results = context.Event(), context.Queue()
        workers = [context.Process(target=_acquire_in_process,
                                   args=(self.path, i, gate, results)) for i in range(4)]
        try:
            for worker in workers:
                worker.start()
            gate.set()
            observed = [results.get(timeout=15) for _ in workers]
            self.assertEqual(observed.count(True), 1)
            for worker in workers:
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(5)
            results.close()
            results.join_thread()

    def test_active_restart_never_steals_ownership(self):
        token = self.token()
        reopened = LeaseStore(self.path)
        self.assertIsNone(reopened.acquire("synthetic-run-two", "boot-two"))
        self.assertEqual(reopened.inspect()["boot_epoch"], token.boot_epoch)

    def test_cleaning_restart_still_blocks(self):
        token = self.token()
        self.store.begin_cleanup(token)
        self.assertIsNone(LeaseStore(self.path).acquire("synthetic-run-two", "boot-two"))
        self.assertEqual(self.store.inspect()["lifecycle"], "cleaning")

    def test_cleanup_failure_is_durable_quarantine(self):
        for status in ("failed", "unknown"):
            with self.subTest(status=status):
                store = LeaseStore(Path(self.temp.name) / (status + ".sqlite"))
                token = store.acquire("synthetic-run-one", "boot-one")
                store.begin_cleanup(token)
                self.assertFalse(store.release(token, True, status))
                reopened = LeaseStore(store.path)
                self.assertEqual(reopened.inspect()["lifecycle"], "recovery_required")
                self.assertEqual(reopened.inspect()["recovery_reason"], "CLEANUP_" + status.upper())
                self.assertIsNone(reopened.acquire("synthetic-run-two", "boot-two"))

    def test_unterminated_worker_blocks_even_if_cleanup_claims_success(self):
        token = self.token()
        self.store.begin_cleanup(token)
        self.assertFalse(self.store.release(token, False, "completed"))
        self.assertEqual(self.store.inspect()["recovery_reason"], "WORKER_NOT_TERMINATED")
        self.assertIsNone(self.store.acquire("synthetic-run-two", "boot-two"))

    def test_new_run_generation_and_boot_reject_old_token(self):
        first = self.token()
        self.store.begin_cleanup(first)
        self.store.release(first, True, "completed")
        second = LeaseStore(self.path).acquire("synthetic-run-two", "boot-two")
        self.assertGreater(second.generation, first.generation)
        self.assertNotEqual(second.boot_epoch, first.boot_epoch)
        self.assert_code("STALE_LEASE", self.store.authorize, first, "p2.capture")

    def test_attempt_handoff_revokes_old_attempt_and_initial_token(self):
        first = self.token()
        attempt = self.store.activate_attempt(first, "synthetic-attempt-one")
        self.assert_code("STALE_LEASE", self.store.authorize, first, "p2.capture")
        self.assertTrue(self.store.authorize(attempt, "p3.check", "synthetic-attempt-one"))
        self.store.begin_cleanup(attempt)
        following = self.store.finish_item(attempt, True, "completed")
        self.assertEqual(following.attempt_id, "")
        self.assertGreater(following.generation, first.generation)
        self.assert_code("STALE_LEASE", self.store.authorize, first, "p2.capture")
        self.assert_code("STALE_LEASE", self.store.authorize, attempt, "p3.check")
        next_attempt = self.store.activate_attempt(following, "synthetic-attempt-two")
        self.assertTrue(self.store.authorize(next_attempt, "p3.check"))

    def test_failed_item_cleanup_does_not_resume(self):
        token = self.store.activate_attempt(self.token(), "synthetic-attempt-one")
        self.store.begin_cleanup(token)
        self.assertIsNone(self.store.finish_item(token, True, "failed"))
        self.assertEqual(self.store.inspect()["lifecycle"], "recovery_required")
        self.assert_code("LEASE_REVOKED", self.store.authorize, token, "p3.check")

    def test_wrong_owner_epoch_device_generation_attempt_are_rejected(self):
        token = self.store.activate_attempt(self.token(), "synthetic-attempt-one")
        for field, value in (("run_id", "synthetic-other"), ("device_id", "synthetic-other"),
                             ("boot_epoch", "other-boot"), ("generation", 900),
                             ("attempt_id", "synthetic-other")):
            with self.subTest(field=field):
                self.assert_code("STALE_LEASE", self.store.authorize,
                                 replace(token, **{field: value}), "p3.check")

    def test_operation_and_attempt_scope_are_closed(self):
        token = self.token()
        self.assert_code("OPERATION_NOT_ALLOWED", self.store.authorize, token, "shell")
        self.assert_code("ATTEMPT_REQUIRED", self.store.authorize, token, "p3.check")
        attempt = self.store.activate_attempt(token, "synthetic-attempt-one")
        self.assert_code("ATTEMPT_SCOPE_MISMATCH", self.store.authorize, attempt, "p2.capture")
        self.assert_code("ATTEMPT_SCOPE_MISMATCH", self.store.authorize,
                         attempt, "p3.check", "synthetic-attempt-two")

    def test_cleanup_is_idempotent_but_release_is_not_repeated(self):
        token = self.token()
        self.store.begin_cleanup(token)
        self.store.begin_cleanup(token)
        self.store.release(token, True, "completed")
        self.assert_code("STALE_LEASE", self.store.release, token, True, "completed")

    def test_false_cleanup_proof_types_are_rejected(self):
        token = self.token()
        self.store.begin_cleanup(token)
        self.assert_code("INVALID_CLEANUP_PROOF", self.store.release, token, "yes", "completed")
        self.assert_code("INVALID_CLEANUP_PROOF", self.store.release, token, True, "success")
        self.assertEqual(self.store.inspect()["lifecycle"], "cleaning")

    def test_non_synthetic_owner_and_attempt_are_rejected(self):
        self.assert_code("INVALID_SYNTHETIC_IDENTIFIER", self.store.acquire, "real-device", "boot")
        token = self.token()
        self.assert_code("INVALID_SYNTHETIC_IDENTIFIER", self.store.activate_attempt, token, "adb")
        self.assertEqual(self.store.inspect()["attempt_id"], "")

    def test_token_is_immutable(self):
        token = self.token()
        with self.assertRaises(FrozenInstanceError):
            token.generation = 300


if __name__ == "__main__":
    unittest.main()
