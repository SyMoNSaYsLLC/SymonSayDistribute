# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Running the same thing many ways on purpose, and recording what happened.

WHY THIS MODULE COULD BE BUILT AND THE OTHER THREE COULD NOT
------------------------------------------------------------
Dispatch, flow control and residency all need MEASURED inputs — observed latency, token rate,
per-device residency — and building them against guesses produces modules that pass their own
tests and are wrong on the machine. This one needs none of that. A cross product is a cross
product, and a pass rate is a count.

THE FAILURE THIS IS SHAPED AGAINST
----------------------------------
A sweep's danger is not that it fails, it is that it succeeds enormously. Four axes of five
values each is 625 runs, and nothing about writing that down suggests it. So a matrix states
its size before anything runs and refuses one larger than the caller said they wanted — a cap
they have to name, because a default cap is somebody else deciding how much of the card's day
to spend.

AND THE ONE THAT WASTES THE RESULT
----------------------------------
A sweep that records only the winner cannot be re-read. Every cell keeps its configuration and
its outcome, including the failures, because "these four combinations all crashed" is the most
useful thing a sweep produces and it is the first thing a summary throws away.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence


class SweepError(Exception):
    """A sweep that could not be set up or run, carrying why."""


class ConfigMatrix:
    """The cross product of named axes — `symon-config-matrix`.

    `symon-instantiation-matrix` and `symon-quant-matrix` are this class over different axes
    (model loads, quantisations). They are configurations of one idea, not three ideas.
    """

    def __init__(self, axes: dict[str, Sequence[Any]]) -> None:
        if not axes:
            raise SweepError("a matrix with no axes has no cells")
        empty = [k for k, v in axes.items() if not v]
        if empty:
            raise SweepError(f"axis {', '.join(empty)} is empty, so the whole product is empty; "
                             f"an axis with nothing in it is a mistake, never a filter")
        self.axes = {k: list(v) for k, v in axes.items()}

    @property
    def size(self) -> int:
        n = 1
        for v in self.axes.values():
            n *= len(v)
        return n

    def describe(self) -> dict[str, Any]:
        return {"axes": {k: len(v) for k, v in self.axes.items()}, "cells": self.size,
                "note": "stated before anything runs, because four axes of five is 625 runs "
                        "and writing it down does not look like 625"}

    def cells(self, *, limit: int) -> list[dict[str, Any]]:
        """Every cell, refused if there are more than the caller said they wanted."""
        if limit <= 0:
            raise SweepError("name a positive limit; a sweep without one is unbounded work")
        if self.size > limit:
            raise SweepError(
                f"this matrix is {self.size} cells against a limit of {limit}: "
                f"{', '.join(f'{k}={len(v)}' for k, v in self.axes.items())}. Narrow an axis "
                f"or raise the limit deliberately")
        keys = list(self.axes)
        return [dict(zip(keys, combo)) for combo in itertools.product(*self.axes.values())]


def grid(**ranges: Sequence[Any]) -> ConfigMatrix:
    """`symon-grid` — a ConfigMatrix over numeric ranges, by keyword."""
    return ConfigMatrix(ranges)


@dataclass
class Cell:
    """One cell's configuration and what happened to it — including failure."""

    config: dict[str, Any]
    ok: bool
    result: Any = None
    error: str = ""
    seconds: float = 0.0


@dataclass
class RunMatrix:
    """The results, addressable by cell — `symon-run-matrix`.

    Failures are kept. "These four combinations all crashed" is the most useful thing a sweep
    produces and it is the first thing a summary of the winner throws away.
    """

    cells: list[Cell] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cells)

    @property
    def passed(self) -> list[Cell]:
        return [c for c in self.cells if c.ok]

    @property
    def failed(self) -> list[Cell]:
        return [c for c in self.cells if not c.ok]

    def best(self, key: Callable[[Cell], Any]) -> Cell:
        ok = self.passed
        if not ok:
            raise SweepError("every cell failed, so there is no best. The failures are the "
                             "result and they are all still here")
        return max(ok, key=key)

    def summary(self) -> dict[str, Any]:
        return {
            "cells": len(self.cells), "passed": len(self.passed), "failed": len(self.failed),
            "pass_rate": round(len(self.passed) / len(self.cells), 4) if self.cells else 0.0,
            "seconds": round(sum(c.seconds for c in self.cells), 2),
            "failures": [{"config": c.config, "error": c.error} for c in self.failed],
            "failures_kept_because": "a combination that crashes is a finding, and a summary "
                                     "of the winner is where that finding usually disappears",
        }


class JobPool:
    """Bounded concurrent execution — `symon-job-pool`.

    The bound has no default. How many things may run at once on this machine is a decision
    about this machine, and `symon-bulk` is this pool with a job list rather than a second idea.
    """

    def __init__(self, *, workers: int) -> None:
        if workers <= 0:
            raise SweepError("workers must be positive")
        self.workers = workers

    def run(self, jobs: Sequence[Callable[[], Any]]) -> RunMatrix:
        from concurrent.futures import ThreadPoolExecutor
        out = RunMatrix()
        if not jobs:
            raise SweepError("no jobs; an empty run is not a run")
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            futures = {ex.submit(_timed, j): i for i, j in enumerate(jobs)}
            results: dict[int, Cell] = {}
            for f in futures:
                i = futures[f]
                results[i] = f.result()
        out.cells = [results[i] for i in sorted(results)]
        return out


def _timed(fn: Callable[[], Any], config: dict | None = None) -> Cell:
    t0 = time.time()
    try:
        r = fn()
        return Cell(config=config or {}, ok=True, result=r, seconds=time.time() - t0)
    except Exception as e:
        return Cell(config=config or {}, ok=False, error=f"{type(e).__name__}: {e}",
                    seconds=time.time() - t0)


class MatrixEvaluator:
    """Run a callable over every cell and keep all of it — `symon-matrix-eval`.

    `symon-sweep` is this over a `grid`. Same machinery, named for what it is being pointed at.
    """

    def __init__(self, matrix: ConfigMatrix, *, limit: int, workers: int = 1) -> None:
        self.matrix = matrix
        self.limit = limit
        self.pool = JobPool(workers=workers)

    def run(self, fn: Callable[[dict[str, Any]], Any]) -> RunMatrix:
        cells = self.matrix.cells(limit=self.limit)
        out = RunMatrix()
        if self.pool.workers == 1:
            out.cells = [_timed(lambda c=c: fn(c), c) for c in cells]
            return out
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.pool.workers) as ex:
            futs = {ex.submit(_timed, (lambda c=c: fn(c)), c): i for i, c in enumerate(cells)}
            got = {futs[f]: f.result() for f in futs}
        out.cells = [got[i] for i in sorted(got)]
        return out


@dataclass(frozen=True)
class Case:
    """One evaluation case: an input and what is expected of the output."""

    name: str
    given: Any
    expect: Callable[[Any], bool]
    why: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise SweepError("a case with no name cannot be reported on")


class EvalSuite:
    """Cases, expectations and a pass rate — `symon-eval`.

    An expectation is a callable rather than an expected value, because most things worth
    evaluating are not equality — "is shorter than the input", "cites a source", "does not
    mention a competitor". A suite that can only check equality quietly becomes a suite of the
    things that are easy to check.
    """

    def __init__(self, cases: Iterable[Case]) -> None:
        self.cases = list(cases)
        if not self.cases:
            raise SweepError("a suite with no cases always passes, which is worse than failing")
        names = [c.name for c in self.cases]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise SweepError(f"duplicate case names {', '.join(sorted(dupes))}; two results "
                             f"under one name means one of them is lost")

    def run(self, subject: Callable[[Any], Any]) -> dict[str, Any]:
        rows = []
        for c in self.cases:
            t0 = time.time()
            try:
                got = subject(c.given)
                ok = bool(c.expect(got))
                err = ""
            except Exception as e:
                got, ok, err = None, False, f"{type(e).__name__}: {e}"
            rows.append({"case": c.name, "passed": ok, "error": err, "why": c.why,
                         "seconds": round(time.time() - t0, 4)})
        passed = sum(1 for r in rows if r["passed"])
        return {"cases": len(rows), "passed": passed, "failed": len(rows) - passed,
                "pass_rate": round(passed / len(rows), 4),
                "results": rows,
                "failed_cases": [r["case"] for r in rows if not r["passed"]]}
