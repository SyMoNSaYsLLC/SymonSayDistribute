# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Flow control — what stops the estate accepting work it cannot serve.

THIS MODULE WAITED FOR A MEASUREMENT, AND THE MEASUREMENT IS IN
--------------------------------------------------------------
It was named and sourced months before it could be written, because every quantity in it is
observed rather than derived: how fast the engine actually answers, how much a second concurrent
request buys, how long a caller waits. Built against guesses it would pass its own tests and be
wrong on the machine.

Measured through the gateway on 2026-09-19 at 32k context, 128 output tokens per request:

    single stream        6.8 tok/s   latency p50 19.02 s, p95 19.10 s
    concurrent x2       11.2 tok/s   aggregate
    first event          436 ms

The number that shapes this module is the ratio. Doubling concurrency bought **1.65x**, not 2x:
the second slot added 4.4 tok/s where the first supplied 6.8. Throughput on one card is
sublinear in concurrency and every request pays the latency of every other one sharing it.

So nothing here has a default. A ceiling, a target latency, a deadline — each is a decision
about a particular machine under a particular load, and a number inherited from a benchmark
somebody else ran is how an estate ends up tuned for hardware it does not have.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class FlowError(Exception):
    """A flow-control decision that could not be made, carrying why."""


# The reference measurement, recorded rather than hardcoded as behaviour. Nothing reads these
# to make a decision; they are here so a caller can see what this estate has actually seen, and
# so a later measurement can be compared against a dated one rather than against a memory.
REFERENCE = {
    "taken": "2026-09-19",
    "how": "workflow/bench-gateway.sh --duration 60s --workers 2 --max-tokens 128",
    "context": 32768,
    "single_stream_tok_s": 6.8,
    "concurrent_2_tok_s": 11.2,
    "latency_p50_s": 19.02,
    "latency_p95_s": 19.10,
    "first_event_ms": 436,
    "reading": "concurrency 2 bought 1.65x, not 2x — the second slot added 4.4 tok/s against "
               "the first's 6.8. Throughput is sublinear in concurrency on one card",
}


class Concurrency:
    """The hard ceiling on requests in flight — `symon-concurrency`.

    Hard means hard: it refuses rather than queueing behind itself, because a limiter that
    silently waits is indistinguishable from a slow engine, and those have different fixes.
    """

    def __init__(self, *, limit: int) -> None:
        if limit <= 0:
            raise FlowError("a concurrency limit must be positive; zero admits nothing")
        self.limit = limit
        self.in_flight = 0
        self.refused = 0

    def acquire(self) -> None:
        if self.in_flight >= self.limit:
            self.refused += 1
            raise FlowError(f"{self.in_flight} already in flight against a limit of "
                            f"{self.limit}; this refuses rather than queueing, so a full unit "
                            f"is distinguishable from a slow one")
        self.in_flight += 1

    def release(self) -> None:
        if self.in_flight <= 0:
            raise FlowError("released more than was acquired; the count is wrong somewhere "
                            "and carrying on would hide it")
        self.in_flight -= 1

    @property
    def free(self) -> int:
        return self.limit - self.in_flight


@dataclass
class Sample:
    """One observation. Latency in seconds, tokens produced, concurrency at the time."""

    latency_s: float
    tokens: int
    concurrency: int

    def __post_init__(self) -> None:
        if self.latency_s <= 0:
            raise FlowError("a latency of zero or less is not an observation")
        if self.tokens <= 0:
            raise FlowError("an observation with no tokens measured nothing")
        if self.concurrency <= 0:
            raise FlowError("concurrency at the time must be at least one")

    @property
    def tok_s(self) -> float:
        return self.tokens / self.latency_s


class Throughput:
    """The observed rate, and what bound it — `symon-throughput`.

    It reports per-concurrency rates separately rather than one average. Averaging across
    concurrency levels produces a number that describes no configuration that was ever run: at
    the reference measurement it would report about 9 tok/s, which is neither the 6.8 seen at
    one nor the 11.2 seen at two.
    """

    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def observe(self, sample: Sample) -> None:
        self.samples.append(sample)

    def by_concurrency(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for s in self.samples:
            b = out.setdefault(s.concurrency, {"samples": 0, "tokens": 0, "seconds": 0.0})
            b["samples"] += 1
            b["tokens"] += s.tokens
            b["seconds"] += s.latency_s
        for c, b in out.items():
            # aggregate rate at this level: tokens produced over WALL time, which for c
            # concurrent streams is the summed latency divided by c
            wall = b["seconds"] / c
            b["aggregate_tok_s"] = round(b["tokens"] / wall, 2) if wall else 0.0
            b["per_stream_tok_s"] = round(b["tokens"] / b["seconds"], 2) if b["seconds"] else 0.0
        return out

    def marginal_gain(self, lower: int, higher: int) -> dict[str, Any]:
        """What the extra concurrency actually bought. The question worth asking before raising it."""
        by = self.by_concurrency()
        if lower not in by or higher not in by:
            raise FlowError(f"no samples at concurrency {lower} and {higher}; this compares "
                            f"what was measured and will not extrapolate between them")
        lo, hi = by[lower]["aggregate_tok_s"], by[higher]["aggregate_tok_s"]
        ratio = (hi / lo) if lo else 0.0
        ideal = higher / lower
        return {"from": lower, "to": higher, "tok_s": [lo, hi],
                "ratio": round(ratio, 3), "ideal_ratio": round(ideal, 3),
                "efficiency": round(ratio / ideal, 3) if ideal else 0.0,
                "gained_tok_s": round(hi - lo, 2),
                "reading": "a ratio below the ideal means each added stream is paying latency "
                           "for less than its share of throughput; at some point the next one "
                           "costs more than it returns"}

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            raise FlowError("nothing observed; there is no throughput to report and reporting "
                            "zero would read as an engine that produced nothing")
        return {"observations": len(self.samples), "by_concurrency": self.by_concurrency(),
                "reference": REFERENCE}


class AdaptiveThrottle:
    """Moves the concurrency ceiling on MEASURED latency — `symon-throttle`.

    Both bounds are the caller's and neither has a default. The target is a promise about what
    a caller waits; the ceiling is a fact about the card. Inheriting either is how a throttle
    ends up enforcing somebody else's service level on your hardware.

    It raises only on evidence. A ceiling is increased when latency is comfortably inside the
    target AND the last increase actually bought throughput — because at the reference
    measurement the second stream returned 1.65x, and a throttle that assumes 2x will keep
    climbing into a configuration where everyone waits longer for no more work done.
    """

    def __init__(self, *, target_latency_s: float, ceiling: int, floor: int = 1,
                 headroom: float = 0.8) -> None:
        if target_latency_s <= 0:
            raise FlowError("a target latency must be positive")
        if ceiling < floor or floor <= 0:
            raise FlowError(f"ceiling {ceiling} and floor {floor} do not describe a range")
        if not 0 < headroom < 1:
            raise FlowError("headroom is the fraction of the target below which it is safe to "
                            "raise; it must be between 0 and 1")
        self.target = target_latency_s
        self.ceiling = ceiling
        self.floor = floor
        self.headroom = headroom
        self.limit = floor
        self.history: list[dict[str, Any]] = []

    def observe(self, *, latency_s: float, throughput: "Throughput | None" = None) -> dict[str, Any]:
        """One decision, with the reason recorded."""
        if latency_s <= 0:
            raise FlowError("cannot decide on a latency of zero or less")
        before = self.limit
        why: str

        if latency_s > self.target:
            self.limit = max(self.floor, self.limit - 1)
            why = (f"latency {latency_s:.2f}s exceeded the target {self.target:.2f}s; lowering "
                   f"immediately rather than averaging, because a caller already waited")
        elif latency_s < self.target * self.headroom and self.limit < self.ceiling:
            gained = None
            # Only ask what the LAST step bought when there was a last step. At the floor,
            # max(floor, limit-1) is the limit itself, so this compared a level with itself,
            # found a gain of zero and refused to ever leave the floor. The throttle could not
            # start — found by a test that raised from 1 and got 1.
            if throughput is not None and self.limit > self.floor:
                try:
                    gained = throughput.marginal_gain(self.limit - 1, self.limit)
                except FlowError:
                    gained = None
            if gained is not None and gained["gained_tok_s"] <= 0:
                why = (f"latency {latency_s:.2f}s allows more, but the last increase bought "
                       f"{gained['gained_tok_s']} tok/s — raising again would add waiting for "
                       f"no work")
            else:
                self.limit += 1
                why = (f"latency {latency_s:.2f}s is under {self.headroom:.0%} of the target"
                       + (f" and the last increase bought {gained['gained_tok_s']} tok/s"
                          if gained else " (no throughput evidence supplied)"))
        else:
            why = f"latency {latency_s:.2f}s is within the target and the headroom; holding"

        row = {"latency_s": latency_s, "limit_before": before, "limit_after": self.limit,
               "target_s": self.target, "why": why}
        self.history.append(row)
        return row


@dataclass
class SLA:
    """Deadlines, and what to shed when they cannot be met — `symon-sla`.

    Shedding is decided by whether a deadline is still reachable at the MEASURED rate, not by
    queue length. A long queue served quickly is fine; a short one served slowly is not, and
    only the rate tells them apart.
    """

    target_latency_s: float
    measured_tok_s: float

    def __post_init__(self) -> None:
        if self.target_latency_s <= 0:
            raise FlowError("a target latency must be positive")
        if self.measured_tok_s <= 0:
            raise FlowError("the rate must be MEASURED and positive — this refuses to shed "
                            "against a rate nobody observed")

    def reachable(self, *, expected_tokens: int, ahead_in_queue: int = 0) -> dict[str, Any]:
        if expected_tokens <= 0:
            raise FlowError("expected tokens must be positive")
        own = expected_tokens / self.measured_tok_s
        waiting = (ahead_in_queue * expected_tokens) / self.measured_tok_s
        total = own + waiting
        ok = total <= self.target_latency_s
        return {"own_seconds": round(own, 2), "queue_seconds": round(waiting, 2),
                "total_seconds": round(total, 2), "target_seconds": self.target_latency_s,
                "meets_deadline": ok,
                "shed": not ok,
                "why": (f"{total:.1f}s against a {self.target_latency_s:.1f}s target at "
                        f"{self.measured_tok_s} tok/s"
                        + ("" if ok else " — admitting this promises what cannot be delivered"))}


class WindowTuner:
    """The batching window, derived from measurement — `symon-window-tuner`.

    A window longer than the time it takes to serve what is already queued adds waiting to every
    request and collects nothing extra. So it is bounded by the measured service time, never
    chosen as a round number.
    """

    def __init__(self, *, measured_tok_s: float, typical_tokens: int) -> None:
        if measured_tok_s <= 0 or typical_tokens <= 0:
            raise FlowError("both the rate and the typical size must be measured and positive")
        self.rate = measured_tok_s
        self.typical = typical_tokens

    def suggest(self, *, arrivals_per_s: float, max_wait_s: float) -> dict[str, Any]:
        if arrivals_per_s <= 0:
            raise FlowError("arrivals must be measured and positive")
        if max_wait_s <= 0:
            raise FlowError("a maximum wait must be positive")
        service_s = self.typical / self.rate
        # Waiting longer than one service time cannot collect a request that will be served
        # sooner than the wait itself.
        by_service = service_s
        # Waiting long enough to collect a second arrival, if that is sooner.
        by_arrival = 1.0 / arrivals_per_s
        window = min(by_service, by_arrival, max_wait_s)
        # Rounded to the same precision. Reporting the window to 3 places and the service
        # time to 2 made a window that is bounded BY the service time print as larger than it,
        # which reads as the bound not holding.
        return {"window_s": round(window, 3), "window_ms": int(window * 1000),
                "service_s": round(service_s, 3), "inter_arrival_s": round(by_arrival, 3),
                "bounded_by": ("the caller's maximum wait" if window == max_wait_s else
                               "one service time" if window == by_service else
                               "the time to the next arrival"),
                "why": "a window longer than the time to serve what is queued adds waiting to "
                       "everything and collects nothing that will not arrive anyway"}


@dataclass
class WindowStager:
    """Applies a tuned window without a restart — `symon-window-stager`.

    It stages rather than applies, and says what would change. A value that takes effect the
    instant it is computed cannot be reviewed, and this one is computed from a measurement that
    may have been taken under load nobody meant to tune for.
    """

    current_ms: int
    staged_ms: int | None = None
    reason: str = ""

    def stage(self, ms: int, reason: str) -> dict[str, Any]:
        if ms <= 0:
            raise FlowError("a window must be positive")
        if not reason.strip():
            raise FlowError("staging a change needs a reason; a value with no reason cannot be "
                            "reviewed and will be applied by default")
        self.staged_ms, self.reason = ms, reason
        return self.diff()

    def diff(self) -> dict[str, Any]:
        return {"current_ms": self.current_ms, "staged_ms": self.staged_ms,
                "changes": self.staged_ms is not None and self.staged_ms != self.current_ms,
                "delta_ms": (self.staged_ms - self.current_ms) if self.staged_ms else 0,
                "reason": self.reason,
                "note": "nothing takes effect until apply() is called"}

    def apply(self) -> dict[str, Any]:
        if self.staged_ms is None:
            raise FlowError("nothing staged")
        before = self.current_ms
        self.current_ms, self.staged_ms = self.staged_ms, None
        return {"was_ms": before, "now_ms": self.current_ms, "reason": self.reason}


@dataclass
class Allocator:
    """Shares of the device across tenants — `symon-allocator`.

    Shares are relative weights, not absolute limits, because the absolute capacity of one card
    changes with context length and concurrency and a fixed allocation goes wrong the moment
    either does.
    """

    weights: dict[str, float] = field(default_factory=dict)

    def set_share(self, tenant: str, weight: float) -> None:
        if weight <= 0:
            raise FlowError("a share must be positive; removing a tenant is a separate act")
        self.weights[tenant] = weight

    def slots(self, total: int) -> dict[str, int]:
        """Whole slots per tenant, with the remainder given to the largest share.

        Fractional slots do not exist, and rounding each independently either over- or
        under-allocates the card. The remainder goes somewhere deliberate instead.
        """
        if total <= 0:
            raise FlowError("there are no slots to allocate")
        if not self.weights:
            raise FlowError("no tenants have shares; allocating to nobody is not a result")
        s = sum(self.weights.values())
        raw = {t: (w / s) * total for t, w in self.weights.items()}
        out = {t: int(v) for t, v in raw.items()}
        left = total - sum(out.values())
        for t in sorted(raw, key=lambda k: (-(raw[k] - int(raw[k])), k))[:left]:
            out[t] += 1
        return out


@dataclass
class LoadShifter:
    """Moves work between engines under pressure — `symon-load-shift`.

    It refuses to shift onto an engine whose rate has not been measured. Moving work to an
    unknown engine is not load balancing, it is hoping, and the failure arrives as a caller
    waiting on something slower than what they left.
    """

    rates: dict[str, float] = field(default_factory=dict)

    def observe(self, engine: str, tok_s: float) -> None:
        if tok_s <= 0:
            raise FlowError(f"{engine}: a rate must be measured and positive")
        self.rates[engine] = tok_s

    def choose(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        pool = {k: v for k, v in self.rates.items() if k not in (exclude or set())}
        if not pool:
            raise FlowError("no engine with a measured rate is available; this will not shift "
                            "onto one nobody has observed")
        best = max(pool, key=lambda k: pool[k])
        return {"engine": best, "tok_s": pool[best],
                "considered": {k: pool[k] for k in sorted(pool)},
                "why": f"{best} is the fastest engine with a MEASURED rate"}
