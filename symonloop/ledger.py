# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Recurring work that survives the process that created it.

THE CAPABILITY, AND WHY IT IS THE ONE WORTH OWNING
--------------------------------------------------
Every agent runtime surveyed on 2026-09-19 can schedule recurring work. Not one of them
REMEMBERS it. The scheduler this estate was measured against says so in its own words — jobs
"live only in this session, nothing is written to disk, and the job is gone when the process
exits." The other runtime's automations directory on this host is empty.

So the thing worth building is not the cadence — `symonscheduler` already owns that, computed
from the POSIX specification — it is the LEDGER. Work that is forgotten by a restart was never
scheduled; it was merely intended.

WHAT THIS DOES NOT DO
---------------------
It does not execute. It does not sleep, poll, or hold a thread. It records what should happen,
answers which of it is due at a moment you name, and records that a firing occurred.

Three components, three jobs, and none of them does another's:

    symonscheduler   computes WHEN         (cron and intervals, no state)
    symonloop        remembers WHAT        (this: durable records, no execution)
    an adapter       actually RUNS it      (vendor-specific, outside the core)

That separation is what lets the core outlive any one runtime. An adapter that disappears takes
nothing with it: the ledger is still on disk and still knows what was owed.

IT DOES NOT PARSE CRON, DELIBERATELY
`next_fire` is stored, never derived here. Computing it is `symonscheduler`'s job and a second
implementation would be a second answer — the divergent-copy failure this estate has already
paid for once. The caller computes it there and hands it in.

CRASH DURING A WRITE MUST NOT COST THE LEDGER
Every write is to a temporary file in the same directory, then `os.replace`, which is atomic on
POSIX. A process killed mid-write leaves either the old record or the new one, never half of
either. The whole point of this component is surviving an unclean stop, so the write path is
where that promise is kept or broken.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Every public callable is reached through a route in service.py.
NOT_EXPOSED: dict[str, str] = {
    "root": "resolves SYM_LOOP_DIR to a path; its value is reported inside GET "
            "/api/symonloop/jobs and inside health, which is the honest surface — a caller "
            "wants the ledger, not where this process looked for it",
    "path_for": "the on-disk filename for one job id; an implementation detail of the store, "
                "and serving it would invite a caller to read or write a record directly "
                "instead of through the operations that keep it consistent",
}

STATES = ("active", "stopped", "expired")
DEFAULT_EXPIRY_DAYS = 7          # a recurring job nobody renews should not outlive attention
_ID = re.compile(r"^[a-z0-9-]{4,64}$")


class LedgerError(Exception):
    """A ledger operation that could not be completed, carrying why."""


def root() -> Path:
    """Where the ledger lives. Configurable, because a test must never touch the real one."""
    p = Path(os.environ.get("SYM_LOOP_DIR", os.path.expanduser("~/symoneural-run/loop")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def path_for(job_id: str) -> Path:
    """The file backing one job, with the id validated before it reaches the filesystem.

    An id is used as a filename, so it is checked against a whitelist rather than escaped. A
    caller that could supply `../../etc/something` could write outside the ledger, and a
    blacklist of dangerous characters is a list somebody always finds a gap in.
    """
    if not _ID.match(job_id or ""):
        raise LedgerError(
            f"{job_id!r} is not a usable job id. Lowercase letters, digits and hyphens, 4 to 64 "
            f"characters — an id becomes a filename, so it is checked against what is allowed "
            f"rather than filtered for what is not")
    return root() / f"{job_id}.json"


def _write(p: Path, rec: dict[str, Any]) -> None:
    """Atomic: write beside the target, then replace. A crash leaves one whole record."""
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(rec, fh, indent=1, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(*, work: str, cadence: str, next_fire: str, now: str,
        job_id: str | None = None, expires_days: int = DEFAULT_EXPIRY_DAYS,
        note: str = "") -> dict[str, Any]:
    """Record work to be done repeatedly. Returns the stored record.

    `next_fire` is computed by symonscheduler and handed in — this component does not parse
    cadence, so a second cron implementation cannot drift from the first.

    `work` is opaque here. It is a string this component stores and never interprets, let alone
    runs. Deciding what it means is the adapter's job, and keeping that out of the core is what
    lets the same ledger serve more than one runtime.
    """
    if not (work or "").strip():
        raise LedgerError("a job with no work is a timer nobody can act on")
    if not (cadence or "").strip():
        raise LedgerError("a job with no cadence cannot say when it is due again")
    _iso(next_fire, "next_fire")
    created = _iso(now, "now")
    jid = job_id or uuid.uuid4().hex[:12]
    p = path_for(jid)
    if p.exists():
        raise LedgerError(f"job {jid!r} already exists; ids are not reused so that a fire "
                          f"count means what it says")
    if expires_days < 0:
        raise LedgerError("expires_days cannot be negative")
    rec = {
        "id": jid, "work": work, "cadence": cadence, "note": note,
        "state": "active", "created": created.isoformat(),
        "next_fire": next_fire, "last_fire": None, "fire_count": 0,
        "expires": (created + timedelta(days=expires_days)).isoformat() if expires_days else None,
        "expires_days": expires_days or None,
    }
    _write(p, rec)
    return rec


def get(job_id: str) -> dict[str, Any]:
    """One job, or a refusal naming the id and where it was looked for."""
    p = path_for(job_id)
    if not p.is_file():
        raise LedgerError(f"no job {job_id!r} in {root()}")
    try:
        return json.loads(p.read_text())
    except Exception as e:
        raise LedgerError(f"job {job_id!r} is on disk but unreadable: {type(e).__name__}: {e}")


def jobs(*, state: str | None = None) -> dict[str, Any]:
    """Every job, with the unreadable ones NAMED rather than skipped.

    A ledger that silently drops a corrupt record reports a smaller, cleaner world than the one
    it is in. A job that cannot be read is exactly the job somebody needs to know about.
    """
    if state is not None and state not in STATES:
        raise LedgerError(f"{state!r} is not a state; one of {', '.join(STATES)}")
    out, broken = [], []
    for f in sorted(root().glob("*.json")):
        try:
            rec = json.loads(f.read_text())
        except Exception as e:
            broken.append({"file": f.name, "why": f"{type(e).__name__}: {e}"})
            continue
        if state is None or rec.get("state") == state:
            out.append(rec)
    return {"root": str(root()), "count": len(out), "jobs": out,
            "unreadable": broken,
            "why": ("every record read cleanly" if not broken else
                    f"{len(broken)} record(s) on disk could not be read and are listed rather "
                    f"than skipped")}


def due(now: str, *, grace_s: int = 0) -> dict[str, Any]:
    """Which active jobs are due at `now`, and which have expired on the way.

    Expiry is evaluated HERE rather than by a sweep, so a job that lapsed while nothing was
    running is never handed out as due. A ledger whose correctness depends on something having
    been awake is not durable, it is merely persistent.
    """
    t = _iso(now, "now")
    ready, expired, waiting = [], [], []
    for rec in jobs()["jobs"]:
        if rec.get("state") != "active":
            continue
        exp = rec.get("expires")
        if exp and _iso(exp, "expires") <= t:
            rec["state"] = "expired"
            rec["expired_at"] = t.isoformat()
            _write(path_for(rec["id"]), rec)
            expired.append(rec)
            continue
        nf = _iso(rec["next_fire"], "next_fire")
        (ready if nf <= t + timedelta(seconds=grace_s) else waiting).append(rec)
    return {"now": t.isoformat(), "grace_s": grace_s,
            "due": sorted(ready, key=lambda r: r["next_fire"]),
            "due_count": len(ready), "waiting": len(waiting),
            "expired_now": expired,
            "why": (f"{len(ready)} job(s) due" if ready else "nothing is due") +
                   (f"; {len(expired)} expired on the way and will not be handed out again"
                    if expired else "")}


def record_fire(job_id: str, *, now: str, next_fire: str) -> dict[str, Any]:
    """Record that a job fired, and when it is next owed.

    The new `next_fire` is supplied rather than computed, for the same reason `add` takes one.
    It must be LATER than the firing: a job whose next fire is at or before now would be handed
    out again immediately and spin.
    """
    rec = get(job_id)
    if rec["state"] != "active":
        raise LedgerError(f"job {job_id!r} is {rec['state']}, not active; a fire cannot be "
                          f"recorded against work that is no longer owed")
    t = _iso(now, "now")
    nf = _iso(next_fire, "next_fire")
    if nf <= t:
        raise LedgerError(
            f"next_fire {next_fire} is not after {now}. A job scheduled into the past or the "
            f"present is due the instant it is recorded, which is a spin, not a schedule")
    rec["last_fire"] = t.isoformat()
    rec["next_fire"] = nf.isoformat()
    rec["fire_count"] = int(rec.get("fire_count", 0)) + 1
    _write(path_for(job_id), rec)
    return rec


def stop(job_id: str, *, now: str, reason: str = "") -> dict[str, Any]:
    """Stop a job without removing it. The record is the history of what ran here."""
    rec = get(job_id)
    rec["state"] = "stopped"
    rec["stopped_at"] = _iso(now, "now").isoformat()
    rec["stopped_reason"] = reason
    _write(path_for(job_id), rec)
    return rec


def resume(job_id: str, *, now: str, next_fire: str) -> dict[str, Any]:
    """Return a stopped job to active service with a fresh next fire.

    An expired job is refused: expiry means nobody renewed it while it lapsed, and quietly
    reviving it would resurrect work whose reason to exist was never re-established.
    """
    rec = get(job_id)
    if rec["state"] == "active":
        raise LedgerError(f"job {job_id!r} is already active")
    if rec["state"] == "expired":
        raise LedgerError(
            f"job {job_id!r} expired at {rec.get('expired_at')}. Expiry means it lapsed with "
            f"nobody renewing it; add it again deliberately rather than reviving it quietly")
    t = _iso(now, "now")
    nf = _iso(next_fire, "next_fire")
    if nf <= t:
        raise LedgerError(f"next_fire {next_fire} is not after {now}")
    rec["state"] = "active"
    rec["next_fire"] = nf.isoformat()
    rec["resumed_at"] = t.isoformat()
    _write(path_for(job_id), rec)
    return rec


def _iso(value: str, field: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise LedgerError(f"{field}: {value!r} is not an ISO-8601 datetime")
