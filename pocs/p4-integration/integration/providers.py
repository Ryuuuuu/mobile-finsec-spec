"""Model-neutral provider boundary and local, cooperative synthetic jobs only.

No provider executes a tool. The supervisor must validate each returned proposal
against its immutable plan and gateway before it may invoke an adapter.
"""

from __future__ import annotations

import asyncio
import copy
import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


BEHAVIORS = frozenset({
    "normal", "quiet", "error", "exit", "hang", "heartbeat_lost",
    "ignores_cancel", "out_of_scope",
})


@dataclass
class FakeJob:
    """Observable task state; the clock is host monotonic, not fixture time."""

    job_id: str
    role: str
    created_at: float
    heartbeat: float
    last_progress: float
    active_tool: bool = False
    task: asyncio.Task[Any] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    events: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)

    @property
    def id(self) -> str:
        return self.job_id

    @property
    def created(self) -> float:
        return self.created_at


@runtime_checkable
class Provider(Protocol):
    """Transport/model-independent operations used by the P4 supervisor.

    FakeJob currently represents the observable handle. A real runtime needs a
    separately validated implementation and stronger isolation guarantees.
    """

    def capabilities(self) -> dict[str, Any]: ...

    async def start_job(
        self, context: dict[str, Any], tool_catalog: tuple[str, ...]
    ) -> FakeJob: ...

    def stream_events(self, job_id: str) -> AsyncIterator[dict[str, Any]]: ...

    async def cancel(self, job_id: str) -> dict[str, Any]: ...

    async def get_result(self, job_id: str) -> dict[str, Any] | None: ...


class FakeProvider:
    """Finite normal/error jobs plus explicitly injected liveness faults.

    ``hang`` and ``heartbeat_lost`` remain alive until cancelled. The
    ``ignores_cancel`` fault ignores cooperative and Task.cancel requests until
    its finite delay expires; it permits testing retained ownership safely.
    ``quiet`` has heartbeat/progress with no textual events. All behavior is
    in-process simulation, not evidence of real model/process cancellation.
    """

    def __init__(
        self,
        behavior: str = "normal",
        delay: float = 0.02,
        name: str = "fake-a",
        cancellation: bool = True,
    ) -> None:
        if behavior not in BEHAVIORS:
            raise ValueError("UNKNOWN_FAKE_BEHAVIOR")
        if isinstance(delay, bool) or not isinstance(delay, (int, float)):
            raise ValueError("INVALID_FAKE_DELAY")
        if not math.isfinite(delay) or not 0 <= delay <= 10:
            raise ValueError("INVALID_FAKE_DELAY")
        if not isinstance(name, str) or not name.startswith("fake-") or len(name) > 64:
            raise ValueError("INVALID_FAKE_PROVIDER_NAME")
        if type(cancellation) is not bool:
            raise ValueError("INVALID_FAKE_CANCELLATION")
        self.behavior = behavior
        self.delay = float(delay)
        self.name = name
        self.cancellation = cancellation
        self.jobs: dict[str, FakeJob] = {}

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": "fake-only",
            "runtime": "p4-fake-v1",
            "synthetic": True,
            "tool_calling": True,
            "cancellation": self.cancellation,
            "structured_output": True,
            "streaming": True,
            "resume": False,
            "local_only": True,
            "gateway_enforcement": "fake_cooperative",
        }

    async def start_job(
        self, context: dict[str, Any], tool_catalog: tuple[str, ...]
    ) -> FakeJob:
        if not isinstance(context, dict) or context.get("role") not in {"main", "item"}:
            raise ValueError("INVALID_PROVIDER_CONTEXT")
        if not isinstance(tool_catalog, tuple) or not all(isinstance(x, str) for x in tool_catalog):
            raise ValueError("INVALID_TOOL_CATALOG")
        if context["role"] == "main" and not isinstance(context.get("selected_items"), list):
            raise ValueError("INVALID_SELECTED_ITEMS")
        if context["role"] == "item" and context.get("variant") not in {"pass", "fail", "inconclusive"}:
            raise ValueError("INVALID_ITEM_VARIANT")
        copied = copy.deepcopy(context)
        now = time.monotonic()
        job = FakeJob("synthetic-job-" + uuid.uuid4().hex, copied["role"], now, now, now)
        self.jobs[job.id] = job
        job.task = asyncio.create_task(self._run(job, copied, tuple(tool_catalog)), name=job.id)
        return job

    def _emit(self, job: FakeJob, event_type: str) -> None:
        job.events.put_nowait({
            "job_id": job.id,
            "role": job.role,
            "source": "fake_provider",
            "synthetic": True,
            "type": event_type,
            "payload": {},
        })

    async def _run(
        self, job: FakeJob, context: dict[str, Any], tool_catalog: tuple[str, ...]
    ) -> dict[str, Any] | None:
        # The catalog is intentionally not executed. Even an allowed proposal
        # still needs supervisor validation and lease authorization.
        del tool_catalog
        quiet = self.behavior == "quiet"
        if not quiet:
            self._emit(job, "started")
        try:
            while True:
                now = time.monotonic()
                if self.behavior != "heartbeat_lost":
                    job.heartbeat = now
                if self.behavior not in {"hang", "heartbeat_lost"}:
                    job.last_progress = now
                if job.stop.is_set() and self.behavior != "ignores_cancel":
                    raise asyncio.CancelledError()
                if self.behavior not in {"hang", "heartbeat_lost"} and now - job.created_at >= self.delay:
                    break
                try:
                    await asyncio.sleep(0.005)
                except asyncio.CancelledError:
                    if self.behavior != "ignores_cancel":
                        raise
            if self.behavior == "error":
                raise RuntimeError("FAKE_PROVIDER_ERROR")
            if self.behavior == "exit":
                return None
            if job.role == "main":
                result = {"selected_items": copy.deepcopy(context["selected_items"])}
                if self.behavior == "out_of_scope":
                    result["selected_items"].append("synthetic-unselected-item")
            else:
                result = {"operation": "p3.check", "variant": context["variant"]}
                if self.behavior == "out_of_scope":
                    result["operation"] = "unavailable.operation"
            if not quiet:
                self._emit(job, "finished")
            return result
        finally:
            job.events.put_nowait(None)

    def _job(self, job_id: str) -> FakeJob:
        try:
            return self.jobs[job_id]
        except (KeyError, TypeError) as exc:
            raise ValueError("UNKNOWN_PROVIDER_JOB") from exc

    async def stream_events(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Single-consumer transport stream; durable replay belongs to supervisor."""
        job = self._job(job_id)
        while True:
            event = await job.events.get()
            if event is None:
                return
            yield copy.deepcopy(event)

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        if not self.cancellation:
            raise RuntimeError("PROVIDER_CANCELLATION_UNSUPPORTED")
        job.stop.set()
        return {"job_id": job.id, "cancel_requested": True}

    async def get_result(self, job_id: str) -> dict[str, Any] | None:
        job = self._job(job_id)
        if job.task is None or not job.task.done():
            raise RuntimeError("PROVIDER_RESULT_PENDING")
        return copy.deepcopy(job.task.result())
