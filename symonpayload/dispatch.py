# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Dispatch — deciding what runs next, sending it, and getting the answers back.

THE SENDER IS INJECTED, ALWAYS
------------------------------
Nothing here knows where an engine is. A `send` callable is passed in, and in the estate that
callable goes through the fabric: a caller names a component and the fabric attaches the
credential. Hardcoding an endpoint here would put a port back in a place that spent a whole day
having ports removed from it, and it would make every test need a GPU.

THE HARD PART IS NOT SENDING, IT IS GETTING BACK
------------------------------------------------
Admission coalesces: several identical requests become one call with one leader and a list of
followers. Dispatch must return that single answer to every one of them. A batch that is sent
correctly and delivered to only the leader is a batch where most callers hang forever, and the
symptom is a timeout three layers away from the cause.

So `Egress` is built around that: it refuses to deliver to a request that was not in the batch,
refuses to deliver twice, and reports anyone left undelivered rather than finishing quietly.

WHAT IT REFUSES TO DECIDE
-------------------------
Whether the engine is fast enough, whether a deadline is reachable, how many may run at once —
all of that is flow control, and it is measured. Dispatch takes those as inputs. A dispatcher
that also decides its own concurrency is a dispatcher that will disagree with the thing that
was supposed to decide it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .admit import Queue, Request
from .form import Batch, CannotForm, DynamicBatcher


class DispatchError(Exception):
    """A dispatch that could not be made or completed, carrying why."""


# A sender takes the wire payload and returns the far end's answer. Anything matching this can
# be passed: the fabric, a direct client, or a fake in a test.
Sender = Callable[[dict], Any]


@dataclass
class Sent:
    """One dispatched batch and what came back, including failure."""

    batch: Batch
    ok: bool
    result: Any = None
    error: str = ""
    seconds: float = 0.0
    engine: str = ""

    @property
    def tok_s(self) -> float:
        return (self.batch.tokens / self.seconds) if self.seconds > 0 else 0.0


class Scheduler:
    """Picks the next batch to run, under limits it is given — `symon-scheduler`.

    `symon-gpu-scheduler` is this with a device named: the choice of what runs next does not
    change because the thing it runs on has a name.

    It will not invent its own concurrency. The limit is passed in from flow control, which
    measured it, and a scheduler that also decided it would eventually disagree with the thing
    that was supposed to decide it.
    """

    def __init__(self, *, batcher: DynamicBatcher, device: str = "default") -> None:
        self.batcher = batcher
        self.device = device
        self.dispatched = 0

    def next_batch(self, queue: Queue, *, free_slots: int,
                   opened_at_ms: int | None = None) -> Batch | None:
        """The next batch, or None when there is nothing to do or no room to do it in.

        None is not an error and is not an empty batch. "Nothing to run" and "could not form a
        batch" are different, and only one of them is worth waking anybody about.
        """
        if free_slots <= 0:
            return None
        pending = queue.peek()
        if not pending:
            return None
        try:
            batch = self.batcher.form(pending, opened_at_ms=opened_at_ms)
        except CannotForm:
            return None
        queue.take(len(batch))
        self.dispatched += 1
        return batch


class Sequencer:
    """Order within one batch — `symon-sequencer`.

    Ordering by descending length is what makes padding cheap: the longest member sets the
    width, so grouping similar lengths adjacently means a micro-batch split wastes less. It is
    OFFERED, never applied silently, because the order admission chose may have been fairness
    and reordering it would quietly overrule that.
    """

    def by_length(self, batch: Batch) -> dict[str, Any]:
        order = sorted(batch.requests, key=lambda r: (-r.tokens, r.id))
        return {"suggested": [r.id for r in order], "current": batch.ids,
                "changes": [r.id for r in order] != batch.ids,
                "why": "descending length groups similar sizes so a split wastes less padding",
                "caution": "admission ordered this by deadline; applying length order overrules "
                           "a fairness decision and is therefore the caller's to make"}


class ExecRouter:
    """Request to execution cell — `symon-exec-router`.

    A cell is whatever the caller says it is: a device, a replica, a variant. The router only
    guarantees that it never routes to a cell it was not told about, and says which ones it
    considered.
    """

    def __init__(self, cells: Sequence[str]) -> None:
        if not cells:
            raise DispatchError("a router with no cells routes nowhere")
        self.cells = list(cells)
        self._n = 0

    def route(self, key: str = "") -> dict[str, Any]:
        if key:
            # Stable by key, so the same request lands on the same cell across retries — a
            # retry that lands elsewhere loses whatever warm state made the first attempt fast.
            cell = self.cells[sum(key.encode()) % len(self.cells)]
            why = "stable by key, so a retry lands where the first attempt did"
        else:
            cell = self.cells[self._n % len(self.cells)]
            self._n += 1
            why = "round robin; no key was given to be stable on"
        return {"cell": cell, "considered": list(self.cells), "why": why}


class BatchRouter:
    """A batch to one of several engines — `symon-batch-router`.

    It refuses to route to an engine that has not been declared, and it will not split a batch
    across engines: a batch was formed against ONE token ceiling, and half of it arriving
    somewhere with a different ceiling is a batch that does not fit twice.
    """

    def __init__(self, engines: dict[str, Sender]) -> None:
        if not engines:
            raise DispatchError("no engines declared; there is nowhere to route")
        self.engines = dict(engines)

    def choose(self, *, prefer: str | None = None) -> str:
        if prefer is not None:
            if prefer not in self.engines:
                raise DispatchError(f"{prefer!r} is not a declared engine; declared: "
                                    f"{', '.join(sorted(self.engines))}")
            return prefer
        return sorted(self.engines)[0]

    def send(self, batch: Batch, payload: dict, *, prefer: str | None = None) -> Sent:
        name = self.choose(prefer=prefer)
        sender = self.engines[name]
        t0 = time.time()
        try:
            out = sender(payload)
            return Sent(batch=batch, ok=True, result=out, seconds=time.time() - t0, engine=name)
        except Exception as e:
            return Sent(batch=batch, ok=False, error=f"{type(e).__name__}: {e}",
                        seconds=time.time() - t0, engine=name)


@dataclass
class TenantRouter:
    """Per-tenant fairness — `symon-tenant-router`.

    It tracks what each tenant has actually been served, not what they asked for, and picks the
    tenant furthest behind their share. Asked-for is easy to inflate; served is what happened.
    """

    shares: dict[str, float] = field(default_factory=dict)
    served: dict[str, int] = field(default_factory=dict)

    def declare(self, tenant: str, share: float) -> None:
        if share <= 0:
            raise DispatchError("a share must be positive")
        self.shares[tenant] = share
        self.served.setdefault(tenant, 0)

    def record(self, tenant: str, tokens: int) -> None:
        if tenant not in self.shares:
            raise DispatchError(f"{tenant!r} has no declared share; recording work for an "
                                f"undeclared tenant would make the fairness figures wrong")
        self.served[tenant] = self.served.get(tenant, 0) + max(0, tokens)

    def next_tenant(self, waiting: Iterable[str]) -> dict[str, Any]:
        pool = [t for t in waiting if t in self.shares]
        if not pool:
            raise DispatchError("none of the waiting tenants has a declared share")
        total_served = sum(self.served.get(t, 0) for t in pool) or 1
        total_share = sum(self.shares[t] for t in pool)
        debt = {}
        for t in pool:
            entitled = (self.shares[t] / total_share) * total_served
            debt[t] = entitled - self.served.get(t, 0)
        pick = max(sorted(pool), key=lambda t: debt[t])
        return {"tenant": pick, "debt": {k: round(v, 1) for k, v in debt.items()},
                "served": {k: self.served.get(k, 0) for k in pool},
                "why": "furthest behind their share of what has actually been SERVED — asked "
                       "for is easy to inflate, served is what happened"}


class VariantDispatcher:
    """Request to a model variant — `symon-variant-dispatch`.

    Traffic percentages must sum to 100 or it refuses. A split that sums to less silently drops
    the remainder onto whichever variant happens to be first, and that is the kind of error that
    shows up as an inexplicable result distribution weeks later.
    """

    def __init__(self, split: dict[str, float]) -> None:
        if not split:
            raise DispatchError("no variants declared")
        total = sum(split.values())
        if abs(total - 100.0) > 1e-6:
            raise DispatchError(f"traffic percentages sum to {total}, not 100. A split that "
                                f"does not sum drops the remainder somewhere nobody chose")
        self.split = dict(split)

    def route(self, key: str) -> dict[str, Any]:
        if not key:
            raise DispatchError("variant routing needs a key to be stable on; routing the same "
                                "caller to different variants makes the comparison meaningless")
        point = (sum(key.encode()) % 10000) / 100.0
        acc = 0.0
        for name in sorted(self.split):
            acc += self.split[name]
            if point < acc:
                return {"variant": name, "at": round(point, 2), "split": dict(self.split),
                        "why": "stable by key, so one caller always sees one variant"}
        last = sorted(self.split)[-1]
        return {"variant": last, "at": round(point, 2), "split": dict(self.split),
                "why": "floating point landed past the last boundary; the last variant takes it"}


class Egress:
    """Results back to the callers that asked — `symon-egress`.

    This is where coalescing is paid for. Admission turned several identical requests into one
    call with a leader and followers; every one of them is waiting. Delivering only to the
    leader leaves the rest hanging, and the symptom appears three layers away as a timeout.

    It refuses to deliver to a request that was not in the batch, refuses to deliver twice, and
    `undelivered()` names anyone still waiting rather than letting the batch finish quietly.
    """

    def __init__(self, batch: Batch, *, followers: dict[str, list[str]] | None = None) -> None:
        self.batch = batch
        self.followers = dict(followers or {})
        self.expected: set[str] = set(batch.ids)
        for lead, subs in self.followers.items():
            if lead not in self.expected:
                raise DispatchError(f"{lead!r} has followers but is not in this batch; the "
                                    f"coalescing map and the batch disagree")
            self.expected |= set(subs)
        self.delivered: dict[str, Any] = {}

    def deliver(self, request_id: str, result: Any) -> list[str]:
        """Deliver to one request and to everyone coalesced behind it. Returns who got it."""
        if request_id not in self.batch.ids:
            raise DispatchError(f"{request_id!r} was not in this batch; delivering to it would "
                                f"answer a request nobody sent here")
        targets = [request_id, *self.followers.get(request_id, [])]
        already = [t for t in targets if t in self.delivered]
        if already:
            raise DispatchError(f"already delivered to {', '.join(already)}; a second answer to "
                                f"one request means one of them is wrong")
        for t in targets:
            self.delivered[t] = result
        return targets

    def undelivered(self) -> list[str]:
        return sorted(self.expected - set(self.delivered))

    def complete(self) -> dict[str, Any]:
        left = self.undelivered()
        return {"expected": len(self.expected), "delivered": len(self.delivered),
                "undelivered": left, "complete": not left,
                "why": ("everyone who was waiting has an answer" if not left else
                        f"{len(left)} still waiting — coalesced callers hang silently, so this "
                        f"is named rather than left to a timeout")}


class ParallelRunner:
    """Bounded concurrent execution of independent sends — `symon-parallel-runner`.

    The bound is given, never chosen here: how many may run at once is measured by flow control
    and this would only disagree with it.
    """

    def __init__(self, *, workers: int) -> None:
        if workers <= 0:
            raise DispatchError("workers must be positive")
        self.workers = workers

    def run(self, jobs: Sequence[Callable[[], Any]]) -> list[dict[str, Any]]:
        if not jobs:
            raise DispatchError("no jobs to run")
        from concurrent.futures import ThreadPoolExecutor

        def one(fn):
            t0 = time.time()
            try:
                return {"ok": True, "result": fn(), "seconds": time.time() - t0}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}",
                        "seconds": time.time() - t0}

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futs = {ex.submit(one, j): i for i, j in enumerate(jobs)}
            got = {futs[f]: f.result() for f in futs}
        return [got[i] for i in sorted(got)]


class PipelineScheduler:
    """Stages that overlap — `symon-pipeline-scheduler`.

    Reports the steady-state rate, which is set by the SLOWEST stage and by nothing else.
    Summing the stages gives the latency of one item through the pipeline and says nothing about
    the rate, and confusing the two is how a pipeline gets "optimised" by speeding up a stage
    that was never the bottleneck.
    """

    def __init__(self, stages: dict[str, float]) -> None:
        if not stages:
            raise DispatchError("a pipeline with no stages has no schedule")
        bad = [k for k, v in stages.items() if v <= 0]
        if bad:
            raise DispatchError(f"stage {', '.join(bad)} has a non-positive duration; a stage "
                                f"that takes no time was not measured")
        self.stages = dict(stages)

    def analyse(self) -> dict[str, Any]:
        slowest = max(self.stages, key=lambda k: self.stages[k])
        total = sum(self.stages.values())
        rate = 1.0 / self.stages[slowest]
        return {"stages": dict(self.stages),
                "bottleneck": slowest, "bottleneck_s": self.stages[slowest],
                "latency_s": round(total, 4), "steady_rate_per_s": round(rate, 4),
                "speedup_vs_serial": round(total / self.stages[slowest], 3),
                "why": "the steady-state rate is set by the slowest stage alone; the sum is the "
                       "latency of ONE item and says nothing about the rate"}


class AssemblyLine(PipelineScheduler):
    """`symon-assembly` — the staged form of the same path, named for what it is pointed at."""


@dataclass
class Pipeline:
    """admit -> form -> dispatch, as one path — `symon-pipeline`.

    The whole point of composing it here is that the seams are where things get dropped: a batch
    formed and never sent, or sent and never delivered to its coalesced followers. Every run
    returns what happened at each seam.
    """

    scheduler: Scheduler
    router: BatchRouter
    build_payload: Callable[[Batch], dict]

    def run_once(self, queue: Queue, *, free_slots: int,
                 followers: dict[str, list[str]] | None = None,
                 prefer: str | None = None) -> dict[str, Any]:
        batch = self.scheduler.next_batch(queue, free_slots=free_slots)
        if batch is None:
            return {"ran": False, "why": "nothing to run, or no free slot to run it in",
                    "queue_depth": len(queue)}
        payload = self.build_payload(batch)
        sent = self.router.send(batch, payload, prefer=prefer)
        eg = Egress(batch, followers=followers)
        if sent.ok:
            # Deliver to each member that is not already answered. A leader's delivery also
            # answers its followers, and if a follower is itself in the batch — which happens
            # when a caller queues both rather than going through the gatekeeper — delivering
            # again would trip the double-answer guard. The guard is right; the loop was wrong.
            for rid in batch.ids:
                if rid not in eg.delivered:
                    eg.deliver(rid, sent.result)
        return {"ran": True, "batch": batch.ids, "bound": batch.bound,
                "tokens": batch.tokens, "engine": sent.engine,
                "ok": sent.ok, "error": sent.error,
                "seconds": round(sent.seconds, 3), "tok_s": round(sent.tok_s, 2),
                "egress": eg.complete(), "queue_depth": len(queue)}
