"""Contract and fault tests for fake providers; no real model is called."""

import asyncio
import math
import unittest

from integration.providers import FakeProvider, Provider


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def make(self, provider, role="item"):
        context = {"role": role, "variant": "pass", "item_id": "synthetic-item-one", "selected_items": ["synthetic-item-one"]}
        return await provider.start_job(context, ("p3.check",))

    async def finish(self, job):
        await asyncio.wait_for(asyncio.shield(job.task), 1)

    async def test_normal_main_and_item_proposals(self):
        p = FakeProvider()
        self.assertIsInstance(p, Provider)
        main = await self.make(p, "main")
        await self.finish(main)
        self.assertEqual(await p.get_result(main.id), {"selected_items": ["synthetic-item-one"]})
        item = await self.make(p)
        await self.finish(item)
        self.assertEqual(await p.get_result(item.id), {"operation": "p3.check", "variant": "pass"})
        self.assertFalse(item.active_tool)

    async def test_events_have_source_and_finish_without_security_verdict(self):
        p = FakeProvider()
        job = await self.make(p)
        events = [event async for event in p.stream_events(job.id)]
        await self.finish(job)
        self.assertEqual([e["type"] for e in events], ["started", "finished"])
        self.assertTrue(all(e["synthetic"] and e["source"] == "fake_provider" for e in events))
        self.assertTrue(all("verdict" not in e for e in events))

    async def test_quiet_job_has_progress_without_output(self):
        p = FakeProvider("quiet", delay=0.05)
        job = await self.make(p)
        await self.finish(job)
        self.assertGreater(job.heartbeat, job.created_at)
        self.assertGreater(job.last_progress, job.created_at)
        self.assertEqual([e async for e in p.stream_events(job.id)], [])
        self.assertEqual((await p.get_result(job.id))["variant"], "pass")

    async def test_hang_has_heartbeat_without_progress(self):
        p = FakeProvider("hang")
        job = await self.make(p)
        await asyncio.sleep(0.025)
        self.assertFalse(job.task.done())
        self.assertGreater(job.heartbeat, job.created_at)
        self.assertEqual(job.last_progress, job.created_at)
        await p.cancel(job.id)
        with self.assertRaises(asyncio.CancelledError):
            await job.task

    async def test_heartbeat_lost_remains_alive(self):
        p = FakeProvider("heartbeat_lost")
        job = await self.make(p)
        await asyncio.sleep(0.025)
        self.assertFalse(job.task.done())
        self.assertEqual(job.heartbeat, job.created_at)
        await p.cancel(job.id)
        with self.assertRaises(asyncio.CancelledError):
            await job.task

    async def test_error_and_abnormal_empty_exit_are_distinct(self):
        broken = FakeProvider("error")
        error_job = await self.make(broken)
        with self.assertRaisesRegex(RuntimeError, "FAKE_PROVIDER_ERROR"):
            await error_job.task
        with self.assertRaisesRegex(RuntimeError, "FAKE_PROVIDER_ERROR"):
            await broken.get_result(error_job.id)
        empty = FakeProvider("exit")
        exit_job = await self.make(empty)
        await self.finish(exit_job)
        self.assertIsNone(await empty.get_result(exit_job.id))

    async def test_cancel_is_idempotent_and_stops_cooperative_job(self):
        p = FakeProvider(delay=0.5)
        job = await self.make(p)
        a = await p.cancel(job.id)
        b = await p.cancel(job.id)
        self.assertEqual(a, b)
        with self.assertRaises(asyncio.CancelledError):
            await job.task

    async def test_ignored_cancel_is_observably_alive_until_finite_completion(self):
        p = FakeProvider("ignores_cancel", delay=0.08)
        job = await self.make(p)
        await asyncio.sleep(0.01)  # Ensure the owned worker has actually started.
        await p.cancel(job.id)
        job.task.cancel()
        await asyncio.sleep(0.01)
        self.assertFalse(job.task.done())
        await self.finish(job)
        self.assertEqual((await p.get_result(job.id))["variant"], "pass")

    async def test_missing_cancel_capability_is_honest(self):
        p = FakeProvider(cancellation=False)
        self.assertFalse(p.capabilities()["cancellation"])
        job = await self.make(p)
        with self.assertRaisesRegex(RuntimeError, "UNSUPPORTED"):
            await p.cancel(job.id)
        await self.finish(job)

    async def test_result_before_done_is_pending(self):
        p = FakeProvider()
        job = await self.make(p)
        with self.assertRaisesRegex(RuntimeError, "PENDING"):
            await p.get_result(job.id)
        await self.finish(job)

    async def test_context_and_results_are_not_mutable_aliases(self):
        p = FakeProvider()
        context = {"role": "main", "selected_items": ["synthetic-original"]}
        job = await p.start_job(context, ())
        context["selected_items"].append("synthetic-late")
        await self.finish(job)
        result = await p.get_result(job.id)
        self.assertEqual(result, {"selected_items": ["synthetic-original"]})
        result["selected_items"].clear()
        self.assertEqual(await p.get_result(job.id), {"selected_items": ["synthetic-original"]})

    async def test_out_of_scope_fault_is_only_a_proposal(self):
        p = FakeProvider("out_of_scope")
        job = await self.make(p)
        await self.finish(job)
        self.assertEqual((await p.get_result(job.id))["operation"], "unavailable.operation")
        self.assertFalse(job.active_tool)

    async def test_two_fake_backends_share_contract_and_no_real_runtime_claim(self):
        for name in ("fake-a", "fake-b"):
            p = FakeProvider(name=name)
            caps = p.capabilities()
            self.assertEqual(caps["gateway_enforcement"], "fake_cooperative")
            self.assertTrue(caps["local_only"])
            self.assertEqual(caps["model"], "fake-only")
            job = await self.make(p)
            await self.finish(job)
            self.assertEqual(set(await p.get_result(job.id)), {"operation", "variant"})

    async def test_invalid_configuration_context_and_job_rejected(self):
        for value in (-1, 11, math.inf, math.nan, True, "1"):
            with self.subTest(delay=value), self.assertRaises(ValueError):
                FakeProvider(delay=value)
        with self.assertRaises(ValueError):
            FakeProvider("real-model")
        p = FakeProvider()
        with self.assertRaises(ValueError):
            await p.start_job({"role": "shell"}, ())
        with self.assertRaises(ValueError):
            await p.get_result("missing")


if __name__ == "__main__":
    unittest.main()
