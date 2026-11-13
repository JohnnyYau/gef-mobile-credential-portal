"""web_research.py — public-web lookups for the person in context.

Real backends (both free, keyless):
  - Wikipedia search API
  - DuckDuckGo Instant Answer API

This sandbox has no outbound internet (only an allowlist), so real calls fail
gracefully and the endpoint reports ``status: "unavailable"`` with a clear
reason. Deployments with internet (Render/Railway) get live results with zero
config.

``WEB_RESEARCH_MOCK=1`` enables clearly-labeled *demo fixture* results so the
UI capability can be demonstrated without a network. Mock results always carry
``sample: true`` / ``demo: true`` and are never mistaken for real sources.

Privacy (hard): only the person's name (+ issuing organisation) is ever sent
to a public API. StudentID and DOB are never part of a web query.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger("web")

ENABLED = os.environ.get("WEB_RESEARCH_ENABLED", "1") not in ("0", "false", "False", "")
MOCK = os.environ.get("WEB_RESEARCH_MOCK", "0") not in ("0", "false", "False", "")
TIMEOUT = 6

WIKI_API = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
            "&list=search&srlimit=3&srsearch=")
DDG_API = "https://api.duckduckgo.com/?format=json&no_html=1&q="

_MOCK_SNIPPETS = {
    "chan tai man": ("Sample web result (demo mode): named in the University of Utopia "
                     "2025 graduating-class honours list. This is a demo fixture, not a "
                     "real public source."),
    "leung wai sum": ("Sample web result (demo mode): profile appears in the 2025 "
                      "University of Utopia alumni directory. This is a demo fixture, "
                      "not a real public source."),
    "lee siu ming": ("Sample web result (demo mode): listed as a 2023 graduate of the "
                     "University of Utopia computing programme. This is a demo fixture, "
                     "not a real public source."),
}


def _http_json(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Gef26-Verification-Portal/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _wikipedia(queries):
    for q in queries:
        try:
            data = _http_json(WIKI_API + urllib.parse.quote(q))
            hits = (data.get("query", {}).get("search") or [])[:3]
        except Exception as exc:  # noqa: BLE001
            logger.warning("wikipedia search failed (%s): %s", q, exc)
            continue
        sources = []
        for hit in hits:
            title = str(hit.get("title", ""))
            snippet = (str(hit.get("snippet") or "")
                       .replace('<span class="searchmatch">', "")
                       .replace("</span>", ""))
            url = ("https://en.wikipedia.org/wiki/"
                   + urllib.parse.quote(title.replace(" ", "_")))
            sources.append({"title": title, "url": url, "snippet": snippet})
        if sources:
            return sources
    return []


def _duckduckgo(queries):
    for q in queries:
        try:
            data = _http_json(DDG_API + urllib.parse.quote(q))
        except Exception as exc:  # noqa: BLE001
            logger.warning("duckduckgo search failed (%s): %s", q, exc)
            continue
        abstract = (data.get("AbstractText") or "").strip()
        if abstract:
            return [{
                "title": data.get("Heading") or "DuckDuckGo result",
                "url": (data.get("AbstractURL")
                        or "https://duckduckgo.com/?q=" + urllib.parse.quote(q)),
                "snippet": abstract[:300],
            }]
    return []


def _mock(queries, name):
    snippet = _MOCK_SNIPPETS.get(name.lower().strip())
    if not snippet:
        return {
            "status": "unavailable",
            "demo": True,
            "reason": "no sample results for this person (mock mode)",
        }
    return {
        "status": "ok",
        "demo": True,
        "queried": queries,
        "note": ("Demo fixture — not a real public source. Enable outbound "
                 "internet on the deployment for live lookups."),
        "sources": [
            {"title": f"[sample] {name} — University of Utopia 2025 graduate",
             "url": "https://example.com/demo/graduate-2025",
             "snippet": snippet, "sample": True},
            {"title": "[sample] UU 2025 Honours List",
             "url": "https://example.com/demo/honours-2025",
             "snippet": ("Sample web result (demo mode): 2025 honours-list extract. "
                         "Not a real public source."),
             "sample": True},
        ],
    }


def search_person(name, org=None):
    """Search public sources for a person. Never include StudentID or DOB."""
    if not ENABLED:
        return {"status": "unavailable", "reason": "WEB_RESEARCH_ENABLED=0"}
    queries = [name]
    if org:
        queries.append(f"{name} {org}")
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:2]
    if MOCK:
        return _mock(queries, name)
    sources = _wikipedia(queries) or _duckduckgo(queries)
    if not sources:
        return {
            "status": "unavailable",
            "reason": ("no public sources found or no outbound internet from this "
                       "server (this sandbox only allows a small allowlist)"),
        }
    return {
        "status": "ok",
        "queried": queries,
        "sources": sources,
        "note": "Results are public-web lookups, not chain records.",
    }
