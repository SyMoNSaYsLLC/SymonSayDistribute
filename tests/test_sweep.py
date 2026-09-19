# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Sweep tests. A sweep's danger is succeeding enormously, and its waste is throwing away the
failures — so most of these are about size and about what is kept."""
import pytest

from symonpayload.sweep import (
    Case, ConfigMatrix, EvalSuite, JobPool, MatrixEvaluator, RunMatrix, SweepError, grid)


# --- size is stated before anything runs ------------------------------------------------
def test_a_matrix_states_its_size_before_running_anything():
    m = grid(a=[1, 2, 3], b=[1, 2], c=[1, 2])
    d = m.describe()
    assert d["cells"] == 12 and m.size == 12


def test_a_matrix_larger_than_the_stated_limit_is_refused_with_the_axes():
    m = ConfigMatrix({"a": list(range(30)), "b": list(range(30))})
    with pytest.raises(SweepError, match="900 cells against a limit of 100"):
        m.cells(limit=100)


def test_the_limit_must_be_named_and_positive():
    with pytest.raises(SweepError, match="unbounded work"):
        grid(a=[1]).cells(limit=0)


def test_an_empty_axis_is_a_mistake_not_a_filter():
    with pytest.raises(SweepError, match="never a filter"):
        ConfigMatrix({"a": [1], "b": []})


def test_a_matrix_with_no_axes_is_refused():
    with pytest.raises(SweepError, match="no axes"):
        ConfigMatrix({})


# --- failures are kept -------------------------------------------------------------------
def test_a_failing_cell_is_recorded_with_its_config_and_error():
    def fn(c):
        if c["a"] == 2:
            raise ValueError("boom")
        return c["a"]
    r = MatrixEvaluator(grid(a=[1, 2, 3]), limit=10).run(fn)
    s = r.summary()
    assert s["passed"] == 2 and s["failed"] == 1
    assert s["failures"][0]["config"] == {"a": 2}
    assert "boom" in s["failures"][0]["error"]


def test_the_summary_says_why_failures_are_kept():
    r = MatrixEvaluator(grid(a=[1]), limit=5).run(lambda c: c["a"])
    assert "disappears" in r.summary()["failures_kept_because"]


def test_best_refuses_when_everything_failed_and_says_the_failures_remain():
    def boom(c):
        raise RuntimeError("no")
    r = MatrixEvaluator(grid(a=[1, 2]), limit=5).run(boom)
    with pytest.raises(SweepError, match="failures are the result"):
        r.best(lambda c: c.result)
    assert len(r.failed) == 2


def test_best_picks_from_the_cells_that_passed():
    r = MatrixEvaluator(grid(a=[1, 5, 3]), limit=9).run(lambda c: c["a"])
    assert r.best(lambda c: c.result).config == {"a": 5}


# --- the pool ------------------------------------------------------------------------------
def test_the_worker_bound_has_no_default_and_must_be_positive():
    with pytest.raises(SweepError, match="workers must be positive"):
        JobPool(workers=0)


def test_an_empty_job_list_is_refused():
    with pytest.raises(SweepError, match="not a run"):
        JobPool(workers=2).run([])


def test_jobs_keep_their_order_even_run_concurrently():
    r = JobPool(workers=4).run([(lambda i=i: i) for i in range(8)])
    assert [c.result for c in r.cells] == list(range(8))


def test_concurrent_evaluation_keeps_cell_order():
    r = MatrixEvaluator(grid(a=[1, 2, 3, 4]), limit=9, workers=3).run(lambda c: c["a"] * 10)
    assert [c.result for c in r.cells] == [10, 20, 30, 40]


# --- evaluation ------------------------------------------------------------------------------
def test_a_suite_with_no_cases_is_refused_because_it_would_always_pass():
    with pytest.raises(SweepError, match="worse than failing"):
        EvalSuite([])


def test_duplicate_case_names_are_refused():
    c = Case("same", 1, lambda o: True)
    with pytest.raises(SweepError, match="duplicate case names"):
        EvalSuite([c, Case("same", 2, lambda o: True)])


def test_a_case_needs_a_name_to_be_reported_on():
    with pytest.raises(SweepError, match="cannot be reported on"):
        Case("", 1, lambda o: True)


def test_an_expectation_can_be_any_predicate_not_only_equality():
    s = EvalSuite([Case("compresses", "hello world", lambda o: len(o) < 11),
                   Case("keeps_start", "hello world", lambda o: o.startswith("hell"))])
    out = s.run(lambda g: g[:4])
    assert out["pass_rate"] == 1.0 and out["cases"] == 2


def test_a_case_that_raises_counts_as_failed_and_keeps_the_error():
    s = EvalSuite([Case("explodes", None, lambda o: True)])
    out = s.run(lambda g: 1 / 0)
    assert out["failed"] == 1 and "ZeroDivisionError" in out["results"][0]["error"]
    assert out["failed_cases"] == ["explodes"]
