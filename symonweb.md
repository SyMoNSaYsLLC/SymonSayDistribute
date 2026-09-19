# symonweb

Reaching the web: fetching pages, and driving a browser.

This page describes what is **running**: the unit answers on 8818, and both paths were
exercised against a live page before this was written.

## The boundary this unit sits on

Every other component in this estate binds loopback and talks to things on this host. This one
goes out — and it does so on behalf of a model that takes its instructions from whoever is
talking to it.

That combination has one specific failure, and most of this unit is about it: the shortest path
from *"summarise this page for me"* to *"read the control board"* is a link. A model persuaded
to fetch `http://127.0.0.1:8811/api/board/settings` would be reaching the estate's own services
from outside the fabric — the exact indirection the fabric exists to prevent, handed to whoever
writes the prompt.

So every address is resolved and checked **before** the request and **after every redirect**.
Loopback, private ranges, link-local, reserved, multicast: refused, with the reason. urllib's
automatic redirects are turned off and each hop is taken by hand, because checking only the
first address is the same as not checking — a public URL that redirects to `127.0.0.1` is the
whole attack.

    http://127.0.0.1:8811/api/board/settings   refused
    http://localhost:8816/api/fabric/...       refused
    http://169.254.169.254/latest/meta-data/   refused
    file:///etc/passwd                         refused — only http and https
    https://example.com/                       allowed

## Two ways to read a page, and they are not interchangeable

    fetch    one HTTP request, no javascript. Fast and cheap; what most pages need.
    browse   a real browser. Scripts run, and the text is what a READER would see.

`browse` is asked for rather than defaulted to, because it costs a browser process. Measured
here it is quicker than expected — a full visit to a live page in **0.8 s** — which is worth
recording because the first launch took over ten seconds and the difference is a cold start,
not the steady state. When a test later ran in 1.05 s it looked too fast to be real; it was
real, and checking beat assuming.

## Any browser, not this one

The browser on this host is Thorium 138, reached through `chromedriver`. Nothing in the client
knows that.

It speaks **W3C WebDriver**, a published standard that chromedriver, geckodriver, msedgedriver
and safaridriver all implement. The only browser-specific thing in the module is a small table
of how each family asks for headless mode, and a driver missing from that table still works —
it simply gets no headless argument, which is honest rather than a guess that silently opens a
window on somebody's desktop. A test asserts no browser name appears outside that table.

There is no selenium here for the same reason there is no bs4: WebDriver is JSON over HTTP and
HTML text extraction is `html.parser`. Both are standard library. bs4, lxml and httpx are
installed on this host and all three are permissive, so using them would not have changed the
placement — they would have changed the **census**, and a dependency carried in every release
should earn that.

## What else it refuses

**robots.txt.** Honoured, and a robots.txt that cannot be read is reported as `unknown`, never
as permission — "we could not ask" and "it said yes" are different, and only one is consent.
`ignore_robots` exists because there are legitimate reasons, and it requires a recorded reason;
passing it without one is refused.

**Impatience.** One request per host per interval, with no default interval, because how this
estate behaves toward other people's servers is a decision and not something to inherit.

**Size.** Capped mid-stream rather than after the body has been read.

Nothing that identifies this host ever leaves it: no cookies, no referer, no credential. There
is no parameter to add one.

## Routes

    GET  /api/symonweb/health     public; answers before the unit is configured
    GET  /api/symonweb/drivers    which W3C drivers exist here
    GET  /api/symonweb/robots     what robots.txt says, without fetching the page
    GET  /api/symonweb/check      would this be allowed, and where does it resolve
    POST /api/symonweb/fetch      one request, no javascript
    POST /api/symonweb/browse     a real browser, rendered

Health is public; the rest need `SYM_WEB_TOKEN`, and an unset token closes the unit.

## Placement

    placement-triage prospect symonweb --sources python-stdlib@PSF-2.0
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The browser and its driver are invoked as programs, never linked or imported, so they are not
components of this artifact.

## Testing

26 tests, and 24 of them need no network because most of what matters is what this refuses:
five private-address spellings including the estate's own board and the cloud metadata address,
three non-http schemes, a host that does not resolve, politeness per host and not globally,
ignoring robots without a reason, unknown robots reported as unknown, script and style never
reaching the text, relative links resolved and `mailto:` excluded, and no browser name outside
the family table.

The two that do reach out test what cannot be faked: a real page comes back parsed, and a real
browser renders one.

    python3 -m pytest tests/ -q              everything
    python3 -m pytest tests/ -m network -q   only the two live ones

## Releases

Tagged `symonweb/v<version>`.
