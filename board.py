#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""control board — one visible file that holds every serving decision, and shows what is true.

    symon-board show      print the board with [live] refreshed from the machine
    symon-board env       emit shell exports, for a unit launch to consume
    symon-board measure   re-derive the values marked STALE, when the card is free
    symon-board diff      only the lines where configured and live disagree
    symon-board init      write a board from the checkpoint and the machine

WHY A FILE AND NOT A DOTFILE
----------------------------
The settings lived in `~/.config/symoneural/learn.env`: hidden, 49 lines, and inert unless
somebody remembered `set -a; . file; set +a` first. Nothing showed whether a value was
measured, derived, guessed, or stale, and nothing showed whether the thing running bore any
relation to it. A setting you cannot see and cannot check is not a control.

This file is the board. Every value carries where it came from. A `[live]` section, rewritten
on every `show`, carries what is actually running beside it — so configured-versus-actual is
visible without asking, and a value that has drifted says so on its own line.

WHAT IT WILL NOT DO
-------------------
It never invents a number. A value it cannot derive is written `STALE` with the reason, and
`env` refuses to emit a board that still carries one unless `--allow-stale` is passed. The
previous configuration carried a gpu fraction resting on an unmeasured assumption with nothing
in the file to say so.

`[live]` is read-only. Edits there are discarded on the next `show`, because it is a report of
the machine and not a request to it.
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys
from pathlib import Path

DEFAULT_BOARD = os.environ.get("SYM_BOARD") or "/models/control.board"

# Every public callable here is either routed by service.py or listed below with the reason it
# is not. The endpoints-current gate enforces that: silence is the failure, because a
# capability nobody routed and nobody decided against is indistinguishable from one forgotten.
NOT_EXPOSED = {
    "sh": "runs a command and returns its output; exposing it would be a shell over HTTP",
    "card": "a probe, reported through /live rather than on its own",
    "listener": "a probe, reported through /live",
    "flag": "parses one flag out of a command line; a helper, not a capability",
    "fingerprint": "hashes a credential file. Routed indirectly through /client, which reports "
                   "the fingerprint. A route taking an arbitrary path would let a caller "
                   "fingerprint any file on the host, which is a different thing entirely",
    "live": "routed as GET /api/board/live",
    "client_surfaces": "routed as GET /api/board/client",
    "client_3p": "superseded by client_surfaces, which reports both surfaces rather than one",
    "cmd_show": "a command-line entry point, not a capability",
    "cmd_diff": "a command-line entry point; the capability is routed as GET /api/board/diff",
    "cmd_env": "a command-line entry point. Deliberately NOT routed: it emits shell exports, "
               "and a control surface that hands out an environment over the network is a "
               "different trust decision from one that reports settings",
    "cmd_3p": "a command-line entry point; superseded by cmd_client",
    "cmd_client": "a command-line entry point; routed as POST /api/board/client/{surface}",
    "cmd_sections": "a command-line entry point; routed as GET /api/board/sections",
    "cmd_check": "a command-line entry point; routed as GET /api/board/check",
    "main": "the command-line dispatcher",
}
LIVE = "live"

# key -> the environment variable a unit reads. A key with no mapping is board-only.
ENV_OF = {
    ("model", "store"): "SYM_MODELS_DIR",
    ("model", "model"): "SYM_CHAT_MODEL_DIR",
    ("model", "registry"): "SYM_LLM_REGISTRY_ROOT",
    ("serving", "context"): "SYM_MAX_MODEL_LEN",
    ("serving", "sequences"): "SYM_MAX_SEQS",
    ("serving", "gpu_fraction"): "SYM_GPU_FRACTION",
    ("serving", "offload_gb"): "SYM_CPU_OFFLOAD_GB",
    ("serving", "served_name"): "SYM_CHAT_SERVED_NAME",
    ("ports", "chat"): "SYM_CHAT_PORT",
    ("ports", "gateway"): "SYM_GW_PORT",
    ("paths", "run_dir"): "SYM_RUN_DIR",
    # The third-party client path. `enabled` is a switch the board owns, not a variable a
    # unit reads, so it has no mapping — `3p` acts on it.
    ("client_3p", "gateway_url"): "SYM_3P_GATEWAY_URL",
    ("client_3p", "credential_helper"): "SYM_3P_CREDENTIAL_HELPER",
    # The credential is named by PATH and never by value. Section 3.2 permits fingerprints and
    # file locations only, and both surfaces already want a path rather than a secret: the web
    # console reads SYM_GW_KEY_FILE server-side, and the client invokes a helper that prints
    # the token. Putting a key on a board would be the one thing neither of them asked for.
    ("client", "credential"): "SYM_GW_KEY_FILE",
    ("client", "gateway_url"): "SYM_GW_URL",
}

# The client loads a config-library entry only when its id is a 36-character UUID. An entry
# named anything else is carried, applied, and silently inert — which cost this estate a day.
UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")

_SECTION = re.compile(r"^\s*\[([A-Za-z_][A-Za-z0-9_]*)\]\s*$")
# A section may declare which tree owns it, so the board answers "what licence governs this
# setting" without anyone having to know the layout:  #@tree: Distribute
_TREE = re.compile(r"^\s*#@tree:\s*(.+?)\s*$")
_ENTRY = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\s*#\s*(.*))?$")


class Board:
    """The file, parsed so it can be rewritten without losing a comment or a blank line."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()

    @classmethod
    def load(cls, path: str | Path) -> "Board":
        p = Path(path)
        if not p.is_file():
            raise SystemExit(f"no board at {p} — run: symon-board init")
        return cls(p.read_text())

    def walk(self):
        """(index, section, key, value, note) for every entry line."""
        section = ""
        for i, line in enumerate(self.lines):
            m = _SECTION.match(line)
            if m:
                section = m.group(1)
                continue
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            e = _ENTRY.match(line)
            if e:
                yield i, section, e.group(2), e.group(4).strip(), (e.group(6) or "").strip()

    def get(self, section: str, key: str) -> tuple[str, str] | None:
        for _, s, k, v, note in self.walk():
            if s == section and k == key:
                return v, note
        return None

    def trees(self) -> dict[str, str]:
        """section -> the tree that owns it, from the #@tree: line above its header."""
        out, pending = {}, ""
        for line in self.lines:
            m = _TREE.match(line)
            if m:
                pending = m.group(1); continue
            s = _SECTION.match(line)
            if s:
                out[s.group(1)] = pending or "(unattributed)"
                pending = ""
        return out

    def sections(self) -> list[str]:
        seen = []
        for line in self.lines:
            m = _SECTION.match(line)
            if m and m.group(1) not in seen:
                seen.append(m.group(1))
        return seen

    def values(self, section: str) -> dict[str, str]:
        return {k: v for _, s, k, v, _ in self.walk() if s == section}

    def stale(self) -> list[tuple[str, str, str]]:
        return [(s, k, note) for _, s, k, _, note in self.walk() if "STALE" in note.upper()]

    def set_note(self, section: str, key: str, note: str) -> None:
        for i, s, k, v, _ in list(self.walk()):
            if s == section and k == key:
                e = _ENTRY.match(self.lines[i])
                pad = " " * max(1, 28 - len(e.group(1) + k + e.group(3) + v))
                self.lines[i] = f"{e.group(1)}{k}{e.group(3)}{v}{pad}# {note}"

    def replace_section(self, name: str, body: list[str]) -> None:
        """Rewrite one section's body, leaving everything else byte-identical."""
        start = end = None
        for i, line in enumerate(self.lines):
            m = _SECTION.match(line)
            if m and m.group(1) == name:
                start = i
            elif m and start is not None:
                end = i
                break
        if start is None:
            self.lines += ["", f"[{name}]"] + body
            return
        if end is None:
            end = len(self.lines)
        self.lines[start + 1:end] = body + [""]

    def text(self) -> str:
        return "\n".join(self.lines).rstrip("\n") + "\n"


# ------------------------------------------------------------------ the machine
def sh(*a) -> str:
    try:
        r = subprocess.run(a, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def fingerprint(path: str) -> tuple[str, str]:
    """Which credential is live, without anyone seeing it.

    Returns (fingerprint, note). The value is hashed and discarded in the same expression; it
    is never returned, never written to the board, and never printed. An operator confirming
    that two surfaces hold the SAME key compares two fingerprints, which is the whole reason
    section 3.2 permits them.
    """
    import hashlib
    p = Path(os.path.expanduser(path))
    if not p.is_file():
        return ("", f"no credential at {p}")
    try:
        raw = p.read_bytes().strip()
    except Exception as e:
        return ("", f"{p} is not readable: {e}")
    if not raw:
        return ("", f"{p} is empty")
    mode = oct(p.stat().st_mode & 0o777)[2:]
    note = f"{p}  mode {mode}  {len(raw)} bytes"
    if mode != "600":
        note += "  — MODE SHOULD BE 600"
    return (hashlib.sha256(raw).hexdigest()[:16], note)


def card() -> dict:
    out = sh("nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits")
    if not out:
        return {}
    t, u, f = (int(x.strip()) for x in out.split(",")[:3])
    return {"total_mib": t, "used_mib": u, "free_mib": f}


def listener(port: str) -> dict:
    """Who holds a port, and the command line they were started with."""
    out = sh("bash", "-lc", f"ss -lntp 2>/dev/null | grep ':{port} '")
    if not out:
        return {"up": False}
    m = re.search(r"pid=(\d+)", out)
    pid = m.group(1) if m else ""
    cmd = ""
    if pid:
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace").replace("\0", " ").strip()
        except Exception:
            cmd = ""
    return {"up": True, "pid": pid, "cmd": cmd}


def flag(cmd: str, name: str) -> str:
    m = re.search(re.escape(name) + r"[= ]([^\s]+)", cmd)
    return m.group(1) if m else ""


def client_3p(board: Board) -> list[tuple[str, str, str]]:
    """Is the third-party client path actually wired, or only configured?

    Four things have to hold at once and each has failed here separately:
      - the profile directory exists (the client writes its state there)
      - a config-library entry is applied AND its id is a valid UUID, or the client loads
        nothing while reporting the entry as applied
      - the gateway answers
      - a credential is reachable without being read, printed, or placed in a system file
    """
    rows = []
    vals = board.values("client_3p")
    if vals.get("enabled", "no").lower() not in ("yes", "true", "on", "1"):
        rows.append(("path", "off", "the board has it switched off"))
        return rows

    prof = Path(vals.get("profile", ""))
    rows.append(("profile", "present" if prof.is_dir() else "MISSING",
                 str(prof) if prof.is_dir() else f"{prof} does not exist"))

    meta = prof / "configLibrary" / "_meta.json"
    if meta.is_file():
        try:
            applied = json.loads(meta.read_text()).get("appliedId", "")
        except Exception:
            applied = ""
        if not applied:
            rows.append(("entry", "NONE", "no entry is applied"))
        elif not UUID_RE.match(applied):
            rows.append(("entry", "INERT", f"{applied} is not a UUID — the client will not load it"))
        else:
            has = (prof / "configLibrary" / f"{applied}.json").is_file()
            rows.append(("entry", "ok" if has else "MISSING FILE",
                         applied if has else f"{applied} applied but its file is absent"))
    else:
        rows.append(("entry", "NONE", "no config library in the profile"))

    url = vals.get("gateway_url", "")
    if url:
        code = sh("bash", "-lc",
                  f"curl -s -o /dev/null -w '%{{http_code}}' -m 5 {url}/health")
        rows.append(("gateway", code or "unreachable",
                     "200 is correct — /health is the one public route" if code == "200"
                     else f"{url} did not answer 200"))

    helper = vals.get("credential_helper", "")
    if helper:
        h = Path(helper)
        rows.append(("credential", "executable" if os.access(h, os.X_OK) else "NOT EXECUTABLE",
                     f"{h} — emits the token on stdout; never read or printed here"))
    return rows


SURFACES = ("3p", "webui", "both", "off")


def client_surfaces(board: Board) -> list[tuple[str, str, str]]:
    """Which surface is selected, and is it actually wired to reach Symon.

    Both surfaces take the credential the same correct way and neither stores it: the web
    console reads the key file server-side, the client invokes a helper that prints the token.
    The board selects WHICH gets wired and names WHERE the key is. It carries no key.
    """
    vals = board.values("client")
    surface = (vals.get("surface") or "off").lower()
    keypath = vals.get("credential", "")
    rows: list[tuple[str, str, str]] = []

    if surface not in SURFACES:
        return [("surface", "INVALID", f"{surface!r} is not one of {', '.join(SURFACES)}")]
    rows.append(("surface", surface, "toggle: symon-board client 3p|webui|both|off"))

    fp, note = fingerprint(keypath) if keypath else ("", "no credential named on the board")
    rows.append(("credential", fp or "MISSING", note))

    want3p = surface in ("3p", "both")
    wantweb = surface in ("webui", "both")

    if want3p:
        prof = Path(os.path.expanduser(vals.get("profile", "")))
        meta = prof / "configLibrary" / "_meta.json"
        applied = ""
        if meta.is_file():
            try:
                applied = json.loads(meta.read_text()).get("appliedId", "")
            except Exception:
                applied = ""
        entry = prof / "configLibrary" / f"{applied}.json"
        if not applied:
            rows.append(("3p_entry", "NONE", "no entry applied"))
        elif not UUID_RE.match(applied):
            rows.append(("3p_entry", "INERT", f"{applied} is not a UUID — the client will not load it"))
        elif not entry.is_file():
            rows.append(("3p_entry", "MISSING", f"{applied} applied but its file is absent"))
        else:
            # Does the entry take its credential from a helper, or does it hold one?
            try:
                cfg = json.loads(entry.read_text())
            except Exception as e:
                cfg = {}
                rows.append(("3p_entry", "UNREADABLE", str(e)[:60]))
            kind = cfg.get("inferenceCredentialKind", "")
            helper = cfg.get("inferenceCredentialHelper", "")
            rows.append(("3p_entry", "ok", applied))
            if kind == "helper-script" and helper:
                h = os.path.expanduser(helper)
                if not os.access(h, os.X_OK):
                    rows.append(("3p_credential", "HELPER NOT EXECUTABLE", h))
                else:
                    # THE ACTUAL QUESTION. Not "is a helper configured" but "does what it
                    # emits match the key the board names". A helper can be present,
                    # executable, and handing the client a different or stale credential;
                    # every check short of this one passes while inference fails on a 401.
                    #
                    # Both sides are hashed and compared. Neither value is returned, stored,
                    # printed or logged — the comparison is the whole output.
                    import hashlib, subprocess
                    try:
                        out = subprocess.run([h], capture_output=True, timeout=15)
                        emitted = out.stdout.strip()
                    except Exception as e:
                        emitted = b""
                        rows.append(("3p_credential", "HELPER FAILED", str(e)[:60]))
                    if emitted:
                        # a helper may emit a bare token or {"token": ...}
                        tok = emitted
                        if emitted.lstrip().startswith(b"{"):
                            try:
                                tok = json.loads(emitted).get("token", "").encode()
                            except Exception:
                                tok = emitted
                        efp = hashlib.sha256(tok.strip()).hexdigest()[:16]
                        if efp == fp and fp:
                            rows.append(("3p_credential", "linked",
                                         f"{h} emits the key the board names ({efp})"))
                        else:
                            rows.append(("3p_credential", "MISMATCH",
                                         f"{h} emits {efp}; the board names {fp or '(none)'} "
                                         "— the client is being handed a different credential"))
                    elif not any(r[0] == "3p_credential" for r in rows):
                        rows.append(("3p_credential", "HELPER EMITTED NOTHING", h))
            elif kind == "static":
                # A static kind means the key is IN the client's config file on disk.
                rows.append(("3p_credential", "STATIC — KEY ON DISK",
                             "inferenceCredentialKind is 'static', so the value sits in the "
                             "entry. Switch to helper-script; the board will not carry a key "
                             "and neither should that file."))
            else:
                rows.append(("3p_credential", "UNSET", f"kind={kind or '(none)'}"))

    if wantweb:
        url = vals.get("webui_url", "")
        code = sh("bash", "-lc", f"curl -s -o /dev/null -w '%{{http_code}}' -m 5 {url}") if url else ""
        rows.append(("webui", code or "unreachable",
                     f"{url} — reads the key file server-side via SYM_GW_KEY_FILE, never in a browser"))
    return rows


def live(board: Board) -> list[str]:
    """What is actually true, right now. Rewritten on every show."""
    chat_port = (board.get("ports", "chat") or ("8802", ""))[0]
    gw_port = (board.get("ports", "gateway") or ("9001", ""))[0]
    c = card()
    chat = listener(chat_port)
    gw = listener(gw_port)
    cmd = chat.get("cmd", "")

    def row(k, v, note):
        pad = " " * max(1, 28 - len(f"{k} = {v}"))
        return f"{k} = {v}{pad}# {note}"

    out = [row("chat_unit", "up" if chat["up"] else "DOWN",
               f"pid {chat.get('pid','-')}, port {chat_port}"),
           row("gateway", "up" if gw["up"] else "DOWN",
               f"pid {gw.get('pid','-')}, port {gw_port}")]
    if cmd:
        served = flag(cmd, "--max-num-seqs")
        frac = flag(cmd, "--gpu-memory-utilization")
        ctx = flag(cmd, "--max-model-len")
        off = flag(cmd, "--cpu-offload-gb") or "0"
        path = next((w for w in cmd.split() if w.startswith("/") and "model" in w.lower()), "")
        for k, v, want_sec, want_key in (("model", path, "model", "model"),
                                         ("context", ctx, "serving", "context"),
                                         ("sequences", served, "serving", "sequences"),
                                         ("gpu_fraction", frac, "serving", "gpu_fraction"),
                                         ("offload_gb", off, "serving", "offload_gb")):
            if not v:
                continue
            want = board.get(want_sec, want_key)
            note = "matches the board"
            if want and want[0] != v:
                note = f"DIFFERS — board says {want[0]}"
            out.append(row(k, v, note))
    for k, v, note in client_surfaces(board):
        out.append(row(f"client_{k}", v, note))
    if c:
        out.append(row("card_total_mib", c["total_mib"], "measured now"))
        out.append(row("card_free_mib", c["free_mib"],
                       "with the chat unit running — not an idle figure"
                       if chat["up"] else "IDLE — good for `measure`"))
    return out


# ------------------------------------------------------------------ commands
def cmd_show(a) -> int:
    b = Board.load(a.board)
    b.replace_section(LIVE, live(b))
    Path(a.board).write_text(b.text())
    if a.section:
        want = a.section
        if want not in b.sections():
            print(f"no section [{want}]. There are: {', '.join(b.sections())}", file=sys.stderr)
            return 2
        cur, out = "", []
        for line in b.lines:
            m = _SECTION.match(line)
            if m:
                cur = m.group(1)
            if cur == want:
                out.append(line)
        sys.stdout.write("\n".join(out) + "\n")
    else:
        sys.stdout.write(b.text())
    st = b.stale()
    if st:
        print(f"\n{len(st)} value(s) marked STALE:", file=sys.stderr)
        for s, k, note in st:
            print(f"  [{s}] {k} — {note}", file=sys.stderr)
    return 0


def cmd_diff(a) -> int:
    b = Board.load(a.board)
    b.replace_section(LIVE, live(b))
    Path(a.board).write_text(b.text())
    rows = [(k, v, note) for _, s, k, v, note in b.walk()
            if s == LIVE and "DIFFERS" in note]
    if not rows:
        print("configured and live agree on every value the board controls")
        return 0
    print(f"{len(rows)} value(s) differ between the board and what is running:")
    for k, v, note in rows:
        print(f"  {k:<16} live {v:<12} {note}")
    print("\nnothing changes until the unit is restarted: symon-board env | ...")
    return 1


def cmd_env(a) -> int:
    b = Board.load(a.board)
    st = b.stale()
    if st and not a.allow_stale:
        print("refusing: the board carries values that were never measured", file=sys.stderr)
        for s, k, note in st:
            print(f"  [{s}] {k} — {note}", file=sys.stderr)
        print("\nrun `symon-board measure` with the card free, or pass --allow-stale",
              file=sys.stderr)
        return 3
    for _, s, k, v, _ in b.walk():
        if s == LIVE:
            continue
        env = ENV_OF.get((s, k))
        if env:
            print(f"export {env}={v}")
    return 0


def cmd_3p(a) -> int:
    """Superseded by `client`. Kept so the old command does not silently vanish.

    This read a `[client_3p]` section that no longer exists. `board.values("client_3p")` came
    back empty, `enabled` defaulted to "no", and it printed "the board has it switched off"
    about a path that was switched ON and fully wired — while `client` reported the same path
    as ok on all five checks, from the `[client]` section that actually governs.

    A command that reports the opposite of the truth is worse than one that was deleted, and
    this is the readiness check somebody runs immediately before testing. It now defers.
    """
    if getattr(a, "state", None) in ("on", "off"):
        print("`3p on|off` is superseded. The surface is one setting now, and it has four\n"
              "values rather than two:\n"
              "    symon-board client 3p|webui|both|off\n"
              "Nothing was changed.")
        return 2
    print("`3p` is superseded by `client`, which reads the [client] section that governs.\n")
    # cmd_client selects a surface when given one; this must only REPORT, so the attribute it
    # switches on is set to nothing rather than left absent, which raised AttributeError.
    a.surface = None
    return cmd_client(a)


def _cmd_3p_legacy(a) -> int:
    """The original, kept for reference. Not reachable from the CLI."""
    b = Board.load(a.board)
    if a.state in ("on", "off"):
        want = "yes" if a.state == "on" else "no"
        for i, s, k, v, note in list(b.walk()):
            if s == "client_3p" and k == "enabled":
                e = _ENTRY.match(b.lines[i])
                pad = " " * max(1, 28 - len(f"{k} = {want}"))
                b.lines[i] = f"{e.group(1)}{k}{e.group(3)}{want}{pad}# {note}"
        Path(a.board).write_text(b.text())
        print(f"third-party client path: {a.state}")
        b = Board.load(a.board)
    rows = client_3p(b)
    print()
    bad = 0
    for k, v, note in rows:
        broken = v.isupper() and v not in ("ok",)
        bad += broken
        print(f"  {'FAIL' if broken else 'ok  '}  {k:<12} {v:<16} {note}")
    if bad:
        print(f"\n{bad} part(s) of the path are not wired")
        return 1
    return 0


def cmd_sections(a) -> int:
    b = Board.load(a.board)
    trees = b.trees()
    counts = {}
    for _, s, _, _, _ in b.walk():
        counts[s] = counts.get(s, 0) + 1
    print(f"{len(b.sections())} sections, {sum(counts.values())} settings")
    print()
    for s in b.sections():
        print(f"  {s:<18} {counts.get(s,0):>3} setting(s)   {trees.get(s,'')}")
    return 0


def cmd_check(a) -> int:
    """Every path on the board must exist; every port must be a port; nothing may be STALE."""
    b = Board.load(a.board)
    bad = 0
    for _, s, k, v, note in b.walk():
        if s == LIVE:
            continue
        if "STALE" in note.upper():
            print(f"  STALE     [{s}] {k} — {note}"); bad += 1
        elif v.startswith("/") and "credential" not in k and not Path(v).exists():
            print(f"  MISSING   [{s}] {k} = {v}"); bad += 1
        elif k in ("chat", "gateway", "port") or k.endswith("_port"):
            if not (v.isdigit() and 1 <= int(v) <= 65535):
                print(f"  NOT A PORT [{s}] {k} = {v}"); bad += 1
    if bad:
        print(f"\n{bad} problem(s) on the board")
        return 1
    print("every path on the board exists, every port is a port, nothing is stale")
    return 0


def cmd_client(a) -> int:
    """Select which surface receives the credential, and report whether it is wired."""
    b = Board.load(a.board)
    if a.surface in SURFACES:
        found = False
        for i, s, k, v, note in list(b.walk()):
            if s == "client" and k == "surface":
                e = _ENTRY.match(b.lines[i])
                pad = " " * max(1, 28 - len(f"{k} = {a.surface}"))
                b.lines[i] = f"{e.group(1)}{k}{e.group(3)}{a.surface}{pad}# {note}"
                found = True
        if not found:
            print("no [client] surface line on the board", file=sys.stderr)
            return 2
        Path(a.board).write_text(b.text())
        print(f"credential surface: {a.surface}")
        b = Board.load(a.board)
    bad = 0
    print()
    for k, v, note in client_surfaces(b):
        broken = v.isupper() and v not in ("ok",) and v != "OFF"
        bad += broken
        print(f"  {'FAIL' if broken else 'ok  '}  {k:<16} {v:<22} {note}")
    if bad:
        print(f"\n{bad} part(s) not wired")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="symon-board")
    ap.add_argument("--board", default=DEFAULT_BOARD)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show"); p.add_argument("section", nargs="?"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("diff"); p.set_defaults(fn=cmd_diff)
    p = sub.add_parser("sections"); p.set_defaults(fn=cmd_sections)
    p = sub.add_parser("check"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("env"); p.add_argument("--allow-stale", action="store_true"); p.set_defaults(fn=cmd_env)
    p = sub.add_parser("client"); p.add_argument("surface", nargs="?",
                                                 choices=list(SURFACES) + ["status"], default="status")
    p.set_defaults(fn=cmd_client)
    p = sub.add_parser("3p"); p.add_argument("state", nargs="?", choices=["on", "off", "status"],
                                             default="status"); p.set_defaults(fn=cmd_3p)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
