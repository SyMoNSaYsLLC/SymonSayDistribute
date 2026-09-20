# symonscheduler

When recurring work should next happen, computed rather than waited for.

The first component of the **SyMonComponents** core — the shared, source-owned layer that
vendor-specific adapters sit on top of rather than inside.

## What it does not do

It does not sleep, spawn a thread, hold a queue, or run anybody's work. Deciding **when** is a
different job from deciding **what**, and a scheduler that also executes cannot be asked a
question without causing something to happen.

That separation is what makes the rest possible: `symonloop` will own the work and ask this
component when to do it, and either can be tested without the other.

## No ambient clock, and that is the whole design

Every function takes `now` as an argument. Nothing here calls `datetime.now()`, `time.time()`
or `date.today()` — **a test asserts that**, by reading the module's own source.

Three things follow, and they are the reason:

- **A year of firings is checked in milliseconds.** A leap day is not something you wait until
  February to find out about. `0 0 29 2 *` from March 2026 correctly answers 2028-02-29, and
  that test costs nothing.
- **A schedule is explainable after the fact.** An operator can ask what this would have decided
  at any past moment and get the answer it actually got. A scheduler nobody can replay is a
  scheduler nobody can debug.
- **The same input always gives the same output.** There is no flake to chase.

## The route that matters is `to-cron`

An interval like `5m` looks like it converts cleanly to cron. Usually it does not, and the
failure is silent.

    5m   -> */5 * * * *    exact      every 5 minutes, evenly
    2h   -> 0 */2 * * *    exact      every 2 hours, evenly
    7m   -> */7 * * * *    NOT exact  fires at minutes 0,7,14,21,28,35,42,49,56 then waits 11
    30s  -> */1 * * * *    NOT exact  cron has no sub-minute field; rounded up

`*/7` is **not** every seven minutes. It is nine firings and then an eleven-minute gap across
the hour boundary — a lie told once an hour. So the conversion returns `exact` alongside the
expression and says in words why, and the caller decides whether that matters.

## The other thing people get wrong

When **both** the day-of-month and the day-of-week fields are restricted, POSIX matches a day
satisfying **either**, not both. `0 0 1 * mon` fires on the first of the month *and* on every
Monday. This surprises nearly everyone, so `parse` returns `day_match` and a sentence saying so
rather than leaving it to be discovered in production.

Sunday is accepted as both `0` and `7`, because refusing one of them is a papercut nobody needs.

## Refusals

    "5"        no unit — the unit decides whether this fires 60 times an hour or once a month
    "0m"       a zero interval is not a schedule; it is a loop with no brake
    "* * * *"  four fields; the count is checked FIRST because every other message would mislead
    "60 * * * *"   out of range, named by field and bound
    "5-1 * * * *"  a range that runs backwards
    "0 0 30 2 *"   well-formed and impossible — bounded search, reported as `found: false`

That last one matters: an expression can be valid and still name a date that never occurs. A
scheduler that hunts for it forever is worse than one that says so after four years of looking.

## Routes

    GET /api/symonscheduler/health     public; answers before the unit is configured
    GET /api/symonscheduler/interval   read "5m" and refuse anything ambiguous
    GET /api/symonscheduler/to-cron    express it as cron, and say when that is not exact
    GET /api/symonscheduler/parse      expand the five fields to the values they match
    GET /api/symonscheduler/next       the first moment at or after `now` that matches
    GET /api/symonscheduler/upcoming   the next several firings — what it DOES, not what it says
    GET /api/symonscheduler/describe   the schedule in words

`now` is accepted on every route that needs one and defaults to this host's clock.

Loopback serves open (§3.2a). Bound off-loopback, `SYM_SCHEDULER_TOKEN` is required and an unset
one closes the unit.

One capability carries no route and says so in `NOT_EXPOSED`: `field_values` is the per-field
expansion behind `parse`, returned inside it. Serving it alone would invite a caller to read one
field's values without the expression they came from.

## Placement

    placement-triage prospect symonscheduler --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

### Written from the specification, not adapted from anyone

A survey on 2026-09-19 established what could lawfully be reused:

| Source | Finding |
|---|---|
| Claude Code 2.1.278 | a 224 MB compiled ELF. No JS bundle, no `package.json`, **no LICENSE of its own** — the only licence strings inside belong to vendored libraries. Proprietary; nothing reusable. Decompiling is forbidden by §3.11 and was not attempted. |
| `@qwen-code/qwen-code` 0.19.3 | Apache-2.0, 245 readable TypeScript files |
| `opencode-ai` 1.18.22 | MIT, bundled |
| `openai` SDK 3.3.1 | Apache-2.0, 1521 readable files |
| ChatGPT desktop 26.915.31945 | Electron shell (MIT covers Electron and Chromium); the application itself is proprietary |

The permissive ones may be **read**. They were not copied, because §3.11 forbids pasting another
party's code into the estate outright, whatever its licence: *"state the behaviour in our words
and show our own example."* §3.1b-i governs building **from** an acquired upstream as a separate
pinned artifact — how this estate builds numpy and llama.cpp — and does not license pasting
source into a first-party module.

None of which this component needed. **The five-field cron expression is POSIX and belongs to
nobody**, and an interval in seconds is arithmetic. It is written from the specification.

## Testing

49 tests, all of them cheap because the clock is an argument: intervals with every unit and
seven ambiguous forms refused, the inexactness of `*/7` asserted in words, field expansion
including names and both spellings of Sunday, seven malformed expressions refused by field, the
POSIX or/and day rule, boundary crossings for day, year and leap year, an impossible date
reported rather than searched forever, the same minute never returned twice, and a test that
reads this module's own source to prove nothing in it reads the clock.

    python3 -m pytest tests/ -q

## Releases

Tagged `symonscheduler/v<version>`.

## Status

Built and tested. Wired on 8831. `symonloop` is the next component and depends on this one.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonscheduler`](symonscheduler/symonscheduler.md) | the capability this unit provides — `cadence.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonscheduler`](symonscheduler/symonscheduler.md), [`tests`](tests/tests.md).
