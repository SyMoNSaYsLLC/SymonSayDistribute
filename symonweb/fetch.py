# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Fetching a page, and turning it into something a model can read.

REDIRECTS ARE FOLLOWED BY HAND, ON PURPOSE
------------------------------------------
urllib follows redirects itself, which would check the first address and then go wherever it is
sent. A public URL redirecting to 127.0.0.1 is the entire attack this component has to survive,
so automatic redirects are turned off and each hop is checked before it is taken. The chain is
returned, so what actually happened is visible rather than collapsed into a final URL.

STANDARD LIBRARY ONLY
---------------------
bs4, lxml and httpx are installed on this host and all three are permissive, so using them
would not have changed the placement. They would have changed the CENSUS — three dependencies
carried in every release of this unit, for text and links out of HTML, which html.parser does.
A dependency that earns its place is worth carrying; three that do not are three more things to
audit at every release.
"""
from __future__ import annotations

import gzip
import html
import io
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
from html.parser import HTMLParser
from typing import Any

from .guard import MAX_BYTES, USER_AGENT, Refused, check_public, robots_allows

MAX_HOPS = 5
DROP = {"script", "style", "noscript", "template", "svg", "head"}


class _Reader(HTMLParser):
    """Text, links, title and meta description, in one pass.

    Deliberately not a DOM. What a model needs from a page is what it says and where it points,
    and building a tree to get those is work that can also go wrong on malformed markup — which
    is most markup.
    """

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.title = ""
        self.description = ""
        self._skip = 0
        self._in_title = False
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in DROP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or "").lower() == "description":
            self.description = (a.get("content") or "")[:500]
        elif tag == "a" and a.get("href"):
            self._href, self._anchor = a["href"], []
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in DROP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href is not None:
            text = " ".join("".join(self._anchor).split())[:200]
            try:
                url = urllib.parse.urljoin(self.base, self._href)
            except Exception:
                url = self._href
            if urllib.parse.urlparse(url).scheme in ("http", "https"):
                self.links.append({"text": text, "url": url})
            self._href, self._anchor = None, []

    def handle_data(self, data):
        # Title first: <title> lives inside <head>, and <head> is dropped, so checking _skip
        # before this silently produced an empty title on every page. Found by fetching
        # example.com and getting no title back from a page that plainly has one.
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._href is not None:
            self._anchor.append(data)
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*", "\n\n", raw)
        return raw.strip()


def _decode_body(raw: bytes, encoding: str | None) -> bytes:
    if encoding == "gzip":
        try:
            return gzip.decompress(raw)
        except Exception:
            return raw
    if encoding == "deflate":
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw
    return raw


def fetch(url: str, *, timeout: float = 20.0, max_bytes: int = MAX_BYTES,
          ignore_robots: bool = False, robots_reason: str = "") -> dict[str, Any]:
    """Fetch one page. Every hop checked, size capped, nothing sent that identifies anyone."""
    if ignore_robots and not robots_reason.strip():
        raise Refused("ignoring robots.txt needs a recorded reason; the flag exists because "
                      "there are legitimate ones, and the reason is the whole point of it", url)

    rob = robots_allows(url)
    if rob.get("allowed") is False and not ignore_robots:
        raise Refused(f"robots.txt at {rob['robots']} disallows this for {USER_AGENT}. Pass "
                      f"ignore_robots with a reason if there is one", url)

    chain: list[dict[str, Any]] = []
    current = url
    for hop in range(MAX_HOPS + 1):
        where = check_public(current)          # every hop, not just the first
        req = urllib.request.Request(current, headers={
            "user-agent": USER_AGENT,
            "accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
            "accept-encoding": "gzip, deflate",
        })
        # No cookies, no auth, no referer: nothing that identifies this host or carries a
        # credential ever leaves it. There is no parameter to add one.
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            r = opener.open(req, timeout=timeout)
            status, headers, body = r.status, dict(r.headers), r.read(max_bytes + 1)
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, dict(e.headers), e.read(max_bytes + 1)
        except urllib.error.URLError as e:
            raise Refused(f"{current} did not answer: {e.reason}", current)

        chain.append({"url": current, "status": status, "addresses": where["addresses"]})

        if status in (301, 302, 303, 307, 308) and headers.get("Location"):
            if hop >= MAX_HOPS:
                raise Refused(f"more than {MAX_HOPS} redirects", url)
            current = urllib.parse.urljoin(current, headers["Location"])
            continue
        break

    truncated = len(body) > max_bytes
    body = body[:max_bytes]
    body = _decode_body(body, (headers.get("Content-Encoding") or "").lower() or None)
    ctype = (headers.get("Content-Type") or "").lower()
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        charset = m.group(1)
    text_body = body.decode(charset, errors="replace")

    out: dict[str, Any] = {
        "url": url, "final_url": chain[-1]["url"], "status": chain[-1]["status"],
        "hops": chain, "content_type": ctype.split(";")[0] or "unknown",
        "bytes": len(body), "truncated": truncated,
        "robots": rob,
        "ignored_robots": {"ignored": bool(ignore_robots), "reason": robots_reason} if ignore_robots else None,
    }
    if "html" in out["content_type"] or "xml" in out["content_type"]:
        p = _Reader(out["final_url"])
        try:
            p.feed(text_body)
        except Exception as e:
            out["parse_error"] = f"{type(e).__name__}: {e}"
        out["title"] = html.unescape(" ".join(p.title.split()))[:300]
        out["description"] = html.unescape(p.description)
        out["text"] = p.text()
        seen, links = set(), []
        for l in p.links:
            if l["url"] not in seen:
                seen.add(l["url"]); links.append(l)
        out["links"] = links
        out["counts"] = {"characters": len(out["text"]), "links": len(links)}
    else:
        out["text"] = text_body if out["content_type"].startswith("text/") else ""
        out["links"] = []
        out["counts"] = {"characters": len(out["text"]), "links": 0}
        if not out["text"]:
            out["note"] = (f"{out['content_type']} is not text; this unit reads pages, and "
                           f"handing back bytes it cannot read would be pretending otherwise")
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse urllib's automatic redirects so every hop can be checked first."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
