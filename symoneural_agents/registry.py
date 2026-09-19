# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""The run registry — what is running, what ran, and what stopped it.

The loop drives one agent to a result. This holds many of them, so a surface can list runs,
watch one, and stop one, which is the whole difference between a library and something an
operator can supervise.

A RUN IS NEVER LOST QUIETLY
---------------------------
Every run stays in the registry after it ends, with its outcome, until it is explicitly
cleared. A supervisor that forgets finished runs cannot tell you what happened five minutes
ago, and "it isn't in the list" then means both "it never started" and "it finished" — the
two answers that most need telling apart.

STOPPING IS A REQUEST, NOT A KILL
----------------------------------
`stop` sets a flag the loop checks between steps. A run stops after the step it is in, so a
tool that is mid-write is never cut in half. That is slower than killing a thread and it is
the only version that leaves the filesystem in a state anyone can reason about.
"""
from __future__ import annotations

# Reached through the routes named below rather than as routes of their own.
NOT_EXPOSED = {
    "Runs": "a class, reached through the run routes",
    "RunNotFound": "an exception type",
}

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .agent import Run, run_agent
from .tools import Grant, Registry as ToolRegistry


class RunNotFound(KeyError):
    pass


@dataclass
class Entry:
    run: Run
    thread: threading.Thread | None = None
    stopping: bool = False
    started_at: float = field(default_factory=time.time)


class Runs:
    """Every run this process has started. Concurrency is capped, deliberately.

    An unbounded pool of agents against one card and one engine is a queue with extra steps
    and no way to see the queue. The cap is a number somebody chose, which is the only kind
    of limit that can be reasoned about later.
    """

    def __init__(self, *, max_concurrent: int = 4) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent is at least 1")
        self._lock = threading.Lock()
        self._runs: dict[str, Entry] = {}
        self.max_concurrent = max_concurrent

    # ---------------------------------------------------------------- reading
    def get(self, run_id: str) -> Entry:
        with self._lock:
            e = self._runs.get(run_id)
        if e is None:
            raise RunNotFound(run_id)
        return e

    def list(self, state: str | None = None) -> list[dict]:
        with self._lock:
            entries = list(self._runs.values())
        out = []
        for e in entries:
            r = e.run.report()
            r["stopping"] = e.stopping
            r["live"] = bool(e.thread and e.thread.is_alive())
            out.append(r)
        if state:
            out = [r for r in out if r["state"] == state]
        return sorted(out, key=lambda r: r["id"])

    def active(self) -> int:
        with self._lock:
            return sum(1 for e in self._runs.values() if e.thread and e.thread.is_alive())

    # ---------------------------------------------------------------- writing
    def start(self, name: str, task: str, grant: Grant, send: Callable[[dict], dict], *,
              model: str, max_steps: int, max_seconds: float) -> Run:
        """Begin a run in the background and return its record immediately.

        The record exists before the thread does, so a caller that asks for it a microsecond
        later finds it. A registry that only records a run once it has started produces a
        window in which a started run does not exist, and that window is where a supervisor
        loses track of things.
        """
        if self.active() >= self.max_concurrent:
            raise RuntimeError(
                f"{self.active()} of {self.max_concurrent} slots in use — "
                "raise max_concurrent deliberately or wait for one to return")

        run = Run(name=name, task=task, granted=grant.names())
        entry = Entry(run=run)
        with self._lock:
            self._runs[run.id] = entry

        def drive() -> None:
            finished = run_agent(name, task, grant, send, model=model,
                                 max_steps=max_steps, max_seconds=max_seconds,
                                 stop=lambda: entry.stopping)
            # Carry the outcome onto the record the caller already holds, rather than
            # replacing it — the id a caller was given must keep answering.
            run.state, run.why, run.answer = finished.state, finished.why, finished.answer
            run.steps, run.started, run.ended = finished.steps, finished.started, finished.ended

        t = threading.Thread(target=drive, name=f"agent-{run.id}", daemon=True)
        entry.thread = t
        run.started = time.time()
        t.start()
        return run

    def stop(self, run_id: str) -> dict:
        """Ask a run to stop after the step it is in."""
        e = self.get(run_id)
        if not (e.thread and e.thread.is_alive()):
            return e.run.report() | {"note": "already finished; nothing to stop"}
        e.stopping = True
        return e.run.report() | {"stopping": True,
                                 "note": "will stop after the step it is in, so a tool "
                                         "mid-write is never cut in half"}

    def clear(self, keep_live: bool = True) -> int:
        """Forget finished runs. Live ones are never dropped."""
        with self._lock:
            drop = [k for k, e in self._runs.items()
                    if not (keep_live and e.thread and e.thread.is_alive())]
            for k in drop:
                del self._runs[k]
        return len(drop)
