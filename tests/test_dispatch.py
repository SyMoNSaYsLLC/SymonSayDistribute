# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Dispatch tests. Weighted to egress, because sending is the easy half: a batch delivered only
to its leader leaves every coalesced caller hanging, and the symptom appears three layers away."""
import pytest

from symonpayload.admit import Queue, Request
from symonpayload.dispatch import (
    AssemblyLine, BatchRouter, DispatchError, Egress, ExecRouter, ParallelRunner, Pipeline,
    PipelineScheduler, Scheduler, Sequencer, TenantRouter, VariantDispatcher)
from symonpayload.form import Batch, DynamicBatcher


def r(i, tokens=40):
    return Request(id=i, tokens=tokens)


def batch(*ids):
    reqs = tuple(r(i) for i in ids)
    return Batch(requests=reqs, tokens=40 * len(reqs), bound="count")


def batcher(max_tokens=200, max_requests=5):
    return DynamicBatcher(max_tokens=max_tokens, max_requests=max_requests,
                          window_ms=50, clock=lambda: 0)


# --- egress is where coalescing is paid for ---------------------------------------------
def test_a_coalesced_follower_is_answered_too():
    eg = Egress(batch("a"), followers={"a": ["b", "c"]})
    got = eg.deliver("a", {"ok": True})
    assert sorted(got) == ["a", "b", "c"]
    assert eg.complete()["complete"] is True


def test_a_follower_left_undelivered_is_named_not_left_to_a_timeout():
    eg = Egress(batch("a"), followers={"a": ["b"]})
    assert eg.undelivered() == ["a", "b"]
    out = eg.complete()
    assert out["complete"] is False and "still waiting" in out["why"]


def test_delivering_to_a_request_not_in_the_batch_is_refused():
    eg = Egress(batch("a"))
    with pytest.raises(DispatchError, match="was not in this batch"):
        eg.deliver("stranger", {})


def test_delivering_twice_is_refused_because_one_answer_would_be_wrong():
    eg = Egress(batch("a"))
    eg.deliver("a", 1)
    with pytest.raises(DispatchError, match="already delivered"):
        eg.deliver("a", 2)


def test_a_follower_map_that_disagrees_with_the_batch_is_refused_at_construction():
    with pytest.raises(DispatchError, match="coalescing map and the batch disagree"):
        Egress(batch("a"), followers={"ghost": ["b"]})


# --- the scheduler distinguishes nothing-to-do from could-not-form -----------------------
def test_no_free_slot_returns_none_rather_than_an_empty_batch():
    q = Queue(); q.put(r("a"))
    assert Scheduler(batcher=batcher()).next_batch(q, free_slots=0) is None
    assert len(q) == 1, "the queue was drained despite nothing being dispatched"


def test_an_empty_queue_returns_none():
    assert Scheduler(batcher=batcher()).next_batch(Queue(), free_slots=4) is None


def test_a_dispatched_batch_leaves_the_queue():
    q = Queue()
    for i in range(3):
        q.put(r(f"r{i}"))
    b = Scheduler(batcher=batcher()).next_batch(q, free_slots=2)
    assert b is not None and len(q) == 3 - len(b)


# --- routers refuse what they were not told about -----------------------------------------
def test_routing_to_an_undeclared_engine_is_refused_by_name():
    br = BatchRouter({"a": lambda p: None})
    with pytest.raises(DispatchError, match="not a declared engine"):
        br.choose(prefer="b")


def test_a_router_with_no_engines_is_refused():
    with pytest.raises(DispatchError, match="nowhere to route"):
        BatchRouter({})


def test_a_cell_router_with_no_cells_is_refused():
    with pytest.raises(DispatchError, match="routes nowhere"):
        ExecRouter([])


def test_the_same_key_always_lands_on_the_same_cell():
    er = ExecRouter(["x", "y", "z"])
    assert er.route("caller-7")["cell"] == er.route("caller-7")["cell"]


def test_an_engine_failure_is_captured_rather_than_raised():
    def boom(_):
        raise RuntimeError("engine died")
    sent = BatchRouter({"a": boom}).send(batch("q"), {})
    assert sent.ok is False and "engine died" in sent.error and sent.engine == "a"


# --- variants must account for all the traffic ----------------------------------------------
def test_a_split_that_does_not_sum_to_one_hundred_is_refused():
    with pytest.raises(DispatchError, match="sum to 90"):
        VariantDispatcher({"a": 50.0, "b": 40.0})


def test_variant_routing_is_stable_per_caller():
    vd = VariantDispatcher({"a": 50.0, "b": 50.0})
    assert vd.route("caller-1")["variant"] == vd.route("caller-1")["variant"]


def test_variant_routing_without_a_key_is_refused():
    with pytest.raises(DispatchError, match="needs a key"):
        VariantDispatcher({"a": 100.0}).route("")


# --- tenants are ranked by what was SERVED --------------------------------------------------
def test_the_tenant_furthest_behind_its_share_goes_next():
    tr = TenantRouter()
    tr.declare("alpha", 3); tr.declare("beta", 1)
    tr.record("alpha", 1000)
    out = tr.next_tenant(["alpha", "beta"])
    assert out["tenant"] == "beta" and "actually been SERVED" in out["why"]


def test_recording_work_for_an_undeclared_tenant_is_refused():
    with pytest.raises(DispatchError, match="no declared share"):
        TenantRouter().record("nobody", 10)


# --- the pipeline reports the bottleneck, not the sum -----------------------------------------
def test_the_steady_rate_is_set_by_the_slowest_stage_alone():
    a = PipelineScheduler({"admit": 0.001, "form": 0.002, "infer": 19.0}).analyse()
    assert a["bottleneck"] == "infer"
    # the code rounds the reported rate to 4 places, so compare at that precision
    assert a["steady_rate_per_s"] == round(1 / 19.0, 4)
    assert a["latency_s"] > a["bottleneck_s"], "latency is the sum, and it is not the rate"


def test_a_dominant_stage_means_pipelining_buys_nothing():
    a = PipelineScheduler({"admit": 0.001, "infer": 19.0, "egress": 0.001}).analyse()
    assert a["speedup_vs_serial"] < 1.01, "a pipeline dominated by one stage cannot be sped up"


def test_a_stage_with_no_duration_was_not_measured():
    with pytest.raises(DispatchError, match="was not measured"):
        PipelineScheduler({"a": 0.0})


def test_the_assembly_line_is_the_same_analysis_under_another_name():
    assert AssemblyLine({"a": 1.0, "b": 2.0}).analyse()["bottleneck"] == "b"


# --- sequencing is offered, never applied -------------------------------------------------------
def test_length_ordering_is_suggested_and_flags_that_it_overrules_fairness():
    b = Batch(requests=(r("small", 10), r("big", 900)), tokens=910, bound="count")
    out = Sequencer().by_length(b)
    assert out["suggested"] == ["big", "small"] and out["changes"] is True
    assert "overrules a fairness decision" in out["caution"]


# --- the whole path -------------------------------------------------------------------------------
def test_a_full_run_sends_and_delivers_to_everyone_waiting():
    q = Queue()
    for i in range(3):
        q.put(r(f"r{i}"))
    p = Pipeline(scheduler=Scheduler(batcher=batcher()),
                 router=BatchRouter({"e": lambda pay: {"answered": pay["ids"]}}),
                 build_payload=lambda b: {"ids": b.ids})
    out = p.run_once(q, free_slots=2, followers={"r0": ["shadow"]})
    assert out["ran"] and out["ok"]
    assert out["egress"]["complete"] is True
    assert out["egress"]["expected"] == 4     # three queued plus one coalesced behind r0


def test_a_run_with_nothing_queued_says_so_rather_than_failing():
    p = Pipeline(scheduler=Scheduler(batcher=batcher()),
                 router=BatchRouter({"e": lambda pay: None}),
                 build_payload=lambda b: {})
    out = p.run_once(Queue(), free_slots=4)
    assert out["ran"] is False and "nothing to run" in out["why"]


def test_the_runner_bound_is_given_not_chosen():
    with pytest.raises(DispatchError, match="workers must be positive"):
        ParallelRunner(workers=0)
    with pytest.raises(DispatchError, match="no jobs"):
        ParallelRunner(workers=2).run([])


def test_parallel_results_keep_their_order_and_capture_failures():
    out = ParallelRunner(workers=3).run([
        (lambda: 1), (lambda: (_ for _ in ()).throw(ValueError("no"))), (lambda: 3)])
    assert out[0]["result"] == 1 and out[2]["result"] == 3
    assert out[1]["ok"] is False and "ValueError" in out[1]["error"]
