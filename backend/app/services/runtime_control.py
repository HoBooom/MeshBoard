"""Process-local cooperative cancellation signals for active agent executions."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from uuid import UUID


class AgentExecutionCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSnapshot:
    active_executions: int
    suspended: bool
    generation: int


class RuntimeControlRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, asyncio.Event] = {}
        self._active: dict[str, int] = {}
        self._generation: dict[str, int] = {}

    @staticmethod
    def _key(agent_id: UUID | str) -> str:
        return str(agent_id)

    def begin(self, agent_id: UUID | str) -> asyncio.Event:
        key = self._key(agent_id)
        with self._lock:
            event = self._events.setdefault(key, asyncio.Event())
            self._active[key] = self._active.get(key, 0) + 1
            return event

    def end(self, agent_id: UUID | str) -> None:
        key = self._key(agent_id)
        with self._lock:
            remaining = max(0, self._active.get(key, 0) - 1)
            if remaining:
                self._active[key] = remaining
            else:
                self._active.pop(key, None)

    def suspend(self, agent_id: UUID | str) -> RuntimeSnapshot:
        key = self._key(agent_id)
        with self._lock:
            event = self._events.setdefault(key, asyncio.Event())
            event.set()
            self._generation[key] = self._generation.get(key, 0) + 1
            return self._snapshot_unlocked(key)

    def activate(self, agent_id: UUID | str) -> RuntimeSnapshot:
        key = self._key(agent_id)
        with self._lock:
            self._events[key] = asyncio.Event()
            self._generation[key] = self._generation.get(key, 0) + 1
            return self._snapshot_unlocked(key)

    def snapshot(self, agent_id: UUID | str) -> RuntimeSnapshot:
        key = self._key(agent_id)
        with self._lock:
            return self._snapshot_unlocked(key)

    def _snapshot_unlocked(self, key: str) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            active_executions=self._active.get(key, 0),
            suspended=self._events.get(key, asyncio.Event()).is_set(),
            generation=self._generation.get(key, 0),
        )


runtime_control = RuntimeControlRegistry()
