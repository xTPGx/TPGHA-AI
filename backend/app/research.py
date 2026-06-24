"""Lightweight research/search layer for general Jarvis conversation.

This is intentionally read-only. It gives the assistant web context for normal
questions without giving arbitrary web content permission to execute actions.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

import httpx

logger = logging.getLogger("tpg.research")

_SEARCH_HINT_RE = re.compile(
    r"\b(search|look up|lookup|google|web|internet|latest|today|current|news|weather|forecast|who won|"
    r"price|stock|release|version|near me)\b",
    re.I,
)
_RESULT_RE = re.compile(
    r'<a[^>]+class="result-link"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
    r'<a[^>]+class="result-snippet"[^>]*>(?P<snippet>.*?)</a>',
    re.I | re.S,
)


def should_search(message: str) -> bool:
    return bool(_SEARCH_HINT_RE.search(message or ""))


async def search_web(query: str, max_results: int = 5) -> dict[str, Any]:
    """Search the public web using DuckDuckGo HTML results.

    No API key is required, which keeps first-run setup sane for HA users. If
    search fails, callers get a structured degraded response instead of a crash.
    """

    query = (query or "").strip()
    if not query:
        return {"query": query, "provider": "duckduckgo_html", "results": [], "error": "Query is required."}
    max_results = max(1, min(8, int(max_results or 5)))
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": "TPGHomeAI/1.0 (+https://github.com/xTPGx/TPGHA-AI)",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface degraded search cleanly
        logger.warning("Web search failed (%s).", type(exc).__name__)
        return {
            "query": query,
            "provider": "duckduckgo_html",
            "results": [],
            "error": f"Search failed: {type(exc).__name__}.",
        }

    results = _parse_results(response.text, max_results)
    return {
        "query": query,
        "provider": "duckduckgo_html",
        "results": results,
        "error": "" if results else "No search results returned.",
    }


def format_search_context(search: dict[str, Any]) -> str:
    if search.get("error") and not search.get("results"):
        return f"Web search attempted for '{search.get('query', '')}' but failed: {search.get('error')}"
    lines = [f"Web search results for: {search.get('query', '')}"]
    for idx, item in enumerate(search.get("results") or [], start=1):
        lines.append(
            f"{idx}. {item.get('title', '')}\n"
            f"   {item.get('snippet', '')}\n"
            f"   {item.get('url', '')}"
        )
    return "\n".join(lines)


def _parse_results(body: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for match in _RESULT_RE.finditer(body):
        title = _clean_html(match.group("title"))
        snippet = _clean_html(match.group("snippet"))
        href = _clean_url(html.unescape(match.group("href")))
        if not title or not href:
            continue
        results.append({"title": title, "url": href, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _clean_html(value: str) -> str:
    text = re.sub(r"<.*?>", "", value or "")
    text = html.unescape(text)
    return " ".join(text.split()).strip()


def _clean_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.path == "/l/" and parsed.query:
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return value.strip()
