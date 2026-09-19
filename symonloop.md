# symonloop

Recurring work that survives the process that created it.

The second component of the **SyMonComponents** core, and the one that makes the first useful.

## The capability worth owning

Every agent runtime surveyed on 2026-09-19 can schedule recurring work. **Not one of them
remembers it.** The scheduler this estate was measured against says so in its own words — jobs
"live only in this session, nothing is written to disk, and the job is gone when the process
exits." The other runtime's `automations/` directory on this host is empty.

So the thing worth building was never the cadence. `symonscheduler` already owns that, computed
from the POSIX specification. It is the **ledger**. Work that a restart forgets was never
scheduled; it was merely intended.

## Three components, three jobs, none doing another's

    symonscheduler   computes WHEN     cron and intervals, no state, no clock of its own
    symonloop        remembers WHAT    this: durable records, no execution
    an adapter       actually RUNS it  vendor-specific, outside the core

That separation is what lets the core outlive any one runtime. An adapter disappearing takes
nothing with it — the ledger is still on disk and still knows what was owed.

**Two tests hold the boundary from this side.** One reads this module's source and fails if
`subprocess`, `os.system`, `eval`, `exec` or `Popen` appear: a ledger that runs work cannot be
asked a question without causing something to happen. The other fails if cron parsing appears
here, because a second implementation is a second answer, and this estate has already paid once
for the same tool existing at four paths with three different contents.

`next_fire` is therefore **stored, never derived**. The caller computes it in `symonscheduler`
and hands it in.

## Surviving an unclean stop is the whole promise, so the write path is where it is kept

Every write goes to a temporary file in the same directory, then `os.replace` — atomic on
POSIX — after an `fsync`. A process killed mid-write leaves either the old record or the new
one, never half of either. Without the `fsync` the rename can land before the bytes do, which is
the same failure wearing a success.

A test asserts both calls are present. Another asserts no `.tmp-` file is ever left behind: a
leaked temporary is a half-written record waiting to be mistaken for a real one.

Records are plain JSON, one file per job. A ledger only its own program can read is a hostage.

## Expiry is evaluated on read, not by a sweep

A recurring job nobody renews should not outlive attention, so jobs carry an expiry (7 days by
default, `0` for never). That expiry is checked **when `due` is asked**, and persisted at that
moment.

The reason is durability, not convenience: a ledger whose correctness depends on something
having been awake is not durable, it is merely persistent. A job that lapsed while nothing was
running must never be handed out as due afterwards — and it is not, because nothing had to be
watching for the lapse to count.

An expired job cannot be resumed. Expiry means nobody renewed it while it lapsed; quietly
reviving it would resurrect work whose reason to exist was never re-established. Add it again
deliberately instead.

## What it refuses

    work with no content        a timer nobody can act on
    a job with no cadence       cannot say when it is due again
    a reused id                 so that a fire count means what it says
    a non-ISO timestamp         refused by field name
    next_fire <= now            a job due the instant it is recorded is a SPIN, not a schedule
    a fire against a stopped job
    resuming an expired job
    ../../escaped               an id becomes a filename

That last one is a whitelist, not an escape: `^[a-z0-9-]{4,64}$`. A caller who could supply
`../../etc/something` could write outside the ledger, and a blacklist of dangerous characters is
a list somebody always finds a gap in. Nine malformed ids are tested, including a traversal, a
NUL byte and an over-long name.

## An unreadable record is named, never skipped

A ledger that silently drops a corrupt record reports a smaller, cleaner world than the one it
is in — and the record that cannot be read is exactly the one somebody needs to know about. So
`jobs` returns them under `unreadable`, and `due` still answers correctly with a corrupt file
sitting beside the good ones.

## Routes

    GET  /api/symonloop/health              public; answers before any job exists
    GET  /api/symonloop/jobs                every job; unreadable ones named
    GET  /api/symonloop/jobs/{id}           one job, or a refusal naming where it was looked for
    GET  /api/symonloop/due                 what is due at `now`, expiring what lapsed on the way
    POST /api/symonloop/jobs                record recurring work
    POST /api/symonloop/jobs/{id}/fired     record a firing and when it is next owed
    POST /api/symonloop/jobs/{id}/stop      stop without removing — the record is the history
    POST /api/symonloop/jobs/{id}/resume    return a stopped job to service

`now` is a parameter on every route that needs one, defaulting to this host's clock.

Loopback serves open (§3.2a). Bound off-loopback, `SYM_LOOP_TOKEN` is required and an unset one
closes the unit.

Two capabilities carry no route and say so in `NOT_EXPOSED`: `root` resolves `SYM_LOOP_DIR` and
is reported inside `jobs` and `health`; `path_for` is the on-disk filename for one record, and
serving it would invite a caller to read or write a record directly instead of through the
operations that keep it consistent.

## Placement

    placement-triage prospect symonloop --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

Written from the specification and from the observable behaviour of runtimes that document
their own limits. No source was reused: the licence survey of 2026-09-19 found Claude Code to
be a 224 MB proprietary ELF with no LICENSE of its own, and `qwen-code` (Apache-2.0),
`opencode-ai` (MIT) and the `openai` SDK (Apache-2.0) to be readable but uncopyable — §3.11
forbids pasting another party's code into the estate whatever its licence. None was needed: an
atomic file write and a due-date comparison are not anybody's intellectual property.

## Testing

47 tests, every one against a ledger under `tmp_path` — the operator's at
`~/symoneural-run/loop` is never written by a test run. Every one supplies `now`, so a seven-day
expiry is checked in microseconds rather than by waiting a week.

What they cover: a job outliving a module reload, the record being plain JSON, atomicity and
fsync asserted from the source, no leaked temporaries, nine malformed ids, a traversal proving
nothing is written outside the ledger, due-ness before and after the moment, grace bringing a
job forward by exactly what was asked and no more, ordering oldest-first, a stopped job never
being due, expiry happening without anything having been awake and persisting across a reload,
a `next_fire` at or before `now` refused as a spin, fire counts surviving a reload, an expired
job refused rather than revived, a corrupt record named rather than dropped, and the two
boundary tests above.

    python3 -m pytest tests/ -q

## Releases

Tagged `symonloop/v<version>`.

## Status

Built and tested. Wired on 8830. It records and decides; nothing yet fires the work — that is an
adapter, deliberately outside the core.
