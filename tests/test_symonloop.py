# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonloop tests.

Every one uses a ledger under tmp_path — the real one at ~/symoneural-run/loop is never
touched. And every one supplies `now`, so a seven-day expiry is checked in microseconds rather
than by waiting a week.
"""
import importlib
import json
import os
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from symonloop import ledger as L

TOKEN = uuid.uuid4().hex
T0 = datetime(2026, 9, 19, 18, 0)


def iso(dt):
    return dt.isoformat()


@pytest.fixture(autouse=True)
def ledger_dir(monkeypatch, tmp_path):
    """Every test gets its own ledger. The operator's must never be written by a test run."""
    monkeypatch.setenv("SYM_LOOP_DIR", str(tmp_path / "loop"))
    return tmp_path / "loop"


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` actually exercises the guard. On a loopback bind it
    # returns before comparing anything, and every authenticated test would pass with no token.
    monkeypatch.setenv("SYM_LOOP_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_LOOP_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def a_job(**kw):
    d = dict(work="say hello", cadence="*/5 * * * *",
             next_fire=iso(T0 + timedelta(minutes=5)), now=iso(T0))
    d.update(kw)
    return L.add(**d)


# --- THE POINT OF THE COMPONENT: it survives the process ------------------------------------
def test_a_job_outlives_the_module_that_created_it():
    """Reload the module and the job is still there. This is the whole capability."""
    rec = a_job(job_id="survivor")
    importlib.reload(L)
    again = L.get("survivor")
    assert again["work"] == rec["work"] and again["next_fire"] == rec["next_fire"]


def test_the_record_is_plain_json_on_disk(ledger_dir):
    """Readable without this code. A ledger only its own program can read is a hostage."""
    a_job(job_id="readable")
    on_disk = json.loads((ledger_dir / "readable.json").read_text())
    assert on_disk["id"] == "readable" and on_disk["state"] == "active"


def test_a_write_is_atomic_so_a_crash_leaves_one_whole_record():
    import inspect
    src = inspect.getsource(L._write)
    assert "os.replace" in src, "a non-atomic write can leave half a record after a kill"
    assert "fsync" in src, "without fsync the rename can land before the bytes do"


def test_no_temporary_files_are_left_behind(ledger_dir):
    for i in range(3):
        a_job(job_id=f"job-{i}")
    assert not list(ledger_dir.glob(".tmp-*")), "a leaked temp file is a half-written record"


# --- an id becomes a filename, so it is checked against a whitelist -------------------------
@pytest.mark.parametrize("bad", ["../escape", "a/b", "", "x", "A-Upper", "has space",
                                 "..", "a" * 65, "nul\x00byte"])
def test_a_dangerous_or_malformed_id_is_refused(bad):
    with pytest.raises(L.LedgerError):
        L.path_for(bad)


def test_a_traversal_id_cannot_write_outside_the_ledger(tmp_path):
    with pytest.raises(L.LedgerError):
        a_job(job_id="../../escaped")
    assert not (tmp_path / "escaped.json").exists()


# --- refusals that keep the ledger meaningful ------------------------------------------------
def test_work_with_no_content_is_refused():
    with pytest.raises(L.LedgerError, match="timer nobody can act on"):
        a_job(work="   ")


def test_a_job_with_no_cadence_is_refused():
    with pytest.raises(L.LedgerError, match="when it is due again"):
        a_job(cadence="")


def test_an_id_is_not_reused():
    a_job(job_id="taken")
    with pytest.raises(L.LedgerError, match="already exists"):
        a_job(job_id="taken")


@pytest.mark.parametrize("field", ["next_fire", "now"])
def test_a_non_iso_timestamp_is_refused_by_name(field):
    with pytest.raises(L.LedgerError, match=field):
        a_job(**{field: "sometime tuesday"})


# --- due: the question the adapter actually asks ---------------------------------------------
def test_a_job_is_not_due_before_its_time():
    a_job(job_id="later")
    assert L.due(iso(T0 + timedelta(minutes=1)))["due_count"] == 0


def test_a_job_is_due_at_its_time():
    a_job(job_id="ontime")
    d = L.due(iso(T0 + timedelta(minutes=5)))
    assert d["due_count"] == 1 and d["due"][0]["id"] == "ontime"


def test_grace_brings_a_job_forward_but_only_by_what_was_asked():
    a_job(job_id="graced")
    at = iso(T0 + timedelta(minutes=4))
    assert L.due(at)["due_count"] == 0
    assert L.due(at, grace_s=60)["due_count"] == 1
    assert L.due(at, grace_s=59)["due_count"] == 0


def test_due_returns_the_oldest_first():
    L.add(work="b", cadence="x", next_fire=iso(T0 + timedelta(minutes=9)), now=iso(T0),
          job_id="second")
    L.add(work="a", cadence="x", next_fire=iso(T0 + timedelta(minutes=2)), now=iso(T0),
          job_id="first")
    d = L.due(iso(T0 + timedelta(minutes=10)))
    assert [j["id"] for j in d["due"]] == ["first", "second"]


def test_a_stopped_job_is_never_due():
    a_job(job_id="halted")
    L.stop("halted", now=iso(T0))
    assert L.due(iso(T0 + timedelta(days=1)))["due_count"] == 0


# --- expiry is evaluated on read, so a lapse while nothing ran still counts -------------------
def test_a_job_expires_without_anything_having_been_awake():
    """Seven days checked in microseconds. Expiry must not need a sweep to have happened."""
    a_job(job_id="lapsed", expires_days=7)
    d = L.due(iso(T0 + timedelta(days=8)))
    assert d["due_count"] == 0
    assert [j["id"] for j in d["expired_now"]] == ["lapsed"]
    assert L.get("lapsed")["state"] == "expired"


def test_expiry_is_persisted_not_merely_reported():
    a_job(job_id="gone", expires_days=1)
    L.due(iso(T0 + timedelta(days=2)))
    importlib.reload(L)
    assert L.get("gone")["state"] == "expired"


def test_a_job_with_no_expiry_never_lapses():
    a_job(job_id="forever", expires_days=0)
    assert L.get("forever")["expires"] is None
    assert L.due(iso(T0 + timedelta(days=4000)))["due_count"] == 1


def test_a_negative_expiry_is_refused():
    with pytest.raises(L.LedgerError, match="negative"):
        a_job(expires_days=-1)


# --- firing ----------------------------------------------------------------------------------
def test_recording_a_fire_advances_the_job():
    a_job(job_id="ticks")
    r = L.record_fire("ticks", now=iso(T0 + timedelta(minutes=5)),
                      next_fire=iso(T0 + timedelta(minutes=10)))
    assert r["fire_count"] == 1
    assert r["last_fire"] == iso(T0 + timedelta(minutes=5))
    assert L.due(iso(T0 + timedelta(minutes=5)))["due_count"] == 0


def test_a_next_fire_in_the_past_is_refused_because_it_would_spin():
    """The failure this catches: a job due the instant it is recorded, forever."""
    a_job(job_id="spinner")
    with pytest.raises(L.LedgerError, match="spin"):
        L.record_fire("spinner", now=iso(T0 + timedelta(minutes=5)),
                      next_fire=iso(T0 + timedelta(minutes=1)))


def test_a_next_fire_equal_to_now_is_also_refused():
    a_job(job_id="equal")
    t = iso(T0 + timedelta(minutes=5))
    with pytest.raises(L.LedgerError, match="spin"):
        L.record_fire("equal", now=t, next_fire=t)


def test_a_fire_cannot_be_recorded_against_a_stopped_job():
    a_job(job_id="dead")
    L.stop("dead", now=iso(T0))
    with pytest.raises(L.LedgerError, match="not active"):
        L.record_fire("dead", now=iso(T0), next_fire=iso(T0 + timedelta(hours=1)))


def test_the_fire_count_survives_a_reload():
    a_job(job_id="counted")
    for i in range(1, 4):
        L.record_fire("counted", now=iso(T0 + timedelta(minutes=5 * i)),
                      next_fire=iso(T0 + timedelta(minutes=5 * (i + 1))))
    importlib.reload(L)
    assert L.get("counted")["fire_count"] == 3


# --- stop and resume ---------------------------------------------------------------------------
def test_stopping_keeps_the_record_rather_than_removing_it(ledger_dir):
    a_job(job_id="kept")
    L.stop("kept", now=iso(T0), reason="not needed today")
    assert (ledger_dir / "kept.json").exists()
    assert L.get("kept")["stopped_reason"] == "not needed today"


def test_a_stopped_job_can_be_resumed():
    a_job(job_id="back")
    L.stop("back", now=iso(T0))
    L.resume("back", now=iso(T0 + timedelta(hours=1)),
             next_fire=iso(T0 + timedelta(hours=2)))
    assert L.get("back")["state"] == "active"


def test_an_expired_job_is_refused_rather_than_quietly_revived():
    """Expiry means nobody renewed it. Reviving it resurrects work with no reason re-established."""
    a_job(job_id="lapsed2", expires_days=1)
    L.due(iso(T0 + timedelta(days=2)))
    with pytest.raises(L.LedgerError, match="expired"):
        L.resume("lapsed2", now=iso(T0 + timedelta(days=2)),
                 next_fire=iso(T0 + timedelta(days=3)))


def test_resuming_an_active_job_is_refused():
    a_job(job_id="already")
    with pytest.raises(L.LedgerError, match="already active"):
        L.resume("already", now=iso(T0), next_fire=iso(T0 + timedelta(hours=1)))


# --- an unreadable record is NAMED, never skipped -----------------------------------------------
def test_a_corrupt_record_is_reported_rather_than_silently_dropped(ledger_dir):
    """A ledger that hides a broken record reports a cleaner world than the one it is in."""
    a_job(job_id="fine")
    (ledger_dir / "broken.json").write_text("{not json")
    j = L.jobs()
    assert j["count"] == 1
    assert [b["file"] for b in j["unreadable"]] == ["broken.json"]
    assert "listed rather than skipped" in j["why"]


def test_a_corrupt_record_does_not_stop_due_from_answering(ledger_dir):
    a_job(job_id="good-one")
    (ledger_dir / "bad.json").write_text("<<<")
    assert L.due(iso(T0 + timedelta(minutes=5)))["due_count"] == 1


def test_an_unknown_state_filter_is_refused():
    with pytest.raises(L.LedgerError, match="not a state"):
        L.jobs(state="sideways")


# --- it does not execute, and that is load-bearing -----------------------------------------------
def test_the_ledger_never_runs_anything():
    """Execution belongs to an adapter. A ledger that runs work cannot be asked a question."""
    import inspect
    src = inspect.getsource(L)
    for banned in ("subprocess", "os.system", "eval(", "exec(", "Popen"):
        assert banned not in src, f"{banned} makes this an executor, not a ledger"


def test_the_ledger_does_not_parse_cadence():
    """symonscheduler owns that. A second implementation is a second answer that can drift."""
    import inspect
    src = inspect.getsource(L)
    assert "next_fire" in src
    for banned in ("def parse", "crontab", "*/", "field_values"):
        assert banned not in src, f"{banned} duplicates symonscheduler"


# --- over http ------------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    monkeypatch.setenv("SYM_LOOP_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_LOOP_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonloop/health").status_code == 200
    assert c.get("/api/symonloop/jobs").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    monkeypatch.delenv("SYM_LOOP_HOST", raising=False)
    monkeypatch.delenv("SYM_LOOP_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonloop/jobs").status_code == 200


def test_the_full_cycle_over_http(client):
    r = client.post("/api/symonloop/jobs", headers=auth(), json={
        "work": "check the build", "cadence": "*/5 * * * *",
        "next_fire": iso(T0 + timedelta(minutes=5)), "now": iso(T0), "job_id": "http-job"})
    assert r.status_code == 200 and r.json()["fire_count"] == 0

    d = client.get("/api/symonloop/due", headers=auth(),
                   params={"now": iso(T0 + timedelta(minutes=5))})
    assert d.json()["due_count"] == 1

    f = client.post("/api/symonloop/jobs/http-job/fired", headers=auth(),
                    json={"now": iso(T0 + timedelta(minutes=5)),
                          "next_fire": iso(T0 + timedelta(minutes=10))})
    assert f.status_code == 200 and f.json()["fire_count"] == 1

    s = client.post("/api/symonloop/jobs/http-job/stop", headers=auth(),
                    json={"now": iso(T0), "reason": "done"})
    assert s.json()["state"] == "stopped"


def test_a_ledger_refusal_over_http_is_409_not_500(client):
    r = client.get("/api/symonloop/jobs/no-such-job", headers=auth())
    assert r.status_code == 409 and "no job" in r.json()["detail"]


def test_a_traversal_id_over_http_is_refused(client):
    r = client.get("/api/symonloop/jobs/..%2F..%2Fetc", headers=auth())
    assert r.status_code in (404, 409)
