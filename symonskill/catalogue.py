# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The named procedures this estate knows, made reachable.

THE GAP THIS CLOSES
-------------------
Six skills exist on disk — branch-place, copyleft-trace, disk-identity, estate-verify,
placement-triage, source-pin. Each carries a SKILL.md with a name and a description, and most
carry scripts. **Nothing in the estate could discover any of them.** The `skills` branch has no
service.py; it is a collection, not a component.

That is the same failure the estate has now hit three times — ravencalc released and absent from
the board, symonloop and symonscheduler wired in two places of four. Work that exists and cannot
be reached was not finished, it was abandoned somewhere tidy.

WHAT A SKILL IS HERE
A directory with a SKILL.md whose frontmatter carries at minimum a `name` and a `description`.
The description is what decides whether a skill is relevant to a task, so a skill without one is
not loadable — it can be listed, but nothing can know when to use it.

THIS DOES NOT RUN SKILLS
It catalogues them: finds them, reads their metadata, validates the contract, and hands back the
body on request. Running a skill's script is execution, and execution belongs to whatever holds
the permission to execute — not to a catalogue. The same separation as symonscheduler computing
WHEN without running anything, and symonloop remembering WHAT without executing it.

A catalogue that also executed could not be asked "what is available?" without risk.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Every public callable here is reached through a route in service.py.
NOT_EXPOSED: dict[str, str] = {
    "roots": "resolves SYM_SKILL_ROOTS to a list of paths; the resolved value is reported "
             "inside GET /api/symonskill/skills and inside health, which is the honest "
             "surface — a caller wants the catalogue, not where this process looked",
}

# Frontmatter is a fenced block at the very top. Parsed with a narrow reader rather than a YAML
# dependency: the contract is two required scalar fields, and a parser that accepts anchors,
# aliases and arbitrary nesting would accept far more than the contract allows.
_FENCE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_KEY = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$")

REQUIRED = ("name", "description")
DEFAULT_ROOTS = "/mnt/SymonSayDistribute/skills"


class SkillError(Exception):
    """A catalogue operation that could not be completed, carrying why."""


def roots() -> list[Path]:
    """Where skills are looked for. Configurable so a test never reads the real collection."""
    raw = os.environ.get("SYM_SKILL_ROOTS", DEFAULT_ROOTS)
    return [Path(p) for p in raw.split(os.pathsep) if p.strip()]


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Read the metadata block, and say precisely what is wrong when it cannot be read.

    Returns {"ok": bool, "fields": {...}, "why": str}. Never raises on bad input: a malformed
    skill is a finding to report, not an exception that hides the other five.
    """
    m = _FENCE.match(text or "")
    if not m:
        return {"ok": False, "fields": {},
                "why": "no frontmatter: a skill opens with a --- fenced block carrying at least "
                       "a name and a description"}
    fields: dict[str, Any] = {}
    # Numbered from the FILE, not from the block. Whoever fixes this opens an editor and jumps
    # to a line; a block-relative number sends them to the wrong one, which is a worse error
    # message than none. The opening fence is line 1, so the block starts at line 2.
    for i, line in enumerate(m.group(1).splitlines(), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = _KEY.match(line)
        if not km:
            return {"ok": False, "fields": fields,
                    "why": f"frontmatter line {i} is not `key: value`: {line.strip()[:60]!r}"}
        fields[km.group(1)] = km.group(2).strip().strip('"\'')
    missing = [k for k in REQUIRED if not fields.get(k)]
    if missing:
        return {"ok": False, "fields": fields,
                "why": f"missing {', '.join(missing)}. The description is what decides whether a "
                       f"skill is relevant to a task, so a skill without one can be listed but "
                       f"never chosen"}
    return {"ok": True, "fields": fields, "why": "name and description both present"}


def _read_skill(d: Path) -> dict[str, Any]:
    md = d / "SKILL.md"
    rec: dict[str, Any] = {"skill": d.name, "path": str(d), "has_skill_md": md.is_file()}
    if not md.is_file():
        rec.update({"valid": False, "why": f"no SKILL.md in {d}"})
        return rec
    text = md.read_text(errors="replace")
    fm = parse_frontmatter(text)
    body = text[len(_FENCE.match(text).group(0)):] if _FENCE.match(text) else text
    scripts = sorted(p.name for p in (d / "scripts").glob("*") if p.is_file()) \
        if (d / "scripts").is_dir() else []
    rec.update({
        "valid": fm["ok"],
        "why": fm["why"],
        "name": fm["fields"].get("name"),
        "description": fm["fields"].get("description"),
        "licence": fm["fields"].get("license") or fm["fields"].get("licence"),
        "extra_fields": sorted(k for k in fm["fields"] if k not in ("name", "description",
                                                                   "license", "licence")),
        "scripts": scripts,
        "body_bytes": len(body.encode()),
        "evidence": str(md),
    })
    # The directory name and the declared name disagreeing is a real defect: a caller asking by
    # one will not find it by the other, and nothing else would notice.
    if rec.get("name") and rec["name"] != d.name:
        rec["name_mismatch"] = (f"declares name {rec['name']!r} but the directory is {d.name!r}; "
                                f"a caller asking by either will miss it under the other")
    return rec


def skills() -> dict[str, Any]:
    """Every skill found, with the invalid ones NAMED rather than dropped.

    A catalogue that silently omits a malformed skill reports a tidier estate than the one that
    exists, and the malformed skill is exactly the one somebody needs told about.
    """
    found, roots_seen = [], []
    for r in roots():
        roots_seen.append({"root": str(r), "exists": r.is_dir()})
        if not r.is_dir():
            continue
        for d in sorted(r.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if not (d / "SKILL.md").is_file():
                continue          # not a skill directory; a tree can hold other things
            found.append(_read_skill(d))
    valid = [s for s in found if s["valid"]]
    invalid = [s for s in found if not s["valid"]]
    mismatched = [s for s in found if s.get("name_mismatch")]
    return {"roots": roots_seen, "count": len(found),
            "valid": len(valid), "invalid": len(invalid),
            "skills": found,
            "invalid_names": [s["skill"] for s in invalid],
            "name_mismatches": [s["skill"] for s in mismatched],
            "why": (f"{len(valid)} of {len(found)} skill(s) carry a usable contract" +
                    (f"; {len(invalid)} do not and are listed rather than hidden" if invalid else "") +
                    (f"; {len(mismatched)} declare a name that is not their directory"
                     if mismatched else ""))}


def get(name: str) -> dict[str, Any]:
    """One skill by name, with its body — what a caller loads when it decides to use it.

    Accepts the directory name or the declared name, because those can differ and a caller
    should not have to know which one this catalogue happens to key on.
    """
    if not (name or "").strip():
        raise SkillError("a skill name is required")
    for s in skills()["skills"]:
        if name in (s["skill"], s.get("name")):
            md = Path(s["path"]) / "SKILL.md"
            text = md.read_text(errors="replace")
            m = _FENCE.match(text)
            return {**s, "body": text[len(m.group(0)):] if m else text}
    known = ", ".join(sorted(x["skill"] for x in skills()["skills"])) or "none"
    raise SkillError(f"no skill {name!r}. Known: {known}")


def relevant(task: str, *, limit: int = 5) -> dict[str, Any]:
    """Which skills a task might need, ranked, with the reason each was chosen.

    Scored against the DESCRIPTION, because that is what a description is for — §3.7's sibling
    idea, that a thing states what it is for so a reader knows when to reach for it. The score
    is a word overlap, deliberately simple: a catalogue that guessed cleverly and wrongly would
    be worse than one whose reasoning a person can check.

    `matched` is returned with every hit so the ranking can be disagreed with.
    """
    q = {w for w in re.findall(r"[a-z0-9]+", (task or "").lower()) if len(w) > 3}
    if not q:
        raise SkillError("a task of at least one word longer than three characters is required; "
                         "a one-word query ranks everything equally and helps nobody")
    out = []
    for s in skills()["skills"]:
        if not s["valid"]:
            continue
        hay = f"{s.get('name','')} {s.get('description','')}".lower()
        words = set(re.findall(r"[a-z0-9]+", hay))
        hit = sorted(q & words)
        if hit:
            out.append({"skill": s["skill"], "score": len(hit), "matched": hit,
                        "description": (s.get("description") or "")[:200]})
    out.sort(key=lambda r: (-r["score"], r["skill"]))
    return {"task": task, "considered": len(q), "query_words": sorted(q),
            "matches": out[:limit], "match_count": len(out),
            "why": (f"{len(out)} skill(s) mention a word from the task" if out else
                    "no skill's description mentions any word from this task — that is an "
                    "answer, not a failure, and it is better than ranking six irrelevant "
                    "skills by noise")}


def validate() -> dict[str, Any]:
    """Every contract defect across the collection, as one answer.

    This is the route a gate would call. It reports rather than repairs: a catalogue that
    corrected a skill's frontmatter would be editing somebody's procedure on its own judgement.
    """
    all_ = skills()
    problems = []
    for s in all_["skills"]:
        if not s["valid"]:
            problems.append({"skill": s["skill"], "kind": "contract", "why": s["why"]})
        if s.get("name_mismatch"):
            problems.append({"skill": s["skill"], "kind": "name", "why": s["name_mismatch"]})
        if s["valid"] and not s.get("scripts") and s.get("body_bytes", 0) < 200:
            problems.append({"skill": s["skill"], "kind": "empty",
                             "why": f"valid frontmatter but {s['body_bytes']} bytes of body and "
                                    f"no scripts — nothing to follow"})
    return {"checked": all_["count"], "problems": problems, "ok": not problems,
            "why": ("every skill carries a usable contract" if not problems else
                    f"{len(problems)} defect(s) across {all_['count']} skill(s)")}
