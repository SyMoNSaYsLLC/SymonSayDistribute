# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Formation tests. The bound a batch reports is as much the product as the batch is."""
import pytest

from symonpayload.admit import Request
from symonpayload.form import (
    Batch, Bundler, CannotForm, Concatenator, DynamicBatcher, MicroBatch, Packer, Padder,
    Reservoir, Stacker, Staging, TokenBudget)


def r(i, tokens):
    return Request(id=i, tokens=tokens)


def batcher(max_tokens=100, max_requests=10, window_ms=50, now=None):
    clock = (lambda: 0) if now is None else (lambda: now[0])
    return DynamicBatcher(max_tokens=max_tokens, max_requests=max_requests,
                          window_ms=window_ms, clock=clock)


# --- the budget -----------------------------------------------------------------------------
def test_budget_refuses_what_does_not_fit_and_names_both_numbers():
    b = TokenBudget(100); b.spend(60)
    with pytest.raises(CannotForm, match="50 tokens does not fit in the 40 left of 100"):
        b.spend(50)


def test_a_ceiling_of_zero_is_refused():
    with pytest.raises(ValueError, match="must be positive"):
        TokenBudget(0)


# --- an empty batch is a bug, not an outcome ------------------------------------------------
def test_an_empty_batch_cannot_be_constructed():
    with pytest.raises(ValueError, match="empty batch is not a batch"):
        Batch(requests=(), tokens=0, bound="count")


def test_an_unknown_bound_is_refused():
    with pytest.raises(ValueError, match="unknown bound"):
        Batch(requests=(r("a", 1),), tokens=1, bound="vibes")


# --- which bound tripped is the point --------------------------------------------------------
def test_token_ceiling_stops_formation_and_says_so():
    b = batcher(max_tokens=100)
    out = b.form([r("a", 60), r("b", 60)])
    assert out.ids == ["a"] and out.bound == "tokens" and out.tokens == 60


def test_request_count_stops_formation_and_says_so():
    b = batcher(max_tokens=1000, max_requests=2)
    out = b.form([r("a", 1), r("b", 1), r("c", 1)])
    assert out.ids == ["a", "b"] and out.bound == "count"


def test_running_out_of_work_is_drained_not_a_bound():
    b = batcher(max_tokens=1000, max_requests=10)
    out = b.form([r("a", 1), r("b", 1)])
    assert out.ids == ["a", "b"] and out.bound == "drained"


def test_the_window_stops_formation_once_something_is_held():
    now = [0]
    b = batcher(max_tokens=1000, max_requests=10, window_ms=10, now=now)
    # first request is taken, then the window passes before the second is considered
    pending = [r("a", 1), r("b", 1), r("c", 1)]
    def clock():
        now[0] += 20
        return now[0]
    b.clock = clock
    out = b.form(pending, opened_at_ms=0)
    assert out.bound == "window" and out.ids == ["a"]


def test_nothing_pending_is_a_refusal_not_an_empty_batch():
    with pytest.raises(CannotForm, match="nothing pending"):
        batcher().form([])


def test_a_request_too_big_to_ever_batch_says_it_belonged_at_admission():
    with pytest.raises(CannotForm, match="should have been refused at admission"):
        batcher(max_tokens=50).form([r("huge", 500)])


def test_formation_keeps_the_order_it_was_given():
    b = batcher(max_tokens=1000, max_requests=3)
    out = b.form([r("z", 1), r("a", 1), r("m", 1)])
    assert out.ids == ["z", "a", "m"]      # priority was decided upstream, not re-decided here


# --- micro-batching ---------------------------------------------------------------------------
def test_split_produces_pieces_that_each_fit():
    batch = Batch(tuple(r(str(i), 40) for i in range(5)), 200, "count")
    pieces = MicroBatch(max_tokens=100).split(batch)
    assert [p.tokens for p in pieces] == [80, 80, 40]
    assert sum(len(p) for p in pieces) == 5


def test_a_member_larger_than_the_micro_batch_is_refused():
    batch = Batch((r("a", 500),), 500, "count")
    with pytest.raises(CannotForm, match="no micro-batch of 100 holds it"):
        MicroBatch(max_tokens=100).split(batch)


# --- padding reports its cost -------------------------------------------------------------------
def test_padding_waste_is_returned_not_hidden():
    out = Padder().pad([200, 200, 200, 8000])
    assert out["width"] == 8000 and out["allocated"] == 32000
    assert out["wasted"] == 32000 - 8600
    assert out["waste_fraction"] == round((32000 - 8600) / 32000, 4)


def test_cannot_pad_below_the_longest_member():
    with pytest.raises(CannotForm, match="longest member is 90"):
        Padder().pad([10, 90], pad_to=50)


def test_padding_nothing_is_a_refusal():
    with pytest.raises(CannotForm, match="nothing to pad"):
        Padder().pad([])


# --- stacking refuses to pad for you ----------------------------------------------------------
def test_ragged_input_is_refused_rather_than_silently_padded():
    with pytest.raises(CannotForm, match="ragged: member 0 is"):
        Stacker().stack([(4, 8), (4, 9)])


def test_equal_shapes_stack_and_gain_a_leading_dimension():
    assert Stacker().stack([(4, 8), (4, 8), (4, 8)]) == (3, 4, 8)


# --- concatenation records its boundaries -------------------------------------------------------
def test_boundaries_come_back_so_the_result_can_be_split_again():
    out = Concatenator().join([3, 5, 2])
    assert out["total"] == 10
    assert out["boundaries"] == [(0, 3), (3, 8), (8, 10)]


def test_a_zero_length_member_is_refused():
    with pytest.raises(ValueError, match="zero-length member"):
        Concatenator().join([3, 0])


# --- packing beats padding when members vary -----------------------------------------------------
def test_packing_wastes_less_than_padding_on_varied_members():
    lengths = [200, 200, 200, 800]
    packed = Packer().pack(lengths, width=800)
    padded = Padder().pad(lengths)
    assert packed["wasted"] < padded["wasted"]
    assert packed["rows"] == 2


def test_a_member_wider_than_the_row_is_refused():
    with pytest.raises(CannotForm, match="does not fit a width of 100"):
        Packer().pack([50, 500], width=100)


# --- bundling keeps the mapping back to callers ----------------------------------------------------
def test_a_missing_body_is_named():
    batch = Batch((r("a", 1), r("b", 1)), 2, "count")
    with pytest.raises(CannotForm, match="no body supplied for b"):
        Bundler().bundle(batch, {"a": {}})


def test_bundle_preserves_batch_order():
    batch = Batch((r("b", 1), r("a", 1)), 2, "count")
    out = Bundler().bundle(batch, {"a": {"x": 1}, "b": {"x": 2}})
    assert out["order"] == ["b", "a"] and out["items"] == [{"x": 2}, {"x": 1}]


# --- staging makes a stall visible -------------------------------------------------------------------
def test_staging_reports_depth_and_tokens_held():
    s = Staging()
    s.put(Batch((r("a", 30),), 30, "count")); s.put(Batch((r("b", 20),), 20, "count"))
    assert s.depth == 2 and s.tokens_held == 50
    assert s.take().ids == ["a"] and s.depth == 1


def test_taking_from_empty_staging_is_a_refusal():
    with pytest.raises(CannotForm, match="nothing staged"):
        Staging().take()


# --- the reservoir refills on a boundary, not continuously ---------------------------------------------
def test_drawing_more_than_is_left_is_refused():
    res = Reservoir(per_window=100); res.draw(90)
    with pytest.raises(CannotForm, match="20 tokens exceeds the 10 left"):
        res.draw(20)


def test_refill_restores_the_window_and_counts_it():
    res = Reservoir(per_window=100); res.draw(100); res.refill()
    assert res.available == 100 and res.windows == 1
