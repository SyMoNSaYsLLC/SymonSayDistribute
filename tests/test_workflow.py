# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The release machinery's own tests.

WHY THIS FILE EXISTS
--------------------
On 2026-09-20 two defects were found in this branch. Neither was caught by a test, because
this branch had none — the machinery that gates every release was the only thing in the
estate shipping unexercised.

The first defect is the one these tests guard. stage-and-cut.sh ran the ship gate, THEN wrote
THIRD-PARTY-NOTICES.md, THEN generated the release notes from that first report. But
check_attribution() FAILs every permissive unit when the notices file is absent
(ship-gate.py:405), and the line that writes it had not run yet. So every release published
notes recording a verdict manufactured by a file the release itself ships, beside an uploaded
SHIP-GATE-REPORT.json that said something else.

Measured on the v1.0.0 stage, notices parked and restored:
    without THIRD-PARTY-NOTICES.md   10 FAIL,  0 REVIEW, 0 PASS
    with it                           2 FAIL,  6 REVIEW, 2 PASS

symoneural-learn/v1.6.0 shipped notes reading "Overall FAIL - 1 failing unit(s), 0 needing
review" while its own uploaded report said REVIEW.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
W = HERE.parent

GATE_LINE = re.compile(
    r"Overall \*\*(?P<overall>\w+)\*\* under policy `(?P<policy>[^`]+)` — "
    r"(?P<fail>\d+) failing unit\(s\), (?P<review>\d+) needing review\."
)


def _report(units: dict[str, str], overall: str) -> dict:
    """A gate report carrying exactly the verdicts a test wants to assert against."""
    return {
        "overall": overall,
        "policy": "symoneural-ship-gate/1",
        "units": {
            name: {"components": [], "findings": [], "artifacts": [], "verdict": verdict}
            for name, verdict in units.items()
        },
    }


def _notes(tmp_path: Path, report: dict) -> str:
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    (stage / "SHIP-GATE-REPORT.json").write_text(json.dumps(report))
    out = stage / "RELEASE-NOTES.md"
    r = subprocess.run(
        [sys.executable, str(W / "release-notes.py"),
         "--stage", str(stage), "--tag", "unit/v0.0.0", "--out", str(out)],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"release-notes.py rc={r.returncode}: {r.stderr[-400:]}"
    return out.read_text()


# --- the notes must never disagree with the report they were generated from -------------------

@pytest.mark.parametrize("units,overall,fail,review", [
    ({"a": "PASS"}, "PASS", 0, 0),
    ({"a": "REVIEW", "repo:a": "PASS"}, "REVIEW", 0, 1),
    ({"a": "FAIL", "repo:a": "PASS"}, "FAIL", 1, 0),
    ({"a": "FAIL", "b": "REVIEW", "c": "PASS"}, "FAIL", 1, 1),
    ({}, "PASS", 0, 0),
])
def test_notes_state_exactly_what_the_report_says(tmp_path, units, overall, fail, review):
    text = _notes(tmp_path, _report(units, overall))
    m = GATE_LINE.search(text)
    assert m, "the ship gate line is missing from the notes entirely"
    assert m.group("overall") == overall
    assert int(m.group("fail")) == fail
    assert int(m.group("review")) == review


def test_a_review_is_never_reported_as_a_failure(tmp_path):
    """The exact shape v1.6.0 shipped: one REVIEW unit and one PASS unit.

    The published notes said "1 failing unit(s), 0 needing review". Reading the report the
    right way round says the opposite, and the opposite is the truth.
    """
    text = _notes(tmp_path, _report({"u": "REVIEW", "repo:u": "PASS"}, "REVIEW"))
    m = GATE_LINE.search(text)
    assert (int(m.group("fail")), int(m.group("review"))) == (0, 1)
    assert m.group("overall") != "FAIL"


# --- the ordering that caused it --------------------------------------------------------------

def _order(script: str) -> list[str]:
    """The sequence of machinery calls in a cutter script, in source order."""
    seen = []
    for line in Path(W / script).read_text().splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        for tool in ("ship-gate.py", "third-party-notices.py", "release-notes.py", "SHA256SUMS"):
            if tool in s:
                seen.append(tool)
    return seen


def test_the_gate_reruns_after_the_notices_and_before_the_notes():
    """The regression guard.

    The notes are generated from SHIP-GATE-REPORT.json. If the last gate run before them
    happened while THIRD-PARTY-NOTICES.md did not exist, they record an attribution FAIL that
    the shipped release does not have.
    """
    order = _order("stage-and-cut.sh")
    notices = order.index("third-party-notices.py")
    notes = order.index("release-notes.py")
    gates_between = [i for i, t in enumerate(order)
                     if t == "ship-gate.py" and notices < i < notes]
    assert gates_between, (
        "no ship-gate run sits between third-party-notices.py and release-notes.py; "
        "the notes would be generated from a report taken before the notices existed"
    )


def test_the_checksums_cover_the_final_notes():
    """SHA256SUMS must be written after the notes, or it signs a file that changed."""
    order = _order("stage-and-cut.sh")
    assert order.index("SHA256SUMS") > order.index("release-notes.py")


def test_attribution_is_a_hard_failure_when_the_notices_are_missing():
    """The premise the ordering rests on. If this ever stops being FAIL, the ordering guard
    above is guarding nothing and should be revisited rather than silently kept."""
    src = (W / "ship-gate.py").read_text()
    m = re.search(r'rep\.finding\(unit, "(\w+)", "attribution",\s*"THIRD-PARTY-NOTICES\.md missing',
                  src)
    assert m, "the missing-notices finding is no longer where this test can see it"
    assert m.group(1) == "FAIL"


# --- drive-sweep: five defects, each found by running it, each now asserted -------------------
#
# Every one of these shipped in a version of the script that reported success. They are
# source-level assertions because the failures are all in the SHAPE of the command, not in
# behaviour a unit test can drive without a cloud remote.

SWEEP = (W / "drive-sweep.sh").read_text()


def test_files_from_is_never_combined_with_max_size():
    """rclone: "the usage of --files-from overrides all other filters". Passing both makes it
    refuse to load any filter and fetch NOTHING while still exiting 0. Measured: 0 of 5196."""
    import re as _re
    for line in SWEEP.splitlines():
        s = line.strip()
        if s.startswith("#") or "rclone copy" not in s:
            continue
        # the folder-mode call may use --max-size; the files-from call may not
        block = SWEEP[max(0, SWEEP.find(s) - 2000):SWEEP.find(s)]
        if "--files-from" in s:
            assert "--max-size" not in s, f"--files-from with --max-size fetches nothing: {s}"


def test_a_fetch_of_nothing_is_a_failure_not_a_clean_result():
    """A chunk that fetched zero files once reported "0 findings" and exited 0."""
    assert 'FETCHED NOTHING' in SWEEP
    assert 'no checkpoint written' in SWEEP.lower()


def test_a_short_fetch_withholds_its_checkpoint():
    """rclone exits 0 having silently dropped files. Banking a partial as complete makes
    today's shortfall permanent on every future run."""
    assert 'SHORT by' in SWEEP
    assert 'NO checkpoint' in SWEEP


def test_the_checkpoint_key_names_the_source_list():
    """Keyed on the part alone, two different lists both produce part-0000 and the second run
    skips the first run's checkpoints as though its own work were done."""
    assert 'listkey=' in SWEEP
    assert 'key="chunk-$listkey-' in SWEEP


def test_the_chunk_directory_is_derived_from_the_list_not_shared():
    """A fixed chunk directory cleared on entry deletes the caller's list when the list lives
    inside it — which then reports success having scanned nothing."""
    assert 'parts="$W/sweep/.chunks-$(basename "$FILES_FROM"' in SWEEP
    assert 'rm -rf "$parts"' in SWEEP          # clearing its OWN derived dir is fine


def test_the_scanner_redacts_every_secret_on_a_line_not_just_the_match():
    """A Claude credentials file carries an access token and a refresh token on one line.
    Redacting only the match printed the other in full, to a terminal and a 0664 log."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ss", str(W / "secret-sweep.py"))
    ss = importlib.util.module_from_spec(spec); spec.loader.exec_module(ss)
    a = "sk-" + "ant-oat01-" + "A" * 80
    b = "sk-" + "ant-ort01-" + "B" * 80
    line = '{"accessToken":"%s","refreshToken":"%s"}' % (a, b)
    found = list(ss.scan_text(line, "synthetic"))
    assert len(found) >= 2, found
    for f in found:
        assert a not in f["context"] and b not in f["context"], f["context"]
