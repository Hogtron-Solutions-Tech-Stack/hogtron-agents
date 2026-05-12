"""Trend-signals handler — scrapes public sources for market signals.

V1 supports Etsy search (the primary signal for POD). Pinterest / Reddit /
TikTok are deferred until the SerpAPI-driven approach is ported (cleaner
ToS posture than direct scraping anyway).

Ported from FactoryHQ/tools/etsy_search.py + agents/researcher.py discover().
Stateless: caller supplies queries, gets back raw signal records. Caller
owns persistence.

POLITENESS: Etsy is being scraped, not API-queried. Rate-limit between
requests via the configured delay. Aggressive use will trigger CAPTCHAs
and soft-block the source IP. Be a good citizen.
"""
from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .briefs import ResearchBrief, ResearchFinding


ETSY_SEARCH_URL = "https://www.etsy.com/search"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_DELAY_SEC = 2.5


class _Throttler:
    """Per-process polite delay. Module-level state — only used by the
    handler, not exposed publicly."""
    last_request_ts = 0.0


def _polite_sleep(min_delay: float) -> None:
    elapsed = time.time() - _Throttler.last_request_ts
    if elapsed < min_delay:
        time.sleep(min_delay - elapsed)
    _Throttler.last_request_ts = time.time()


def _extract_listing_id(href: str) -> Optional[str]:
    m = re.search(r"/listing/(\d+)/", href or "")
    return m.group(1) if m else None


def _search_etsy(query: str, limit: int, ua: str, delay: float) -> list[dict]:
    params = {"q": query, "ref": "search_bar", "explicit": "1"}
    url = f"{ETSY_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    _polite_sleep(delay)
    resp = requests.get(
        url,
        headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"},
        timeout=15,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for card in soup.select("a.listing-link, a[data-listing-id]")[:limit]:
        listing_id = card.get("data-listing-id") or _extract_listing_id(card.get("href", ""))
        if not listing_id:
            continue
        title_el = card.select_one("h3") or card.find("h3")
        price_el = card.select_one(".currency-value, .n-listing-card__price .currency-value")
        shop_el = card.select_one(".v2-listing-card__shop, p.text-gray-lighter")
        sales_el = card.select_one(".wt-text-caption.wt-text-truncate, span.wt-text-caption")

        results.append({
            "source": "etsy",
            "source_query": query,
            "listing_id": listing_id,
            "title": (title_el.get_text(strip=True) if title_el else "").strip(),
            "url": card.get("href", "").split("?")[0],
            "price": (price_el.get_text(strip=True) if price_el else None),
            "shop": (shop_el.get_text(strip=True) if shop_el else None),
            "sales_badge": (sales_el.get_text(strip=True) if sales_el else None),
        })
    return results


def trend_signals(brief: ResearchBrief) -> ResearchFinding:
    """Scrape market signals from public sources.

    brief.payload:
      queries (list[str], required) — search terms to scrape
      source  (str, default 'etsy') — only 'etsy' supported in v1
      limit_per_query (int, default 20)
    brief.context:
      user_agent (optional, falls back to default Chrome UA)
      delay_sec (optional, falls back to env ETSY_REQUEST_DELAY_SEC or 2.5)
    """
    queries = brief.payload.get("queries")
    if not queries:
        raise ValueError("trend_signals brief.payload must include 'queries' (list)")

    source = (brief.payload.get("source") or "etsy").lower()
    if source != "etsy":
        return ResearchFinding(
            kind="trend_signals", status="error",
            reason=f"source {source!r} not supported in v1; only 'etsy'",
        )

    limit = int(brief.payload.get("limit_per_query") or 20)
    ua = brief.context.get("user_agent") or DEFAULT_USER_AGENT
    delay = float(
        brief.context.get("delay_sec")
        or os.environ.get("ETSY_REQUEST_DELAY_SEC")
        or DEFAULT_DELAY_SEC
    )

    all_signals = []
    per_query_counts: dict[str, int] = {}
    errors: list[dict] = []

    for q in queries:
        try:
            signals = _search_etsy(q, limit, ua, delay)
            all_signals.extend(signals)
            per_query_counts[q] = len(signals)
        except requests.HTTPError as e:
            errors.append({"query": q, "error": f"HTTP {e.response.status_code}"})
        except Exception as e:
            errors.append({"query": q, "error": str(e)[:200]})

    return ResearchFinding(
        kind="trend_signals",
        status="ok" if all_signals else "error" if errors else "ok",
        payload={"signals": all_signals, "errors": errors},
        metadata={
            "source": source,
            "n_signals": len(all_signals),
            "per_query_counts": per_query_counts,
            "n_errors": len(errors),
        },
        reason=f"scraped {len(all_signals)} signals across {len(queries)} queries"
               + (f"; {len(errors)} errors" if errors else ""),
    )
