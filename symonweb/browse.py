# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Driving a browser — any browser that speaks W3C WebDriver.

WHY THE PROTOCOL AND NOT A BROWSER
----------------------------------
The browser on this host today is Thorium, a Chromium fork, reached through `chromedriver`.
Binding to that would make this unit useless the day it changes, and it would be binding to an
accident of this machine rather than to anything real.

W3C WebDriver is a published standard. chromedriver, geckodriver, msedgedriver and safaridriver
all implement it, so this drives whichever is present and does not care which. The only
browser-specific thing in the whole module is the capability key used to ask for headless mode,
and that is a small table with an entry per family and a documented fallback.

It is also why there is no selenium here. WebDriver is JSON over HTTP; a client for it is the
standard library plus the protocol, and a dependency for that would be carried in every release
for no capability we do not already have.

THE SAME GUARD AS FETCHING, FOR THE SAME REASON
-----------------------------------------------
A browser told to open `http://127.0.0.1:8811/api/board/settings` reaches the estate's own
services from outside the fabric, exactly as a fetch would — with the added problem that it will
execute whatever JavaScript it finds there. Every navigation goes through the same public-address
check, and it is applied to the resolved URL after the page settles as well, because a page can
navigate itself.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .guard import Refused, check_public

# Every driver here speaks the same protocol. The family decides one thing only: how to ask for
# headless. A driver not in this table is still usable — it simply gets no headless argument,
# which is honest rather than a guess that silently opens a window on somebody's desktop.
FAMILIES = {
    "chromedriver":  {"browser": "chrome",  "caps_key": "goog:chromeOptions",
                      "headless": ["--headless=new", "--no-sandbox", "--disable-gpu",
                                   "--disable-dev-shm-usage"]},
    "geckodriver":   {"browser": "firefox", "caps_key": "moz:firefoxOptions",
                      "headless": ["-headless"]},
    "msedgedriver":  {"browser": "MicrosoftEdge", "caps_key": "ms:edgeOptions",
                      "headless": ["--headless=new", "--no-sandbox"]},
    "safaridriver":  {"browser": "safari",  "caps_key": None, "headless": []},
}

SEARCH = ["/usr/bin", "/usr/local/bin", "/opt/chromium.org/thorium", "/opt/google/chrome",
          "/snap/bin", "/usr/lib/chromium", "/usr/lib/chromium-browser"]


def drivers() -> list[dict[str, Any]]:
    """Every W3C driver on this host, with the family it belongs to.

    Version is NOT collected by running the binary. `thorium-shell --version` launches a
    browser and waits — it printed a DevTools websocket and hung for two minutes. A probe that
    can start a browser to answer a question about itself is not a probe.

    CORRECTED 2026-09-20: that reason is true of the BROWSER and false of the DRIVER.
    `/opt/chromium.org/thorium/chromedriver --version` returned
    `ChromeDriver 138.0.7204.303 (536d2fef…)` immediately, rc=0, launching nothing. So the
    version here is readable and the reason it is not read is no longer the one written above.

    The real reason is §3.1b-iii and it is a GAP, not a decision: none of the 108 pins in
    SymonSaySource records a browser driver, a Chromium or a Thorium, so there is nothing to
    compare a version TO. Reading one and asserting it against nothing would be theatre.
    Recorded in symonweb.md under "The version gap"; closed by a pin, after which this returns
    a version and a test fails on drift the way board and symonprobe now do.
    """
    out = []
    seen: set[str] = set()
    for name, fam in FAMILIES.items():
        paths = []
        w = shutil.which(name)
        if w:
            paths.append(w)
        for d in SEARCH:
            p = Path(d) / name
            if p.is_file() and os.access(p, os.X_OK):
                paths.append(str(p))
        for p in paths:
            rp = str(Path(p).resolve())
            if rp in seen:
                continue
            seen.add(rp)
            out.append({"driver": name, "path": p, "browser": fam["browser"],
                        "headless_supported": bool(fam["headless"])})
    return out


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class BrowserError(Exception):
    """A browsing operation that could not be completed, carrying why."""


class Session:
    """One browser session. Always closed, including when something raises.

    A leaked session is a browser process holding memory and a profile directory until the host
    reboots, and the way they leak is an exception between start and quit. So this is a context
    manager and the driver process is killed by pid, not by name.
    """

    def __init__(self, driver: str | None = None, *, headless: bool = True,
                 timeout: float = 30.0, page_load_s: float = 30.0) -> None:
        found = drivers()
        if not found:
            raise BrowserError(
                "no W3C WebDriver on this host. This unit drives any of chromedriver, "
                "geckodriver, msedgedriver or safaridriver; install one and it works unchanged")
        chosen = next((d for d in found if d["driver"] == driver), None) if driver else found[0]
        if chosen is None:
            raise BrowserError(f"{driver!r} is not present. Available: "
                               f"{', '.join(sorted({d['driver'] for d in found}))}")
        self.info = chosen
        self.fam = FAMILIES[chosen["driver"]]
        self.headless = headless
        self.timeout = timeout
        self.page_load_s = page_load_s
        self.port = _free_port()
        self.proc: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.base = f"http://127.0.0.1:{self.port}"

    # --- protocol ---------------------------------------------------------------------
    def _rq(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"content-type": "application/json",
                                              "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read())
                msg = err.get("value", {}).get("message", "")[:300]
            except Exception:
                msg = e.reason
            raise BrowserError(f"{method} {path} -> {e.code}: {msg}")
        except urllib.error.URLError as e:
            raise BrowserError(f"the driver at {self.base} is not answering: {e.reason}")

    def __enter__(self) -> "Session":
        self.proc = subprocess.Popen(
            [self.info["path"], f"--port={self.port}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                self._rq("GET", "/status", timeout=2)
                break
            except BrowserError:
                if self.proc.poll() is not None:
                    raise BrowserError(f"{self.info['driver']} exited rc={self.proc.returncode} "
                                       f"before it listened on {self.port}")
                time.sleep(0.2)
        else:
            self._kill()
            raise BrowserError(f"{self.info['driver']} did not listen on {self.port} in 20s")

        caps: dict[str, Any] = {"browserName": self.info["browser"],
                                "pageLoadStrategy": "normal"}
        key = self.fam["caps_key"]
        if key and self.headless and self.fam["headless"]:
            caps[key] = {"args": list(self.fam["headless"])}
        try:
            r = self._rq("POST", "/session", {"capabilities": {"alwaysMatch": caps}}, timeout=60)
        except BrowserError:
            self._kill()
            raise
        self.session_id = (r.get("value") or {}).get("sessionId") or r.get("sessionId")
        if not self.session_id:
            self._kill()
            raise BrowserError(f"{self.info['driver']} returned no sessionId")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.session_id:
                self._rq("DELETE", f"/session/{self.session_id}", timeout=10)
        except Exception:
            pass
        self._kill()

    def _kill(self) -> None:
        """Stop the driver by PID, with SIGCONT before SIGTERM so a stopped process gets it."""
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGCONT)
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.proc.wait(timeout=8)
        except Exception:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except Exception:
                pass

    # --- what a caller actually does ----------------------------------------------------
    def go(self, url: str) -> dict[str, Any]:
        """Navigate, with the address checked before AND after — a page can navigate itself."""
        before = check_public(url)
        self._rq("POST", f"/session/{self.session_id}/timeouts",
                 {"pageLoad": int(self.page_load_s * 1000)})
        self._rq("POST", f"/session/{self.session_id}/url", {"url": url},
                 timeout=self.page_load_s + 10)
        landed = self._rq("GET", f"/session/{self.session_id}/url").get("value") or url
        if landed != url:
            check_public(landed)
        return {"requested": url, "landed": landed, "addresses": before["addresses"]}

    def read(self) -> dict[str, Any]:
        """Title, url, visible text and links, taken from the live DOM after scripts have run.

        This is the whole reason a browser is worth its cost over a fetch: the text here is what
        a reader sees, not what the server sent.
        """
        script = (
            "const t=document.title, u=location.href;"
            "const b=document.body?document.body.innerText:'';"
            "const l=[...document.querySelectorAll('a[href]')].slice(0,500)"
            ".map(a=>({text:(a.innerText||'').trim().slice(0,200),url:a.href}))"
            ".filter(x=>x.url.startsWith('http'));"
            "return {title:t,url:u,text:b,links:l};")
        r = self._rq("POST", f"/session/{self.session_id}/execute/sync",
                     {"script": script, "args": []}, timeout=self.page_load_s + 10)
        v = r.get("value") or {}
        seen, links = set(), []
        for l in v.get("links", []):
            if l["url"] not in seen:
                seen.add(l["url"]); links.append(l)
        text = (v.get("text") or "").strip()
        return {"title": v.get("title", ""), "url": v.get("url", ""), "text": text,
                "links": links,
                "counts": {"characters": len(text), "links": len(links)},
                "rendered": True,
                "rendered_means": "read from the live DOM after scripts ran, not from the "
                                  "bytes the server sent"}


def visit(url: str, *, driver: str | None = None, headless: bool = True,
          page_load_s: float = 30.0) -> dict[str, Any]:
    """Open one page in a real browser and read it. The session is always closed."""
    with Session(driver=driver, headless=headless, page_load_s=page_load_s) as s:
        nav = s.go(url)
        out = s.read()
        out["navigation"] = nav
        out["driver"] = {"driver": s.info["driver"], "browser": s.info["browser"],
                         "headless": headless}
        return out
