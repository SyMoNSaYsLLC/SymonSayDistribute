# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Flow-control tests, anchored on the measurement this module waited for.

The reference run on 2026-09-19: 6.8 tok/s at concurrency 1, 11.2 aggregate at 2, p50 19.02 s.
These assert the SHAPE that measurement showed — sublinear scaling, per-stream slowdown — not
the digits, so they still hold when the card or the context changes.
"""
import pytest

from symonpayload.flow import (
    REFERENCE, AdaptiveThrottle, Allocator, Concurrency, FlowError, LoadShifter, SLA, Sample,
    Throughput, WindowStager, WindowTuner)


def measured() -> Throughput:
    t = Throughput()
    for _ in range(4):
        t.observe(Sample(latency_s=18.714, tokens=128, concurrency=1))
    for _ in range(6):
        t.observe(Sample(latency_s=22.856, tokens=128, concurrency=2))
    return t


# --- nothing measured has a default ----------------------------------------------------
def test_an_sla_refuses_a_rate_nobody_measured():
    with pytest.raises(FlowError, match="MEASURED and positive"):
        SLA(target_latency_s=10, measured_tok_s=0)


def test_a_window_tuner_refuses_unmeasured_inputs():
    with pytest.raises(FlowError, match="measured and positive"):
        WindowTuner(measured_tok_s=0, typical_tokens=128)


def test_a_load_shifter_refuses_to_move_work_onto_an_unmeasured_engine():
    s = LoadShifter()
    with pytest.raises(FlowError, match="will not shift"):
        s.choose()


def test_a_throttle_has_no_default_target_or_ceiling():
    with pytest.raises(FlowError, match="target latency must be positive"):
        AdaptiveThrottle(target_latency_s=0, ceiling=4)
    with pytest.raises(FlowError, match="do not describe a range"):
        AdaptiveThrottle(target_latency_s=10, ceiling=1, floor=4)


# --- what the measurement actually showed -------------------------------------------------
def test_concurrency_scales_sublinearly_as_measured():
    g = measured().marginal_gain(1, 2)
    assert g["ratio"] < g["ideal_ratio"], "doubling concurrency did not double throughput"
    assert 0 < g["efficiency"] < 1
    assert g["gained_tok_s"] > 0


def test_each_stream_slows_when_another_joins():
    by = measured().by_concurrency()
    assert by[2]["per_stream_tok_s"] < by[1]["per_stream_tok_s"], \
        "the per-stream rate should fall as concurrency rises; aggregate is not the whole story"


def test_aggregate_still_rises_even_though_each_stream_slows():
    by = measured().by_concurrency()
    assert by[2]["aggregate_tok_s"] > by[1]["aggregate_tok_s"]


def test_marginal_gain_refuses_to_extrapolate_to_unmeasured_concurrency():
    with pytest.raises(FlowError, match="will not extrapolate"):
        measured().marginal_gain(1, 8)


def test_the_reference_measurement_is_recorded_with_how_it_was_taken():
    assert "bench-gateway.sh" in REFERENCE["how"]
    assert REFERENCE["taken"] and REFERENCE["context"] == 32768


def test_throughput_refuses_to_report_nothing_as_zero():
    with pytest.raises(FlowError, match="no throughput to report"):
        Throughput().summary()


# --- the hard ceiling refuses rather than queueing --------------------------------------------
def test_a_full_limiter_refuses_and_says_why_it_does_not_queue():
    c = Concurrency(limit=2)
    c.acquire(); c.acquire()
    with pytest.raises(FlowError, match="refuses rather than queueing"):
        c.acquire()
    assert c.refused == 1


def test_releasing_more_than_acquired_is_an_error_not_a_clamp():
    with pytest.raises(FlowError, match="count is wrong somewhere"):
        Concurrency(limit=1).release()


# --- the throttle moves on evidence ------------------------------------------------------------
def test_exceeding_the_target_lowers_immediately():
    th = AdaptiveThrottle(target_latency_s=20.0, ceiling=4, floor=1)
    th.limit = 3
    row = th.observe(latency_s=25.0)
    assert row["limit_after"] == 2 and "exceeded the target" in row["why"]


def test_it_will_not_raise_when_the_last_increase_bought_nothing():
    t = Throughput()
    for _ in range(3):
        t.observe(Sample(latency_s=10.0, tokens=100, concurrency=1))
    for _ in range(3):
        t.observe(Sample(latency_s=20.0, tokens=100, concurrency=2))   # no aggregate gain
    th = AdaptiveThrottle(target_latency_s=60.0, ceiling=8, floor=1)
    th.limit = 2
    row = th.observe(latency_s=5.0, throughput=t)
    assert row["limit_after"] == 2, "raised despite the previous step buying nothing"
    assert "for no work" in row["why"]


def test_it_raises_when_latency_allows_and_the_last_step_paid():
    th = AdaptiveThrottle(target_latency_s=60.0, ceiling=8, floor=1)
    th.limit = 1
    row = th.observe(latency_s=5.0, throughput=measured())
    assert row["limit_after"] == 2


def test_it_never_goes_below_the_floor_or_above_the_ceiling():
    th = AdaptiveThrottle(target_latency_s=1.0, ceiling=3, floor=2)
    th.limit = 2
    th.observe(latency_s=99.0)
    assert th.limit == 2


# --- the sla sheds on reachability, not on queue length -------------------------------------------
def test_a_deadline_that_cannot_be_met_is_shed_with_the_arithmetic():
    s = SLA(target_latency_s=30.0, measured_tok_s=6.8)
    ok = s.reachable(expected_tokens=128)
    assert ok["meets_deadline"] and not ok["shed"]
    bad = s.reachable(expected_tokens=128, ahead_in_queue=3)
    assert bad["shed"] and "promises what cannot be delivered" in bad["why"]


def test_a_long_queue_served_fast_is_not_shed():
    fast = SLA(target_latency_s=30.0, measured_tok_s=500.0)
    assert fast.reachable(expected_tokens=128, ahead_in_queue=10)["meets_deadline"]


# --- the window is bounded by measurement ------------------------------------------------------------
def test_the_window_never_exceeds_one_service_time():
    w = WindowTuner(measured_tok_s=6.8, typical_tokens=128)
    out = w.suggest(arrivals_per_s=0.01, max_wait_s=999)
    assert out["window_s"] <= out["service_s"]


def test_the_window_is_capped_by_the_callers_maximum_wait():
    w = WindowTuner(measured_tok_s=6.8, typical_tokens=128)
    out = w.suggest(arrivals_per_s=0.01, max_wait_s=0.5)
    assert out["window_s"] == 0.5 and out["bounded_by"] == "the caller's maximum wait"


# --- staging is reviewable --------------------------------------------------------------------------
def test_a_staged_change_needs_a_reason_and_does_not_take_effect():
    st = WindowStager(current_ms=2000)
    with pytest.raises(FlowError, match="needs a reason"):
        st.stage(500, "   ")
    d = st.stage(500, "measured inter-arrival fell to 0.5s")
    assert d["changes"] and st.current_ms == 2000
    applied = st.apply()
    assert applied["now_ms"] == 500 and st.current_ms == 500


def test_applying_nothing_is_refused():
    with pytest.raises(FlowError, match="nothing staged"):
        WindowStager(current_ms=100).apply()


# --- shares are relative and the remainder goes somewhere deliberate -----------------------------------
def test_slots_sum_to_the_total_with_no_fractional_loss():
    a = Allocator()
    a.set_share("alpha", 2); a.set_share("beta", 1); a.set_share("gamma", 1)
    got = a.slots(5)
    assert sum(got.values()) == 5
    assert got["alpha"] >= got["beta"]


def test_allocating_to_nobody_is_refused():
    with pytest.raises(FlowError, match="allocating to nobody"):
        Allocator().slots(4)
