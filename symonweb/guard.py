# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What this component refuses to fetch, and why each refusal exists.

THE ONE THAT MATTERS MOST
-------------------------
This is the first component in the estate that reaches off the host, and it is driven by a
model. That combination has a specific failure: a model persuaded to fetch
`http://127.0.0.1:8811/api/board/settings` would be reaching the estate's own services from
outside the fabric — the exact indirection the fabric exists to prevent, handed to whoever
writes the prompt.

So every address is resolved and checked BEFORE the request, and again after every redirect. A
name that resolves into loopback, a private range, link-local or any other non-public address
is refused. That is not a hardening pass to add later; without it this component is a hole in
the estate's own boundary.

WHAT ELSE IT REFUSES
--------------------
Anything that is not http or https. `file://` reads the disk, and a fetcher that can read the
disk is not a fetcher.

A host it has fetched too recently. Politeness is not optional when the request is made on
somebody else's behalf and they never see it.

Anything robots.txt disallows, unless the caller passes --ignore-robots and says why. The flag
exists because there are legitimate reasons; it is recorded so the reason exists somewhere.

A response larger than the cap, stopped mid-stream rather than after it has been read.
"""
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.parse
import urllib.robotparser
from typing import Any

ALLOWED_SCHEMES = {"http", "https"}
MAX_BYTES = 5 << 20          # 5 MiB. A page larger than this is a download, not a page.
USER_AGENT = "SyMoNeuRaL-symonfetch/1.0 (+first-party estate component)"


class Refused(Exception):
    """A fetch refused before it happened, carrying why."""

    def __init__(self, reason: str, url: str = "") -> None:
        super().__init__(reason)
        self.reason, self.url = reason, url


def _addresses(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise Refused(f"{host} does not resolve: {e}", host)
    return sorted({i[4][0] for i in infos})


def check_public(url: str) -> dict[str, Any]:
    """Refuse anything that resolves to an address this host can reach privately.

    Checked on every hop, not only the first: a public URL that redirects to 127.0.0.1 is the
    whole attack, and checking only the first address is the same as not checking.
    """
    p = urllib.parse.urlparse(url)
    if p.scheme not in ALLOWED_SCHEMES:
        raise Refused(f"{p.scheme or '(none)'} is not a scheme this fetches; "
                      f"only {', '.join(sorted(ALLOWED_SCHEMES))}", url)
    if not p.hostname:
        raise Refused("no host in the url", url)

    addrs = _addresses(p.hostname)
    bad = []
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            bad.append(a)
    if bad:
        raise Refused(
            f"{p.hostname} resolves to {', '.join(bad)}, which is not a public address. This "
            f"component reaches the web; reaching this host's own services is what the fabric "
            f"is for, and going around it through a fetch is the hole that would open", url)
    return {"host": p.hostname, "addresses": addrs, "scheme": p.scheme}


class Politeness:
    """One fetch per host per interval. No default interval — it is a decision."""

    def __init__(self, *, min_interval_s: float, clock=time.monotonic) -> None:
        if min_interval_s < 0:
            raise ValueError("a negative interval is not an interval")
        self.min_interval_s = min_interval_s
        self.clock = clock
        self._last: dict[str, float] = {}

    def check(self, host: str) -> None:
        last = self._last.get(host)
        now = self.clock()
        if last is not None and (now - last) < self.min_interval_s:
            wait = round(self.min_interval_s - (now - last), 2)
            raise Refused(f"{host} was fetched {round(now - last, 2)}s ago; this unit waits "
                          f"{self.min_interval_s}s between requests to one host. {wait}s left")
        self._last[host] = now

    def forget(self, host: str) -> None:
        self._last.pop(host, None)


def robots_allows(url: str, agent: str = USER_AGENT, timeout: float = 10.0) -> dict[str, Any]:
    """Whether robots.txt permits this, reported rather than silently obeyed.

    A robots.txt that cannot be fetched is reported as `unknown`, not as permission. "We could
    not ask" and "we asked and it said yes" are different, and only one of them is consent.
    """
    p = urllib.parse.urlparse(url)
    robots = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots)
    try:
        rp.read()
    except Exception as e:
        return {"robots": robots, "allowed": None, "why": f"could not be read: {e}",
                "note": "unknown is not permission"}
    return {"robots": robots, "allowed": bool(rp.can_fetch(agent, url)),
            "crawl_delay": rp.crawl_delay(agent)}
