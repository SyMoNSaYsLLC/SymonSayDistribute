# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""The agent loop — the one thing the estate did not have.

Symon could already ASK for a tool and could already READ a result: the channel format
renders tool declarations, emits `tool_use` blocks, and replays a `tool_result` as a message
from that tool. Nothing anywhere executed the call. This closes that circle and nothing more.

THE LOOP
--------
    send the task with the granted tools
    while the model asks for tools:
        execute each call, in the order asked
        send every result back in one turn
    return when the model answers instead of asking

WHY BOUNDS ARE NOT OPTIONAL
---------------------------
A run cannot be reached into once it starts. That is the point — it is what makes the grant a
bound rather than a suggestion — but it means the only thing that can stop a run that will
never finish is a limit set before it began. `max_steps` and `max_seconds` have no defaults
generous enough to be ignored, and a run that hits one ends as EXCEEDED, which is a result,
not a crash.

WHAT COMES BACK
---------------
Never only the answer. A run returns what it was granted, every tool it actually called, every
call that failed, and why it stopped — so "it worked" and "it gave up quietly" cannot look the
same in a report.
"""
from __future__ import annotations

import json, time, uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .tools import Grant


class Bounds(Exception):
    pass


STATES = ("composed", "running", "returned", "empty", "failed", "exceeded", "stopped")


@dataclass
class Step:
    n: int
    kind: str                      # "call" or "answer"
    tool: str = ""
    arguments: dict = field(default_factory=dict)
    result: str = ""
    is_error: bool = False
    seconds: float = 0.0


@dataclass
class Run:
    name: str
    task: str
    id: str = field(default_factory=lambda: "run_" + uuid.uuid4().hex[:16])
    state: str = "composed"
    started: float = 0.0
    ended: float = 0.0
    steps: list[Step] = field(default_factory=list)
    answer: str = ""
    why: str = ""
    granted: list[str] = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        return (self.ended or time.time()) - self.started if self.started else 0.0

    def report(self) -> dict:
        calls = [s for s in self.steps if s.kind == "call"]
        failed = [s for s in calls if s.is_error]
        return {
            "id": self.id, "name": self.name, "state": self.state,
            "elapsed_s": round(self.elapsed, 1),
            "granted": self.granted,
            "calls": len(calls),
            "tools_used": sorted({s.tool for s in calls}),
            "failed_calls": [{"tool": s.tool, "why": s.result[:200]} for s in failed],
            "answer": self.answer,
            "why": self.why,
        }


def run_agent(name: str, task: str, grant: Grant, send: Callable[[dict], dict], *,
              model: str, max_steps: int, max_seconds: float,
              stop: Callable[[], bool] | None = None,
              on_step: Callable[[Run, Step], None] | None = None) -> Run:
    """Drive one agent to a result.

    `send` takes a Messages-dialect payload and returns the parsed response. It is injected so
    the loop can be tested without a model and without a network — the loop's correctness is
    about transcript shape and bounds, not about what any particular model says.
    """
    if max_steps < 1:
        raise Bounds("max_steps is at least 1 — a run with no steps cannot return")
    if max_seconds <= 0:
        raise Bounds("max_seconds must be positive; a run that cannot be stopped is not bounded")

    run = Run(name=name, task=task, granted=grant.names())
    run.state, run.started = "running", time.time()
    messages: list[dict] = [{"role": "user", "content": task}]

    try:
        for n in range(1, max_steps + 1):
            if stop and stop():
                run.state, run.why = "stopped", "stopped by request between steps"
                break
            if run.elapsed > max_seconds:
                run.state = "exceeded"
                run.why = f"ran {run.elapsed:.0f}s against a {max_seconds:.0f}s bound"
                break

            t0 = time.time()
            reply = send({"model": model, "max_tokens": 4096, "messages": messages,
                          "tools": grant.declare()})
            blocks = reply.get("content") or []
            calls = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]

            if not calls:
                run.answer = "".join(b.get("text", "") for b in blocks
                                     if isinstance(b, dict) and b.get("type") == "text")
                run.steps.append(Step(n=n, kind="answer", seconds=round(time.time() - t0, 2)))
                if run.answer.strip():
                    run.state, run.why = "returned", "the model answered instead of asking"
                else:
                    # NOT an answer. The first live run came back `returned` with an empty
                    # string because the model emitted only a thinking block and stopped —
                    # it had decided to call a tool and never emitted the call. Reporting
                    # that as a return makes "it worked" and "it produced nothing" identical
                    # in every report downstream, which is the failure this estate exists to
                    # prevent. It gets its own state and names what it did produce.
                    kinds = sorted({b.get("type") for b in blocks if isinstance(b, dict)})
                    run.state = "empty"
                    run.why = ("the model neither called a tool nor answered; it produced "
                               f"{kinds or ['nothing']} and ended the turn")
                break

            # The assistant turn goes back verbatim. Dropping the thinking blocks or
            # reordering the calls hands the model a transcript it did not produce.
            messages.append({"role": "assistant", "content": blocks})
            results = []
            for c in calls:
                out, err = grant.execute(c.get("name", ""), c.get("input") or {})
                step = Step(n=n, kind="call", tool=c.get("name", ""),
                            arguments=c.get("input") or {}, result=out, is_error=err,
                            seconds=round(time.time() - t0, 2))
                run.steps.append(step)
                if on_step:
                    on_step(run, step)
                results.append({"type": "tool_result", "tool_use_id": c.get("id", ""),
                                "content": out, "is_error": err})
            messages.append({"role": "user", "content": results})
        else:
            run.state = "exceeded"
            run.why = f"used all {max_steps} steps without the model answering"
    except Exception as e:
        run.state, run.why = "failed", f"{type(e).__name__}: {e}"

    run.ended = time.time()
    return run
