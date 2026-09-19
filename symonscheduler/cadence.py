# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""When work should next happen, computed rather than waited for.

THE FIRST PIECE OF THE SyMonComponents CORE
-------------------------------------------
Recurring work is a capability several systems provide and none of them own. The five-field
cron expression is POSIX and belongs to nobody; an interval like "5m" is arithmetic. So this
is written from the specification, not adapted from anyone's implementation — which is also
what rules §3.11 requires, and what the licence survey on 2026-09-19 concluded was the only
lawful route for the proprietary sources and the honest one for the permissive sources.

WHY COMPUTING BEATS SLEEPING
A scheduler that sleeps cannot answer "when next?" without waiting, cannot be tested without
real time passing, and loses everything when the process dies. This one is a pure function of
a clock reading handed to it. Nothing here sleeps, nothing here starts a thread, and every
answer is reproducible because the time is an argument rather than an ambient fact.

That decision is what makes the whole thing testable: a year of firings can be checked in
milliseconds, and a leap day is not something you wait until February to find out about.

NO AMBIENT CLOCK
`now` is always passed in. A function that reads the clock itself cannot be asked what it
would have done yesterday, and an estate that cannot replay a schedule cannot explain one.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Any, Iterator

# Every public callable here is reached through a route in service.py; nothing is unrouted.
NOT_EXPOSED: dict[str, str] = {
    "field_values": "the per-field expansion behind parse(); its result is returned inside "
                    "parse() as `fields`, and serving it separately would invite a caller to "
                    "read one field's values without the expression they came from",
}

# Field order is the POSIX one. Written out rather than assumed, because the day-of-week
# position is the one people get wrong and a silent misread schedules the wrong day.
FIELDS = ("minute", "hour", "day_of_month", "month", "day_of_week")
BOUNDS = {"minute": (0, 59), "hour": (0, 23), "day_of_month": (1, 31),
          "month": (1, 12), "day_of_week": (0, 6)}

# Names accepted in the month and weekday fields. Sunday is 0 AND 7 in the wild; both are
# accepted and normalised to 0, because refusing one of them is a papercut nobody needs.
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
DAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}

_INTERVAL = re.compile(r"^\s*(\d+)\s*([smhdw])\s*$", re.I)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class CadenceError(Exception):
    """A schedule that could not be understood, carrying which field failed and why."""


def interval_seconds(spec: str) -> dict[str, Any]:
    """Turn "5m" into seconds, refusing anything ambiguous rather than guessing at it.

    A bare number has no unit and is refused. "0" of anything is refused: a zero interval is
    not a fast schedule, it is a loop with no brake, and the only safe reading of it is that
    whoever wrote it meant something else.
    """
    m = _INTERVAL.match(spec or "")
    if not m:
        raise CadenceError(
            f"{spec!r} is not an interval. Expected a number and one unit from s, m, h, d, w "
            f"— for example 30s, 5m, 2h, 1d. A bare number is refused because the unit is the "
            f"part that decides whether this fires 60 times an hour or once a month")
    n, unit = int(m.group(1)), m.group(2).lower()
    if n == 0:
        raise CadenceError("a zero interval is not a schedule; it is a loop with no brake")
    return {"spec": spec.strip(), "count": n, "unit": unit,
            "seconds": n * _UNIT_SECONDS[unit]}


def to_cron(spec: str) -> dict[str, Any]:
    """Express an interval as a cron expression, and say plainly when it cannot be exact.

    "5m" divides an hour and becomes `*/5 * * * *`. "7m" does not, and a `*/7` in the minute
    field does NOT mean every seven minutes — it means minutes 0,7,14,…,56 and then a 4-minute
    gap across the hour boundary. Returning that silently would be a lie told once an hour, so
    the drift is named and the caller decides.
    """
    iv = interval_seconds(spec)
    n, unit, secs = iv["count"], iv["unit"], iv["seconds"]
    if unit == "s":
        mins = max(1, -(-n // 60))          # ceil: sub-minute cadence is not expressible
        return {**iv, "cron": f"*/{mins} * * * *", "exact": n % 60 == 0,
                "why": (f"cron has no sub-minute field; {n}s was rounded up to {mins} minute(s)"
                        if n % 60 else f"{n}s is exactly {mins} minute(s)")}
    if unit == "m":
        exact = 60 % n == 0
        return {**iv, "cron": f"*/{n} * * * *", "exact": exact,
                "why": ("every %d minutes, evenly" % n if exact else
                        f"*/{n} fires at minutes {', '.join(str(x) for x in range(0, 60, n))} "
                        f"and then waits {60 - (60 // n) * n + n} minutes across the hour "
                        f"boundary — {n} does not divide 60, so this is not a true {n}-minute "
                        f"cadence")}
    if unit == "h":
        exact = 24 % n == 0
        return {**iv, "cron": f"0 */{n} * * *", "exact": exact,
                "why": ("every %d hours, evenly" % n if exact else
                        f"{n} does not divide 24, so the last interval of each day is short")}
    if unit == "d":
        return {**iv, "cron": f"0 0 */{n} * *", "exact": n == 1,
                "why": ("daily" if n == 1 else
                        f"day-of-month stepping restarts each month, so a {n}-day cadence "
                        f"breaks at every month boundary")}
    return {**iv, "cron": "0 0 * * 0", "exact": n == 1,
            "why": "weekly" if n == 1 else
                   f"cron cannot express every {n} weeks; this fires weekly instead"}


def field_values(spec: str, field: str) -> set[int]:
    """Expand one cron field to the set of values it matches.

    Handles `*`, `a-b`, `a-b/s`, `*/s`, names, and comma lists of any of those. A step with no
    range means "from the low bound", which is the behaviour every implementation agrees on.
    """
    lo, hi = BOUNDS[field]
    out: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            raise CadenceError(f"{field}: empty element in {spec!r}")
        step = 1
        if "/" in part:
            part, _, s = part.partition("/")
            if not s.isdigit() or int(s) == 0:
                raise CadenceError(f"{field}: {s!r} is not a usable step")
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part.lstrip("-"):
            x, _, y = part.partition("-")
            a, b = _value(x, field), _value(y, field)
        else:
            a = b = _value(part, field)
            if step != 1:
                b = hi                       # `5/10` means from 5 to the top, by 10
        if a > b:
            raise CadenceError(f"{field}: range {part!r} runs backwards")
        out |= set(range(a, b + 1, step))
    if not out:
        raise CadenceError(f"{field}: {spec!r} matches nothing, so it can never fire")
    return out


def _value(tok: str, field: str) -> int:
    lo, hi = BOUNDS[field]
    t = tok.strip().lower()
    if field == "month" and t in MONTHS:
        return MONTHS[t]
    if field == "day_of_week" and t in DAYS:
        return DAYS[t]
    if not t.lstrip("+").isdigit():
        raise CadenceError(f"{field}: {tok!r} is not a number or a name this field accepts")
    v = int(t)
    if field == "day_of_week" and v == 7:
        return 0                              # Sunday is both 0 and 7 in the wild
    if not lo <= v <= hi:
        raise CadenceError(f"{field}: {v} is outside {lo}-{hi}")
    return v


def parse(cron: str) -> dict[str, Any]:
    """Parse a five-field expression into the values each field matches.

    The field count is checked first and named, because "too few fields" is the single most
    common mistake and every other error message would be misleading once it has happened.
    """
    parts = str(cron).split()
    if len(parts) != 5:
        raise CadenceError(
            f"expected 5 fields (minute hour day-of-month month day-of-week), got {len(parts)} "
            f"in {cron!r}")
    fields = {name: sorted(field_values(p, name)) for name, p in zip(FIELDS, parts)}
    dom_restricted = parts[2] != "*"
    dow_restricted = parts[4] != "*"
    return {"cron": " ".join(parts), "fields": fields,
            "day_match": ("or" if dom_restricted and dow_restricted else "and"),
            "why_day_match":
                ("day-of-month and day-of-week are BOTH restricted, so a day matching EITHER "
                 "fires — this is the POSIX rule and it surprises people, so it is stated"
                 if dom_restricted and dow_restricted else
                 "only one day field is restricted, so the match is unambiguous")}


def _day_matches(p: dict[str, Any], when: datetime) -> bool:
    dom = when.day in p["fields"]["day_of_month"]
    dow = (when.weekday() + 1) % 7 in p["fields"]["day_of_week"]   # Monday=0 -> Sunday=0
    return (dom or dow) if p["day_match"] == "or" else (dom and dow)


def next_fire(cron: str, after: datetime, *, limit_days: int = 1500) -> dict[str, Any]:
    """The first moment at or after `after` that the expression matches.

    Minute resolution, so the search starts at the next whole minute. Bounded: an expression
    like `0 0 30 2 *` matches no date that exists, and a scheduler that hunts for it forever is
    worse than one that says so. The bound is four years, which covers a leap cycle.
    """
    p = parse(cron)
    t = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    stop = after + timedelta(days=limit_days)
    while t <= stop:
        if t.month not in p["fields"]["month"]:
            # jump to the first of the next month rather than stepping a minute at a time
            t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            continue
        if not _day_matches(p, t):
            t = (t + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in p["fields"]["hour"]:
            t = (t + timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute in p["fields"]["minute"]:
            return {"cron": p["cron"], "after": after.isoformat(), "next": t.isoformat(),
                    "seconds_away": int((t - after).total_seconds()), "found": True}
        t += timedelta(minutes=1)
    return {"cron": p["cron"], "after": after.isoformat(), "next": None, "found": False,
            "why": f"no match within {limit_days} days. An expression can be well-formed and "
                   f"still name a date that never occurs — 30 February is the classic one"}


def upcoming(cron: str, after: datetime, count: int = 5) -> dict[str, Any]:
    """The next `count` firings. What a schedule ACTUALLY does, before it is trusted with work.

    A cron expression is read wrongly far more often than it is written wrongly, and the cheap
    defence is to look at what it will do rather than at what it says.
    """
    if count < 1 or count > 200:
        raise CadenceError("count must be between 1 and 200")
    out, cur = [], after
    for _ in range(count):
        n = next_fire(cron, cur)
        if not n["found"]:
            break
        out.append(n["next"])
        cur = datetime.fromisoformat(n["next"])
    return {"cron": cron, "after": after.isoformat(), "count": len(out), "fires": out,
            "complete": len(out) == count}


def describe(cron: str) -> dict[str, Any]:
    """A schedule in words, so a wrong one can be spotted before it is relied on."""
    p = parse(cron)
    f, raw = p["fields"], p["cron"].split()
    def phrase(name: str, singular: str) -> str:
        vals, spec = f[name], raw[FIELDS.index(name)]
        lo, hi = BOUNDS[name]
        if spec == "*":
            return f"every {singular}"
        if len(vals) == 1:
            return f"{singular} {vals[0]}"
        if len(vals) > (hi - lo + 1) // 2:
            return f"{len(vals)} of {hi - lo + 1} {singular}s"
        return f"{singular}s {', '.join(str(v) for v in vals)}"
    return {"cron": p["cron"],
            "minute": phrase("minute", "minute"), "hour": phrase("hour", "hour"),
            "day_of_month": phrase("day_of_month", "day"),
            "month": phrase("month", "month"),
            "day_of_week": phrase("day_of_week", "weekday"),
            "day_match": p["day_match"], "why_day_match": p["why_day_match"],
            "fires_per_day": len(f["minute"]) * len(f["hour"])}
