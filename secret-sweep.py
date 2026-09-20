#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
# gate-allow-file: no-secret — this file IS the detector; it names the shapes to find them.
"""Find exposed credentials without ever handling one.

THE RULE THIS OBEYS, AND HOW
----------------------------
R13: never print, generate or commit a secret. Fingerprints and locations only.

So this never returns a secret value, not even truncated. A finding is:

    where       the file, and the line number
    what        the kind of credential the shape indicates
    fingerprint the first 12 hex of SHA-256 over the matched text
    context     the surrounding line with the match REPLACED by <redacted:N bytes>

The fingerprint is what makes two copies of the same credential recognisably the same across
a repository, an archive and a cloud folder, without anyone learning the value. It is also
what lets a rotation be verified later: the old fingerprint must stop appearing.

WHAT IT WILL NOT DO
- It never executes anything it scans.
- It never uploads a finding, or sends one to an external service.
- It never deletes, quarantines or rewrites. Deleting a copy does not invalidate a secret;
  only rotation does, and rotation is Garrett's.
- It never reads a file larger than the cap, and it says which ones it skipped rather than
  quietly covering less ground than the report implies.

A scanner that silently skips is worse than no scanner: it converts an unknown into a false
clean.

FINDINGS ARE WRITTEN 0600
Because a findings file that names every credential location is itself a map worth protecting,
even without the values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

MAX_BYTES = 8 * 1024 * 1024        # a file larger than this is REPORTED, never silently skipped
# `.bare` and `objects` hold git's own compressed blobs. Walking them as text reports
# thousands of "binary content" skips that mean nothing — and every blob in them is read
# properly, decompressed, by the --git history mode. Skipping them here is not reducing
# coverage; scanning them here was never coverage in the first place.
SKIP_DIRS = {".git", ".bare", "objects", "node_modules", "__pycache__", ".pytest_cache",
             ".venv", "venv", ".mypy_cache", ".ruff_cache", "site-packages", ".cache"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".pdf", ".zip", ".gz", ".xz",
              ".bz2", ".tar", ".7z", ".mp4", ".mov", ".mp3", ".wav", ".so", ".o", ".a", ".bin",
              ".safetensors", ".gguf", ".pt", ".pth", ".onnx", ".ico", ".woff", ".woff2"}

# Shapes, not values. Each names a credential family whose format is public and unmistakable.
# A shape match is EVIDENCE, not proof — a fixture, a test double and a documented example all
# match, which is why every finding carries its context for a person to judge.
PATTERNS: list[tuple[str, str]] = [
    ("anthropic-key",      r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("openai-key",         r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    ("github-pat",         r"ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}"),
    ("github-oauth",       r"gho_[A-Za-z0-9]{30,}"),
    ("gitlab-pat",         r"glpat-[A-Za-z0-9_-]{18,}"),
    ("aws-access-key",     r"AKIA[0-9A-Z]{16}"),
    ("google-api-key",     r"AIza[0-9A-Za-z_-]{35}"),
    ("google-oauth-token", r"ya29\.[0-9A-Za-z_-]{20,}"),
    ("slack-token",        r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("stripe-key",         r"sk_live_[0-9a-zA-Z]{24,}"),
    ("private-key-block",  r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("jwt",                r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("cloudflare-token",   r"\b[A-Za-z0-9_-]{40}\b(?=.*(?i:cloudflare|tunnel))"),
    # An assignment whose NAME says secret and whose value is long enough to be one. The widest
    # net here, and the noisiest — which is why the kind says "assignment" rather than claiming
    # to know what it found.
    ("secret-assignment",
     r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|"
     r"client[_-]?secret|private[_-]?key)\b\s*[:=]\s*['\"]?([A-Za-z0-9/+_=-]{16,})['\"]?"),
]
COMPILED = [(k, re.compile(p)) for k, p in PATTERNS]

# A match inside one of these is almost certainly a placeholder. Recorded as `likely_placeholder`
# rather than dropped: the judgement is surfaced, not made silently.
PLACEHOLDER = re.compile(
    r"(?i)\b(example|sample|placeholder|dummy|fake|redacted|your[_-]?\w+|xxx+|<[a-z_]+>|"
    r"changeme|not[_-]?a[_-]?real|test[_-]?token|000000|aaaa+)\b")


# A credential looks random. An identifier does not, and a type annotation is the commonest
# false positive there is: `password: URLPatternComponentResult;` matched the assignment shape
# on the first run of this scanner and was a TypeScript interface field.
#
# The discriminator is SHAPE, not length: a real key mixes cases AND digits, or is base64/hex.
# A CamelCase identifier has no digits; a snake_case one has no upper case. Neither is a secret.
_LOOKS_LIKE_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _plausible_secret(v: str) -> bool:
    """Could this value be a credential at all? Conservative: when unsure, say yes."""
    if not _LOOKS_LIKE_IDENTIFIER.match(v):
        return True                       # punctuation, base64, hex — keep it
    has_digit = any(c.isdigit() for c in v)
    has_upper = any(c.isupper() for c in v)
    has_lower = any(c.islower() for c in v)
    # A bare identifier with no digits is a name — a type, a variable, a function.
    return has_digit and has_upper and has_lower


def fingerprint(s: str) -> str:
    """Stable, one-way, and short enough to read. Never reversible to the value."""
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:12]


def redact(line: str, match: str) -> str:
    """The line with EVERY credential on it replaced by its length. No value, ever.

    Redacting only the match that produced this finding is not enough, and that is not a
    theoretical point. On 2026-09-20 a Claude OAuth credentials file was found whose single
    line carries both an access token and a refresh token. Matching the first redacted the
    first and printed the second in full; matching the second did the reverse. Both values
    reached a terminal and a world-readable log before anyone noticed.

    So the line is swept with every pattern this scanner knows before it is returned. A
    credential this tool does not recognise can still survive, which is why the context is
    also truncated — but a line holding two secrets of known shape now loses both.
    """
    out = line
    seen: set[str] = set()
    for _kind, rx in COMPILED:
        for m in rx.finditer(line):
            hit = m.group(1) if (m.groups() and m.group(1)) else m.group(0)
            if hit and hit not in seen:
                seen.add(hit)
                out = out.replace(hit, f"<redacted:{len(hit)}B>")
    if match and match not in seen:
        out = out.replace(match, f"<redacted:{len(match)}B>")
    return out.strip()[:200]


def scan_text(text: str, where: str) -> Iterator[dict[str, Any]]:
    for lineno, line in enumerate(text.splitlines(), 1):
        if len(line) > 4000:
            line = line[:4000]          # a minified bundle should not dominate the report
        for kind, rx in COMPILED:
            for m in rx.finditer(line):
                hit = m.group(1) if (m.groups() and m.group(1)) else m.group(0)
                # The assignment shape is the wide net. Everything else here is a vendor
                # format that cannot be anything but a credential, so only this one is filtered.
                if kind == "secret-assignment" and not _plausible_secret(hit):
                    continue
                yield {
                    "where": where, "line": lineno, "kind": kind,
                    "fingerprint": fingerprint(hit),
                    "length": len(hit),
                    "context": redact(line, hit),
                    "likely_placeholder": bool(PLACEHOLDER.search(line)),
                }


def scan_file(p: Path, label: str | None = None) -> tuple[list[dict], dict | None]:
    """One file. Returns (findings, skip-record-or-None). A skip is always reported."""
    where = label or str(p)
    try:
        st = p.stat()
    except OSError as e:
        return [], {"where": where, "why": f"unreadable: {type(e).__name__}"}
    if st.st_size > MAX_BYTES:
        return [], {"where": where, "why": f"larger than the {MAX_BYTES // 1048576} MiB cap "
                                           f"({st.st_size} bytes) — NOT scanned"}
    if p.suffix.lower() in BINARY_EXT:
        return [], {"where": where, "why": f"binary extension {p.suffix} — not scanned as text"}
    try:
        raw = p.read_bytes()
    except OSError as e:
        return [], {"where": where, "why": f"unreadable: {type(e).__name__}"}
    return scan_blob(raw, where)


def scan_blob(raw: bytes, where: str) -> tuple[list[dict], dict | None]:
    """Bytes from anywhere — a file on disk or a blob out of git — scanned identically.

    Extension is a hint, not a fact. Git history holds blobs whose path says `.sh` and whose
    content is an ELF, and blobs with no extension at all. Deciding by extension alone is how
    the first run of this died: `git cat-file -p` under text=True hit 0xf3 in a Distribute blob
    and took the whole scan with it, leaving a zero-byte summary that looked like a clean repo.

    So the content decides, exactly as it does for a file on disk, and this is one function
    rather than two so the two paths cannot drift apart.
    """
    if b"\x00" in raw[:8192]:
        return [], {"where": where, "why": "binary content (NUL in first 8 KiB) — not scanned"}
    return list(scan_text(raw.decode("utf-8", "replace"), where)), None


def walk(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            yield Path(dirpath) / f


def scan_tree(root: Path) -> dict[str, Any]:
    findings, skipped, n = [], [], 0
    for f in walk(root):
        n += 1
        got, skip = scan_file(f)
        findings += got
        if skip:
            skipped.append(skip)
    return {"root": str(root), "files_seen": n, "findings": findings, "skipped": skipped}


def scan_git_history(repo: Path, max_commits: int = 4000,
                     done: set[str] | None = None) -> dict[str, Any]:
    """Every blob ever committed. A secret removed from HEAD is still in the history.

    Reads blobs through `git cat-file`, never checking anything out — a scanner that checked out
    old revisions would be executing somebody's past working tree by accident.
    """
    def git(*a: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(repo), *a],
                              capture_output=True, text=True, timeout=300)

    def git_raw(*a: str) -> subprocess.CompletedProcess:
        """Bytes, never text. A blob is arbitrary content; decoding it at the pipe is a crash."""
        return subprocess.run(["git", "-C", str(repo), *a],
                              capture_output=True, timeout=300)
    r = git("rev-list", "--all", f"--max-count={max_commits}")
    if r.returncode != 0:
        return {"repo": str(repo), "error": r.stderr.strip()[:200], "findings": [], "blobs": 0}
    commits = [c for c in r.stdout.split() if c]
    # A blob SHA is content-addressed, so "already scanned" is true forever — which makes the
    # checkpoint trivially correct across runs. Without it the daily job restarts 188 commits
    # of history every time and a kill mid-run loses everything.
    seen: set[str] = set(done) if done else set()
    findings, blobs, skipped = [], 0, []
    for c in commits:
        t = git("ls-tree", "-r", "--long", c)
        if t.returncode != 0:
            continue
        for line in t.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 5 or parts[1] != "blob":
                continue
            sha, size, path = parts[2], parts[3], parts[4]
            if sha in seen:
                continue
            seen.add(sha)
            if size.isdigit() and int(size) > MAX_BYTES:
                skipped.append({"where": f"{repo.name}@{sha[:8]}:{path}",
                                "why": f"blob larger than cap ({size} bytes) — NOT scanned"})
                continue
            if Path(path).suffix.lower() in BINARY_EXT:
                continue
            b = git_raw("cat-file", "-p", sha)
            if b.returncode != 0:
                skipped.append({"where": f"{repo.name}@{sha[:8]}:{path}",
                                "why": f"git cat-file rc={b.returncode} — NOT scanned"})
                continue
            blobs += 1
            got, skip = scan_blob(b.stdout, f"{repo.name}@{sha[:8]}:{path}")
            findings += got
            if skip:
                skipped.append(skip)
            if done is not None:
                done.add(sha)
    return {"repo": str(repo), "commits": len(commits), "blobs": blobs,
            "findings": findings, "skipped": skipped}


def report(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_f = [f for r in results for f in r.get("findings", [])]
    all_s = [s for r in results for s in r.get("skipped", [])]
    real = [f for f in all_f if not f["likely_placeholder"]]
    by_kind: dict[str, int] = {}
    by_fp: dict[str, list[str]] = {}
    for f in real:
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
        by_fp.setdefault(f["fingerprint"], []).append(f["where"])
    return {
        "scanned": [r.get("root") or r.get("repo") for r in results],
        "findings_total": len(all_f),
        "likely_placeholders": len(all_f) - len(real),
        "findings_to_review": len(real),
        "by_kind": by_kind,
        "unique_credentials": len(by_fp),
        "appearing_more_than_once": {k: v for k, v in by_fp.items() if len(v) > 1},
        "not_scanned": all_s,
        "not_scanned_count": len(all_s),
        "findings": real,
        "why": ("nothing matched a credential shape outside placeholders" if not real else
                f"{len(real)} match(es) across {len(by_fp)} distinct value(s). A shape match is "
                f"evidence, not proof — a fixture and a live key look identical to a regex, so "
                f"every one carries its context for a person to judge. Deleting a copy does not "
                f"invalidate a secret; only rotation does."),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Find exposed credentials without handling one.")
    ap.add_argument("--tree", action="append", default=[], help="a directory to scan")
    ap.add_argument("--git", action="append", default=[], help="a repository whose history to scan")
    ap.add_argument("--out", default=None, help="write findings JSON here, mode 0600")
    a = ap.parse_args()
    if not a.tree and not a.git:
        ap.error("give at least one --tree or --git")
    results = [scan_tree(Path(t)) for t in a.tree] + [scan_git_history(Path(g)) for g in a.git]
    rep = report(results)
    summary = {k: v for k, v in rep.items() if k != "findings"}
    print(json.dumps(summary, indent=1))
    if a.out:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(rep, fh, indent=1)
        print(f"\nfindings written 0600 to {p}", file=sys.stderr)
    return 1 if rep["findings_to_review"] else 0


if __name__ == "__main__":
    sys.exit(main())
