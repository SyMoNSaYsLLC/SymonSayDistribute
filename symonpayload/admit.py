# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Admission — everything that happens before a request is allowed to cost anything.

The gateway relays each request straight to the engine: no queue, no ordering, no ceiling on
what is in flight. That works until two people ask at once, and then the failure is a timeout
somewhere downstream with nothing to say which request caused it or why it was accepted.

The rule this module exists to enforce: work is refused at the door, with a reason, or it is
admitted and accounted for. There is no third state where something is in the building and
nobody knows.

NO DEFAULTS FOR POLICY. Capacity, window and concurrency are arguments without defaults,
because they are decisions about a particular machine. A default here is a number nobody
chose, silently deciding what the estate will accept.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable


class Refused(Exception):
    """Refusal at the door, carrying why. Never raised for an internal fault."""

    def __init__(self, reason: str, request_id: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.request_id = request_id


@dataclass(frozen=True)
class Request:
    """One arrival.

    `tokens` is counted by the caller before it gets here. It is not estimated from character
    length: the gateway already exposes count_tokens, and a batch formed on a guessed token
    count is a batch that does not fit.
    """

    id: str
    tokens: int
    tenant: str = "default"
    deadline_ms: int | None = None
    fingerprint: str = ""
    at_ms: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("a request needs an id; an unidentifiable request cannot be reported on")
        if self.tokens <= 0:
            raise ValueError(f"{self.id}: tokens must be counted and positive, got {self.tokens}")
        if self.deadline_ms is not None and self.deadline_ms <= 0:
            raise ValueError(f"{self.id}: a deadline that has already passed is not a deadline")


class Ingress:
    """The bounded arrival buffer. Full means refuse — never grow.

    An unbounded queue does not remove the limit, it moves it: requests accumulate until
    something further down runs out of memory, and the refusal arrives as a crash instead of
    a 429. Refusing at a number somebody chose is the whole point.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive; a zero-capacity ingress accepts nothing")
        self.capacity = capacity
        self._held: list[Request] = []

    def __len__(self) -> int:
        return len(self._held)

    @property
    def full(self) -> bool:
        return len(self._held) >= self.capacity

    def offer(self, req: Request) -> None:
        if self.full:
            raise Refused(f"ingress is at capacity ({self.capacity}); not accepting more", req.id)
        self._held.append(req)

    def drain(self) -> list[Request]:
        out, self._held = self._held, []
        return out


class Prioritizer:
    """The ordering policy the queue reads. Deadline first, then arrival order.

    Stable on purpose: two requests with the same deadline keep the order they arrived in, so
    a caller cannot be starved by a steady stream of equally urgent work.
    """

    def order(self, reqs: Iterable[Request]) -> list[Request]:
        indexed = list(enumerate(reqs))
        # None sorts last: no deadline means no claim on going first.
        return [r for _, r in sorted(
            indexed, key=lambda p: (p[1].deadline_ms is None, p[1].deadline_ms or 0, p[1].at_ms, p[0]))]


class Coalescer:
    """One in-flight call serves every identical concurrent request.

    Identity is the caller's `fingerprint` and nothing else. This module does not hash bodies
    to decide what is 'the same' — two requests that differ in a way we did not think to hash
    would silently receive each other's answer, and that is a correctness bug pretending to be
    an optimisation. An empty fingerprint means "never coalesce me".
    """

    def __init__(self) -> None:
        self._leaders: dict[str, str] = {}
        self._followers: dict[str, list[str]] = {}

    def admit(self, req: Request) -> str | None:
        """Return the leader's request id if this one is a follower, else None."""
        if not req.fingerprint:
            return None
        leader = self._leaders.get(req.fingerprint)
        if leader is None:
            self._leaders[req.fingerprint] = req.id
            self._followers[req.id] = []
            return None
        self._followers[leader].append(req.id)
        return leader

    def followers(self, leader_id: str) -> list[str]:
        return list(self._followers.get(leader_id, ()))

    def release(self, leader_id: str) -> list[str]:
        """Finish a leader and hand back everyone waiting on it."""
        waiting = self._followers.pop(leader_id, [])
        for fp, lid in list(self._leaders.items()):
            if lid == leader_id:
                del self._leaders[fp]
        return waiting


class TriageGate:
    """Admit or refuse, with the reason.

    Every refusal names which limit was hit. "Rejected" with no reason is the failure mode this
    replaces: an operator reading logs cannot tell an over-long prompt from an over-full queue,
    and those need opposite responses.
    """

    def __init__(self, *, max_tokens: int, tenants: set[str] | None = None) -> None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        self.max_tokens = max_tokens
        self.tenants = tenants

    def check(self, req: Request) -> None:
        if req.tokens > self.max_tokens:
            raise Refused(
                f"{req.tokens} tokens exceeds the {self.max_tokens} this unit accepts", req.id)
        if self.tenants is not None and req.tenant not in self.tenants:
            raise Refused(f"tenant {req.tenant!r} is not one this unit serves", req.id)

    def route(self, req: Request) -> str:
        """WorkloadTriageDispatcher: the same gate, reporting a lane instead of a verdict."""
        self.check(req)
        return "urgent" if req.deadline_ms is not None else "bulk"


class Queue:
    """The admitted work, and only the admitted work.

    Nothing reaches here without passing the gate, so its length is a number that means
    something: it is work the unit has agreed to do.
    """

    def __init__(self, prioritizer: Prioritizer | None = None) -> None:
        self._items: list[Request] = []
        self.prioritizer = prioritizer or Prioritizer()

    def __len__(self) -> int:
        return len(self._items)

    def put(self, req: Request) -> None:
        self._items.append(req)

    def take(self, n: int) -> list[Request]:
        if n <= 0:
            raise ValueError("take needs a positive count")
        ordered = self.prioritizer.order(self._items)
        taken, rest = ordered[:n], ordered[n:]
        self._items = rest
        return taken

    def peek(self) -> list[Request]:
        return self.prioritizer.order(self._items)


class Aggregator:
    """Collects arrivals over a window into one candidate batch.

    The window is in milliseconds and the clock is injected. A module that reads the wall clock
    itself cannot be tested for the behaviour that matters — what happens exactly at the
    boundary — so the clock is an argument.
    """

    def __init__(self, *, window_ms: int, clock: Callable[[], int]) -> None:
        if window_ms <= 0:
            raise ValueError("window_ms must be positive; a zero window never aggregates")
        self.window_ms = window_ms
        self.clock = clock
        self._opened_at: int | None = None
        self._held: list[Request] = []

    def add(self, req: Request) -> None:
        if self._opened_at is None:
            self._opened_at = self.clock()
        self._held.append(req)

    @property
    def age_ms(self) -> int:
        return 0 if self._opened_at is None else self.clock() - self._opened_at

    @property
    def expired(self) -> bool:
        return self._opened_at is not None and self.age_ms >= self.window_ms

    def close(self) -> list[Request]:
        out, self._held, self._opened_at = self._held, [], None
        return out


@dataclass
class Gatekeeper:
    """Queue, Prioritizer and TriageGate as one object, because they are used together.

    Kept as one admission point so there is a single place that can answer "why was this
    refused" — three objects wired differently in two callers is how two callers end up with
    different admission policy and nobody notices.
    """

    gate: TriageGate
    ingress: Ingress
    queue: Queue = field(default_factory=Queue)
    coalescer: Coalescer = field(default_factory=Coalescer)
    refusals: list[tuple[str, str]] = field(default_factory=list)

    def admit(self, req: Request) -> str | None:
        """Admit one request. Returns a leader id if coalesced, None if queued.

        Raises Refused, and records it, so the refusal is countable afterwards rather than
        only visible to whoever caught the exception.
        """
        try:
            self.gate.check(req)
            self.ingress.offer(req)
        except Refused as r:
            self.refusals.append((req.id, r.reason))
            raise
        leader = self.coalescer.admit(req)
        if leader is None:
            self.queue.put(req)
        self.ingress.drain()
        return leader
