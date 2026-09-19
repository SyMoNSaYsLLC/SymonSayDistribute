# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Residency tests, anchored on what ravencalc measured from symon on 2026-09-19:
32 experts with 4 active, 12.62 MiB per expert per layer, 24 layers of which 12 slide over a
window of 128. The assertions are about SHAPE, so they survive a different checkpoint."""
import pytest

from symonpayload.residency import (
    Chunker, FramePool, MEASURED, Prefetcher, ResidencyError, Slicer, SlidingWindow, Splitter,
    Stager, StreamBuffer, VramBalancer)

EXPERT_BYTES = MEASURED["bytes_per_expert_per_layer"]


# --- nothing measured has a default ------------------------------------------------------
def test_a_prefetcher_refuses_an_unmeasured_bandwidth():
    with pytest.raises(ResidencyError, match="MEASURED and positive"):
        Prefetcher(bytes_per_expert=EXPERT_BYTES, bandwidth_bytes_per_s=0)


def test_a_balancer_refuses_a_negative_free_reading():
    with pytest.raises(ResidencyError, match="not a measurement"):
        VramBalancer({"gpu0": -1})


def test_the_measurement_records_how_it_was_taken():
    assert "ravencalc" in MEASURED["how"] and MEASURED["taken"]
    assert MEASURED["experts_active_per_token"] < MEASURED["experts_total"]


# --- the sliding window is the reason the cache is small ------------------------------------
def test_sliding_layers_save_positions_and_the_saving_widens_with_context():
    sw = SlidingWindow(window=128, layers=24, full_attention_layers=12)
    small = sw.positions_cached(16384)["saved_fraction"]
    large = sw.positions_cached(131072)["saved_fraction"]
    assert 0 < small < 1 and large >= small, \
        "a fixed window against a growing context should save proportionally more, not less"


def test_a_stack_with_no_sliding_layers_saves_nothing():
    sw = SlidingWindow(window=128, layers=24, full_attention_layers=24)
    assert sw.positions_cached(4096)["saved_fraction"] == 0.0


def test_an_impossible_layer_split_is_refused():
    with pytest.raises(ResidencyError, match="not a layer stack"):
        SlidingWindow(window=128, layers=4, full_attention_layers=9)


# --- prefetch answers whether it can arrive, not whether to do it ------------------------------
def test_a_prefetch_that_cannot_arrive_in_time_says_it_buys_nothing():
    pf = Prefetcher(bytes_per_expert=EXPERT_BYTES, bandwidth_bytes_per_s=1e8)
    out = pf.in_time(experts=4, available_ms=1.0)
    assert out["arrives_in_time"] is False and "buys nothing" in out["why"]


def test_page_in_time_scales_with_the_number_of_experts():
    pf = Prefetcher(bytes_per_expert=EXPERT_BYTES, bandwidth_bytes_per_s=16e9)
    assert pf.page_in_ms(4) == pytest.approx(4 * pf.page_in_ms(1))


# --- buffers refuse rather than dropping -------------------------------------------------------
def test_a_full_stream_buffer_refuses_because_a_dropped_token_is_a_wrong_answer():
    b = StreamBuffer(capacity=2)
    b.push(1); b.push(2)
    with pytest.raises(ResidencyError, match="wrong answer, not"):
        b.push(3)
    assert b.dropped == 1


def test_a_pool_that_has_served_nothing_reports_no_reuse_rate():
    p = FramePool(size_bytes=1024, capacity=2)
    assert p.stats()["reuse_rate"] is None
    assert "has served nothing" in p.stats()["note"]


def test_a_pool_reuses_rather_than_allocating_and_the_rate_shows_it():
    p = FramePool(size_bytes=1024, capacity=2)
    a = p.take(); p.give_back(a); p.take()
    assert p.reused == 1 and p.allocated == 1 and p.stats()["reuse_rate"] == 0.5


def test_a_pool_refuses_to_become_an_allocator():
    p = FramePool(size_bytes=1024, capacity=1)
    p.take()
    with pytest.raises(ResidencyError, match="quietly becomes an allocator"):
        p.take()


# --- placement is by measured capacity ------------------------------------------------------------
def test_placing_more_than_any_device_holds_names_what_is_free():
    vb = VramBalancer({"gpu0": 1000, "gpu1": 2000})
    with pytest.raises(ResidencyError, match="no device has it free"):
        vb.place("huge", 5000)


def test_a_preferred_device_is_honoured_even_when_another_has_more_room():
    vb = VramBalancer({"gpu0": 16_000_000_000, "host": 94_000_000_000})
    out = vb.place("experts", 10_000_000_000, prefer="gpu0")
    assert out["device"] == "gpu0"


def test_an_unknown_preferred_device_is_refused():
    with pytest.raises(ResidencyError, match="not a known device"):
        VramBalancer({"gpu0": 10}).place("x", 1, prefer="gpu9")


# --- chunking keeps the remainder ------------------------------------------------------------------
def test_the_final_short_chunk_is_returned_rather_than_padded_or_dropped():
    out = Chunker(size=100).spans(250)
    assert out["chunks"] == 3
    assert out["spans"][-1] == (200, 250) and out["remainder"] == 50


def test_overlap_not_smaller_than_the_chunk_is_refused():
    with pytest.raises(ResidencyError, match="contain each other"):
        Chunker(size=100, overlap=100)


def test_overlapping_chunks_advance_by_the_step():
    out = Chunker(size=100, overlap=20).spans(260)
    starts = [s for s, _ in out["spans"]]
    assert starts[1] - starts[0] == 80


# --- splitting refuses to produce useless fragments --------------------------------------------------
def test_something_that_already_fits_is_not_split():
    out = Splitter(max_length=1000, min_piece=100).split(500)
    assert out["split"] is False and "only add joins" in out["why"]


def test_pieces_below_the_floor_are_refused_rather_than_produced():
    """The case that bites is a sequence JUST over the limit, not a huge one. 100,000 over a
    limit of 100 evens to exactly 100 and is fine; 101 needs two pieces and evens to 51, which
    is below a floor of 90. My first version of this test used the huge one and did not fire."""
    with pytest.raises(ResidencyError, match="worse than refusing"):
        Splitter(max_length=100, min_piece=90).split(101)
    # and the huge one is fine, because evening lands it back on the limit
    out = Splitter(max_length=100, min_piece=90).split(100000)
    assert out["piece_length"] == 100


def test_a_split_is_evened_so_the_last_piece_is_not_a_stub():
    out = Splitter(max_length=1000, min_piece=10).split(2100)
    lengths = [b - a for a, b in out["pieces"]]
    assert max(lengths) - min(lengths) <= 1, f"uneven split {lengths}"


# --- slicing will not hide a load imbalance -----------------------------------------------------------
def test_an_uneven_slice_is_refused_unless_explicitly_allowed():
    with pytest.raises(ResidencyError, match="silent load imbalance"):
        Slicer().slice((2880, 4096), axis=1, parts=3)
    out = Slicer().slice((2880, 4096), axis=1, parts=3, allow_remainder=True)
    assert out["even"] is False and out["imbalance"] > 0
    assert sum(out["sizes"]) == 4096


def test_an_even_slice_reports_no_imbalance():
    out = Slicer().slice((2880, 4096), axis=1, parts=4)
    assert out["even"] and out["imbalance"] == 0.0
    assert [tuple(s) for s in out["shapes"]] == [(2880, 1024)] * 4


def test_slicing_an_axis_that_does_not_exist_is_refused():
    with pytest.raises(ResidencyError, match="outside a 2-dimensional shape"):
        Slicer().slice((10, 10), axis=5, parts=2)


# --- the stager cannot move what it does not hold -------------------------------------------------------
def test_moving_something_never_admitted_is_refused():
    with pytest.raises(ResidencyError, match="leaves the real copy"):
        Stager().move("ghost", "gpu0")


def test_admitting_the_same_thing_twice_is_refused():
    s = Stager(); s.admit("a", "host")
    with pytest.raises(ResidencyError, match="two records of one thing"):
        s.admit("a", "gpu0")


def test_a_move_to_where_it_already_is_is_not_a_move():
    s = Stager(); s.admit("a", "host")
    out = s.move("a", "host")
    assert out["moved"] is False and s.moves == []
