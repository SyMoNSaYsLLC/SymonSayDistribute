# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""symonweb tests.

Most of these need no network, because most of what matters is what this REFUSES. The few that
do reach out are marked, and they test the two things that cannot be faked: that a real page
comes back parsed, and that a real browser renders one.
"""
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from symonweb import browse as B
from symonweb import fetch as F
from symonweb import guard as G

TOKEN = uuid.uuid4().hex


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SYM_WEB_TOKEN", TOKEN)
    import service
    importlib.reload(service)
    return TestClient(service.app)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


# --- the refusal this component exists for ---------------------------------------------
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8811/api/board/settings",   # the estate's own control board
    "http://localhost:8816/api/fabric/components",  # the fabric
    "http://10.0.0.1/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
])
def test_a_private_address_is_refused_however_it_is_spelled(url):
    with pytest.raises(G.Refused, match="not a public address"):
        G.check_public(url)


def test_the_refusal_says_why_it_matters_not_just_that_it_happened():
    with pytest.raises(G.Refused, match="going around it through a fetch is the hole"):
        G.check_public("http://127.0.0.1:8811/")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "gopher://x/1"])
def test_only_http_and_https_are_fetched(url):
    with pytest.raises(G.Refused, match="is not a scheme this fetches"):
        G.check_public(url)


def test_a_host_that_does_not_resolve_is_refused_rather_than_attempted():
    with pytest.raises(G.Refused, match="does not resolve"):
        G.check_public("http://this-host-does-not-exist-symonweb-test.invalid/")


# --- politeness ---------------------------------------------------------------------------
def test_one_fetch_per_host_per_interval():
    now = [0.0]
    p = G.Politeness(min_interval_s=2.0, clock=lambda: now[0])
    p.check("example.com")
    with pytest.raises(G.Refused, match="1.0s left|this unit waits"):
        p.check("example.com")
    now[0] = 2.0
    p.check("example.com")          # the interval has passed


def test_politeness_is_per_host_not_global():
    now = [0.0]
    p = G.Politeness(min_interval_s=5.0, clock=lambda: now[0])
    p.check("a.example"); p.check("b.example")      # different hosts do not block each other


def test_a_negative_interval_is_refused():
    with pytest.raises(ValueError, match="not an interval"):
        G.Politeness(min_interval_s=-1)


# --- robots -----------------------------------------------------------------------------
def test_ignoring_robots_without_a_reason_is_refused():
    with pytest.raises(G.Refused, match="needs a recorded reason"):
        F.fetch("https://example.com/", ignore_robots=True, robots_reason="   ")


def test_unknown_robots_is_reported_as_unknown_and_not_as_permission():
    r = G.robots_allows("http://this-host-does-not-exist-symonweb-test.invalid/x")
    assert r["allowed"] is None and "not permission" in r["note"]


# --- parsing, without the network ---------------------------------------------------------
def test_the_title_is_read_even_though_head_is_dropped():
    p = F._Reader("https://x.example/")
    p.feed("<html><head><title>Hello</title></head><body><p>Body text</p></body></html>")
    assert p.title == "Hello" and "Body text" in p.text()


def test_script_and_style_never_reach_the_text():
    p = F._Reader("https://x.example/")
    p.feed("<body><script>var secret=1</script><style>.a{}</style><p>Real</p></body>")
    t = p.text()
    assert "Real" in t and "secret" not in t and ".a{}" not in t


def test_relative_links_are_resolved_against_the_final_url():
    p = F._Reader("https://x.example/dir/page.html")
    p.feed('<body><a href="../other.html">Other</a><a href="mailto:a@b.c">Mail</a></body>')
    urls = [l["url"] for l in p.links]
    assert "https://x.example/other.html" in urls
    assert not any(u.startswith("mailto:") for u in urls)   # only http(s) is a link here


# --- drivers ------------------------------------------------------------------------------
def test_driver_discovery_names_a_family_for_each():
    for d in B.drivers():
        assert d["driver"] in B.FAMILIES and d["browser"]


def test_an_absent_driver_is_refused_by_name():
    if not B.drivers():
        pytest.skip("no driver on this host")
    with pytest.raises(B.BrowserError, match="is not present"):
        B.Session(driver="geckodriver-that-is-not-here")


def test_nothing_in_the_client_is_specific_to_one_browser():
    import inspect
    src = inspect.getsource(B)
    body = src.split("FAMILIES = {", 1)[1].split("}", 1)[1]
    for word in ("thorium", "Thorium", "chromium"):
        assert word not in body.split("SEARCH =")[0], f"{word} outside the family table"


# --- over http ----------------------------------------------------------------------------
def test_health_is_public_and_the_rest_is_closed(monkeypatch):
    monkeypatch.delenv("SYM_WEB_TOKEN", raising=False)
    import service
    importlib.reload(service)
    c = TestClient(service.app)
    assert c.get("/api/symonweb/health").status_code == 200
    assert c.get("/api/symonweb/drivers").status_code == 503


def test_fetching_the_estates_own_board_is_403_with_the_reason(client):
    r = client.post("/api/symonweb/fetch", headers=auth(),
                    json={"url": "http://127.0.0.1:8811/api/board/settings"})
    assert r.status_code == 403
    assert "not a public address" in r.json()["detail"]["refused"]


def test_check_answers_without_making_a_request(client):
    r = client.get("/api/symonweb/check?url=http://127.0.0.1:9001/v1/models", headers=auth())
    assert r.status_code == 200 and r.json()["allowed"] is False


# --- live: the two things that cannot be faked ------------------------------------------------
@pytest.mark.network
def test_a_real_page_comes_back_parsed():
    r = F.fetch("https://example.com/")
    assert r["status"] == 200 and r["title"] == "Example Domain"
    assert "Example Domain" in r["text"] and r["counts"]["links"] >= 1


@pytest.mark.network
def test_a_real_browser_renders_and_the_session_is_closed():
    if not B.drivers():
        pytest.skip("no driver on this host")
    r = B.visit("https://example.com/")
    assert r["title"] == "Example Domain" and r["rendered"] is True
    assert "Example Domain" in r["text"]
