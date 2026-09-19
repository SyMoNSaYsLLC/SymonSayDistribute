# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Admission tests. Most of these are refusals, because the refusals are the product."""
import pytest

from symonpayload.admit import (
    Aggregator, Coalescer, Gatekeeper, Ingress, Prioritizer, Queue, Refused, Request, TriageGate)


def r(i, tokens=10, **kw):
    return Request(id=i, tokens=tokens, **kw)


# --- a request that cannot be reported on is not a request --------------------------------
def test_request_needs_an_id():
    with pytest.raises(ValueError, match="needs an id"):
        Request(id="", tokens=5)


def test_tokens_must_be_counted_not_guessed():
    with pytest.raises(ValueError, match="counted and positive"):
        Request(id="a", tokens=0)


def test_a_passed_deadline_is_not_a_deadline():
    with pytest.raises(ValueError, match="already passed"):
        Request(id="a", tokens=5, deadline_ms=-1)


# --- ingress refuses rather than growing --------------------------------------------------
def test_ingress_refuses_at_capacity_with_the_number():
    ing = Ingress(capacity=2)
    ing.offer(r("a")); ing.offer(r("b"))
    with pytest.raises(Refused, match="at capacity \\(2\\)"):
        ing.offer(r("c"))


def test_zero_capacity_is_refused_at_construction():
    with pytest.raises(ValueError, match="zero-capacity"):
        Ingress(capacity=0)


def test_drain_empties():
    ing = Ingress(capacity=3); ing.offer(r("a"))
    assert [x.id for x in ing.drain()] == ["a"]
    assert len(ing) == 0


# --- ordering -----------------------------------------------------------------------------
def test_deadlines_go_first_and_none_goes_last():
    p = Prioritizer()
    out = p.order([r("none"), r("late", deadline_ms=900), r("soon", deadline_ms=100)])
    assert [x.id for x in out] == ["soon", "late", "none"]


def test_equal_deadlines_keep_arrival_order_so_nobody_starves():
    p = Prioritizer()
    out = p.order([r("first", at_ms=1, deadline_ms=50), r("second", at_ms=2, deadline_ms=50)])
    assert [x.id for x in out] == ["first", "second"]


# --- coalescing is by declared fingerprint, never by guessing -------------------------------
def test_identical_fingerprints_follow_one_leader():
    c = Coalescer()
    assert c.admit(r("a", fingerprint="fp")) is None
    assert c.admit(r("b", fingerprint="fp")) == "a"
    assert c.followers("a") == ["b"]


def test_empty_fingerprint_never_coalesces():
    c = Coalescer()
    assert c.admit(r("a", fingerprint="")) is None
    assert c.admit(r("b", fingerprint="")) is None


def test_release_hands_back_the_waiting_and_frees_the_fingerprint():
    c = Coalescer()
    c.admit(r("a", fingerprint="fp")); c.admit(r("b", fingerprint="fp"))
    assert c.release("a") == ["b"]
    assert c.admit(r("d", fingerprint="fp")) is None   # a new leader, not a stale one


# --- the gate names which limit it hit ------------------------------------------------------
def test_too_many_tokens_names_both_numbers():
    g = TriageGate(max_tokens=100)
    with pytest.raises(Refused, match="200 tokens exceeds the 100"):
        g.check(r("a", tokens=200))


def test_unknown_tenant_is_refused_by_name():
    g = TriageGate(max_tokens=100, tenants={"alpha"})
    with pytest.raises(Refused, match="'beta' is not one"):
        g.check(r("a", tenant="beta"))


def test_route_is_the_same_gate_not_a_second_policy():
    g = TriageGate(max_tokens=100)
    assert g.route(r("a", deadline_ms=5)) == "urgent"
    assert g.route(r("b")) == "bulk"
    with pytest.raises(Refused):
        g.route(r("c", tokens=500))


# --- queue ----------------------------------------------------------------------------------
def test_queue_takes_in_priority_order_and_keeps_the_rest():
    q = Queue()
    for x in (r("none"), r("soon", deadline_ms=10)):
        q.put(x)
    assert [x.id for x in q.take(1)] == ["soon"]
    assert len(q) == 1


def test_take_zero_is_a_mistake_not_an_empty_list():
    with pytest.raises(ValueError, match="positive count"):
        Queue().take(0)


# --- aggregation uses an injected clock so the boundary is testable --------------------------
def test_window_expires_exactly_at_the_boundary():
    now = [0]
    a = Aggregator(window_ms=10, clock=lambda: now[0])
    a.add(r("a"))
    now[0] = 9
    assert not a.expired
    now[0] = 10
    assert a.expired


def test_an_empty_aggregator_has_not_expired():
    a = Aggregator(window_ms=10, clock=lambda: 10_000)
    assert not a.expired


def test_close_resets_the_window():
    now = [0]
    a = Aggregator(window_ms=5, clock=lambda: now[0])
    a.add(r("a")); now[0] = 99
    assert [x.id for x in a.close()] == ["a"]
    assert a.age_ms == 0 and not a.expired


def test_zero_window_never_aggregates_and_is_refused():
    with pytest.raises(ValueError, match="never aggregates"):
        Aggregator(window_ms=0, clock=lambda: 0)


# --- the gatekeeper records refusals so they can be counted ----------------------------------
def test_gatekeeper_records_the_refusal_it_raised():
    gk = Gatekeeper(gate=TriageGate(max_tokens=50), ingress=Ingress(capacity=4))
    with pytest.raises(Refused):
        gk.admit(r("big", tokens=999))
    assert gk.refusals == [("big", "999 tokens exceeds the 50 this unit accepts")]


def test_gatekeeper_queues_a_leader_and_not_its_follower():
    gk = Gatekeeper(gate=TriageGate(max_tokens=500), ingress=Ingress(capacity=4))
    assert gk.admit(r("a", fingerprint="fp")) is None
    assert gk.admit(r("b", fingerprint="fp")) == "a"
    assert len(gk.queue) == 1
