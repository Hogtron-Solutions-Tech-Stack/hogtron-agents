"""Platform presence handler — auto-detects which delivery aggregators a
restaurant is listed on via Google site-restricted searches.

Ported from hogtron-dashboard/tools/aggregator_audit/checkers/. Stateless;
SerpAPI key from brief.context or env.

NOTE: the *report generation* (revenue projection, recommendations,
HogTron pricing) stays in hogtron-dashboard — that's Sales/Marketing
territory, not Research. Research just reports presence.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

import requests

from .briefs import ResearchBrief, ResearchFinding


PLATFORM_DOMAINS: dict[str, str] = {
    "doordash":  "doordash.com",
    "ubereats":  "ubereats.com",
    "grubhub":   "grubhub.com",
    "slice":     "slicelife.com",
}

LISTING_PATTERNS: dict[str, re.Pattern] = {
    "doordash":  re.compile(r"https?://(?:www\.)?doordash\.com/(?:store|en-us/store)/", re.I),
    "ubereats":  re.compile(r"https?://(?:www\.)?ubereats\.com/(?:[a-z\-]+/)?(?:store|food-delivery)/", re.I),
    "grubhub":   re.compile(r"https?://(?:www\.)?grubhub\.com/(?:restaurant|food)/", re.I),
    "slice":     re.compile(r"https?://(?:www\.)?slicelife\.com/restaurants/", re.I),
}


@dataclass
class SearchResult:
    title: str
    link: str
    snippet: str


class SearchProviderError(Exception):
    pass


class _SerpApi:
    URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: Optional[str], timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        if not self.api_key:
            raise SearchProviderError("SERPAPI_API_KEY not set")
        try:
            resp = requests.get(
                self.URL,
                params={
                    "q": query, "engine": "google", "api_key": self.api_key,
                    "num": num_results, "hl": "en", "gl": "us",
                },
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise SearchProviderError(f"network: {e}") from e

        if resp.status_code == 401:
            raise SearchProviderError("SerpAPI rejected the API key")
        if resp.status_code == 429:
            raise SearchProviderError("SerpAPI quota / rate limit hit")
        resp.raise_for_status()

        organic = (resp.json() or {}).get("organic_results") or []
        return [
            SearchResult(
                title=(r.get("title") or "").strip(),
                link=(r.get("link") or "").strip(),
                snippet=(r.get("snippet") or "").strip(),
            )
            for r in organic
        ]


def _slug_words(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return [w for w in words if len(w) >= 3]


def _confidence(name: str, city: str, url: str, title: str, snippet: str) -> float:
    haystack = f"{url}\n{title}\n{snippet}".lower()
    name_hits = sum(1 for w in _slug_words(name) if w in haystack)
    city_hits = 1 if (city and city.lower() in haystack) else 0
    if name_hits >= 2 and city_hits:
        return 1.0
    if name_hits >= 1 and city_hits:
        return 0.85
    if name_hits >= 1:
        return 0.7
    return 0.4


def _build_query(platform: str, name: str, city: str, state: str) -> str:
    parts = [f'"{name}"']
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    parts.append(f"site:{PLATFORM_DOMAINS[platform]}")
    return " ".join(parts)


def _check_one(platform: str, name: str, city: str, state: str, search: _SerpApi) -> dict:
    query = _build_query(platform, name, city, state)
    try:
        results = search.search(query, num_results=5)
    except SearchProviderError as e:
        return {"listed": None, "url": None, "title": None, "snippet": None,
                "confidence": 0.0, "notes": f"check failed: {e}"}

    pattern = LISTING_PATTERNS[platform]
    best = None
    for r in results:
        if not pattern.search(r.link):
            continue
        c = _confidence(name, city, r.link, r.title, r.snippet)
        if not best or c > best["confidence"]:
            best = {
                "listed": True, "url": r.link, "title": r.title,
                "snippet": r.snippet, "confidence": c, "notes": None,
            }
    if best:
        if best["confidence"] < 0.7:
            best["notes"] = "low-confidence match — verify URL before relying on it"
        return best
    if results:
        return {"listed": False, "url": None, "title": None, "snippet": None,
                "confidence": 0.85, "notes": None}
    return {"listed": None, "url": None, "title": None, "snippet": None,
            "confidence": 0.3, "notes": "no results — couldn't confirm either way"}


def platform_presence(brief: ResearchBrief) -> ResearchFinding:
    """Detect which platforms a restaurant is listed on.

    brief.payload:
      name (required) — restaurant name
      city (optional) — disambiguates by location
      state (optional) — disambiguates further
      platforms (optional) — subset of PLATFORM_DOMAINS keys, default all
    brief.context:
      serpapi_api_key (optional, falls back to env SERPAPI_API_KEY)
    """
    name = brief.payload.get("name")
    if not name:
        raise ValueError("platform_presence brief.payload must include 'name'")

    city = brief.payload.get("city", "")
    state = brief.payload.get("state", "")
    platforms = brief.payload.get("platforms") or list(PLATFORM_DOMAINS.keys())

    unknown = [p for p in platforms if p not in PLATFORM_DOMAINS]
    if unknown:
        raise ValueError(f"unknown platforms: {unknown}. Known: {list(PLATFORM_DOMAINS.keys())}")

    api_key = brief.context.get("serpapi_api_key") or os.environ.get("SERPAPI_API_KEY")
    search = _SerpApi(api_key=api_key)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(platforms)) as ex:
        futures = {
            ex.submit(_check_one, p, name, city, state, search): p
            for p in platforms
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                results[slug] = fut.result()
            except Exception as e:
                results[slug] = {"listed": None, "url": None, "title": None,
                                 "snippet": None, "confidence": 0.0,
                                 "notes": f"exception: {e}"}

    n_listed = sum(1 for v in results.values() if v.get("listed") is True)
    n_missing = sum(1 for v in results.values() if v.get("listed") is False)
    n_unknown = sum(1 for v in results.values() if v.get("listed") is None)

    return ResearchFinding(
        kind="platform_presence",
        status="ok",
        payload={"results": results},
        metadata={
            "name": name, "city": city, "state": state,
            "platforms_checked": platforms,
            "n_listed": n_listed, "n_missing": n_missing, "n_unknown": n_unknown,
        },
    )
