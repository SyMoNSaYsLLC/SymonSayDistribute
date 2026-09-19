# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonscheduler tests.

Every one of these is cheap because `now` is an argument. A year of firings is checked in
milliseconds, and a leap year is not something you wait until February to find out about —
which is the whole reason the clock is passed in rather than read.
"""
import importlib
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from symonscheduler import cadence as C

TOKEN = uuid.uuid4().hex
T0 = datetime(2026, 9, 19, 17, 33)


@pytest.fixture
def client(monkeypatch):
    # Off-loopback, so `headers=auth()` in this file actually exercises the guard. On a
    # loopback bind the guard returns before comparing anything, which would make every
    # authenticated test here pass with a wrong token or none at all.
    monkeypatch.setenv("SYM_SCHEDULER_HOST", "0.0.0.0")
    monkeypatch.setenv("SYM_SCHEDULER_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- intervals: the unit is the part that matters ------------------------------------------
@pytest.mark.parametrize("spec,secs", [("30s", 30), ("5m", 300), ("2h", 7200),
                                       ("1d", 86400), ("1w", 604800)])
def test_an_interval_is_read_with_its_unit(spec, secs):
    assert C.interval_seconds(spec)["seconds"] == secs


@pytest.mark.parametrize("bad", ["5", "", "m", "5x", "-5m", "5 m m", "abc"])
def test_an_ambiguous_interval_is_refused_rather_than_guessed(bad):
    with pytest.raises(C.CadenceError):
        C.interval_seconds(bad)


def test_a_zero_interval_is_refused_because_it_is_not_a_schedule():
    with pytest.raises(C.CadenceError, match="brake"):
        C.interval_seconds("0m")


# --- the honesty that matters most: a cron that is NOT the interval asked for ---------------
def test_an_interval_that_divides_its_unit_is_exact():
    r = C.to_cron("5m")
    assert r["cron"] == "*/5 * * * *" and r["exact"] is True


def test_an_interval_that_does_not_divide_its_unit_says_so():
    """*/7 is NOT every seven minutes. Returning it silently is a lie told once an hour."""
    r = C.to_cron("7m")
    assert r["exact"] is False
    assert "does not divide 60" in r["why"]


def test_a_sub_minute_interval_is_rounded_up_and_says_it_was():
    r = C.to_cron("30s")
    assert r["cron"] == "*/1 * * * *" and r["exact"] is False
    assert "no sub-minute field" in r["why"]


# --- parsing ------------------------------------------------------------------------------
def test_the_field_count_is_checked_first_and_named():
    with pytest.raises(C.CadenceError, match="expected 5 fields"):
        C.parse("* * * *")


@pytest.mark.parametrize("cron,field,expected", [
    ("*/15 * * * *", "minute", [0, 15, 30, 45]),
    ("0 9-17 * * *", "hour", list(range(9, 18))),
    ("0 0 * jan,jul *", "month", [1, 7]),
    ("0 0 * * mon-fri", "day_of_week", [1, 2, 3, 4, 5]),
    ("0 0 * * 7", "day_of_week", [0]),          # Sunday is both 0 and 7 in the wild
])
def test_fields_expand_to_the_values_they_match(cron, field, expected):
    assert C.parse(cron)["fields"][field] == expected


@pytest.mark.parametrize("bad", ["60 * * * *", "* 24 * * *", "* * 0 * *",
                                 "* * * 13 *", "* * * * 8", "5-1 * * * *", "*/0 * * * *"])
def test_an_out_of_range_or_backwards_field_is_refused(bad):
    with pytest.raises(C.CadenceError):
        C.parse(bad)


def test_both_day_fields_restricted_means_OR_and_the_surprise_is_stated():
    """The POSIX rule people get wrong. If it is not stated it will be misread."""
    p = C.parse("0 0 1 * mon")
    assert p["day_match"] == "or"
    assert "EITHER" in p["why_day_match"]
    assert C.parse("0 0 1 * *")["day_match"] == "and"


# --- next fire ----------------------------------------------------------------------------
def test_the_next_fire_is_computed_not_waited_for():
    n = C.next_fire("*/5 * * * *", T0)
    assert n["found"] and n["next"] == "2026-09-19T17:35:00"
    assert n["seconds_away"] == 120


def test_a_fire_at_the_current_minute_is_not_returned_twice():
    """Starting at 17:35 exactly must give 17:40, or a scheduler fires the same tick forever."""
    assert C.next_fire("*/5 * * * *", datetime(2026, 9, 19, 17, 35))["next"] \
        == "2026-09-19T17:40:00"


def test_it_crosses_a_day_boundary():
    assert C.next_fire("0 3 * * *", datetime(2026, 9, 19, 23, 59))["next"] \
        == "2026-09-20T03:00:00"


def test_it_crosses_a_year_boundary():
    assert C.next_fire("0 0 1 1 *", datetime(2026, 12, 31, 23, 59))["next"] \
        == "2027-01-01T00:00:00"


def test_a_leap_day_is_found_without_waiting_for_one():
    n = C.next_fire("0 0 29 2 *", datetime(2026, 3, 1, 0, 0))
    assert n["found"] and n["next"].startswith("2028-02-29")


def test_a_date_that_never_occurs_is_refused_rather_than_searched_forever():
    """30 February is well-formed and impossible. A bounded search says so."""
    n = C.next_fire("0 0 30 2 *", T0)
    assert n["found"] is False and n["next"] is None
    assert "never occurs" in n["why"]


def test_weekday_matching_uses_sunday_as_zero():
    """2026-09-20 is a Sunday. Off-by-one here schedules the wrong day all year."""
    assert C.next_fire("0 0 * * 0", datetime(2026, 9, 19, 12, 0))["next"] \
        == "2026-09-20T00:00:00"


# --- upcoming and describe ------------------------------------------------------------------
def test_upcoming_returns_successive_distinct_firings():
    u = C.upcoming("*/5 * * * *", T0, 4)
    assert u["fires"] == ["2026-09-19T17:35:00", "2026-09-19T17:40:00",
                          "2026-09-19T17:45:00", "2026-09-19T17:50:00"]
    assert u["complete"] is True


def test_upcoming_is_incomplete_rather_than_wrong_when_the_schedule_runs_out():
    u = C.upcoming("0 0 30 2 *", T0, 3)
    assert u["complete"] is False and u["fires"] == []


@pytest.mark.parametrize("count", [0, -1, 500])
def test_an_unreasonable_count_is_refused(count):
    with pytest.raises(C.CadenceError):
        C.upcoming("* * * * *", T0, count)


def test_describe_counts_the_firings_per_day():
    assert C.describe("*/5 * * * *")["fires_per_day"] == 12 * 24
    assert C.describe("0 9 * * *")["fires_per_day"] == 1


# --- no ambient clock: the property the whole design rests on -------------------------------
def test_nothing_in_cadence_reads_the_clock_itself():
    """A function that reads the clock cannot be asked what it would have done yesterday."""
    import inspect
    src = inspect.getsource(C)
    for banned in ("datetime.now(", "datetime.utcnow(", "time.time(", "date.today("):
        assert banned not in src, f"{banned} makes this untestable and unexplainable"


# --- over http --------------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    monkeypatch.setenv("SYM_SCHEDULER_HOST", "0.0.0.0")
    monkeypatch.delenv("SYM_SCHEDULER_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonscheduler/health").status_code == 200
    assert c.get("/api/symonscheduler/parse?cron=*+*+*+*+*").status_code == 503


def test_loopback_needs_no_token(monkeypatch):
    """A token on a loopback bind defends only against a caller who could already read it."""
    monkeypatch.delenv("SYM_SCHEDULER_HOST", raising=False)
    monkeypatch.delenv("SYM_SCHEDULER_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonscheduler/describe?cron=0+9+*+*+*").status_code == 200


def test_now_can_be_supplied_so_a_decision_is_reproducible(client):
    r = client.get("/api/symonscheduler/next",
                   params={"cron": "*/5 * * * *", "now": T0.isoformat()}, headers=auth())
    assert r.status_code == 200 and r.json()["next"] == "2026-09-19T17:35:00"


def test_a_bad_expression_over_http_is_409_not_500(client):
    r = client.get("/api/symonscheduler/parse", params={"cron": "nonsense"}, headers=auth())
    assert r.status_code == 409


def test_a_bad_now_is_refused_by_name(client):
    r = client.get("/api/symonscheduler/next",
                   params={"cron": "* * * * *", "now": "yesterday"}, headers=auth())
    assert r.status_code == 409 and "ISO-8601" in r.json()["detail"]
