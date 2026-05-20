"""SEO audit handler — scrape + LLM-score the 5 on-page SEO pillars.

Ported from hogtron-dashboard/tools/seo_audit.py. Stateless. Provider
selectable per call: gemini | anthropic | xai. All keys come from brief
context or env. Apify fallback is intentionally NOT ported — that's an
Operations concern (paid scraping infra), not Research.

Returns the same JSON shape as the GEO Auditor service so report
templates can stay shared.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .briefs import ResearchBrief, ResearchFinding


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


_SYSTEM_PROMPT = "You are an SEO auditor. Always respond with valid JSON only — no markdown, no explanations."


_PROMPT = """You are a senior on-page SEO auditor. Analyze the scraped data below and score 5 SEO pillars (0-100).

URL: {url}
Title: {title}
Meta Description: {meta_description}
Word Count: {word_count}
H1 count: {h1_count}
H2 count: {h2_count}
Has Schema: {has_schema}
Internal Links: {internal_links}
Image Alt Coverage: {alt_coverage}%

Headings:
{headings}

Content excerpt:
{body_text}

IMPORTANT — Programmatic base scores have already been calculated from the raw data:
{base_scores_text}
Use these as your starting point. You may adjust each pillar score by AT MOST plus or minus 8 points based on qualitative factors the scraper cannot detect (writing quality, keyword intent, UX context). Do NOT deviate more than 8 points from any base score. The overall_score must equal the average of your 5 final pillar scores (rounded to nearest int).

Score on these pillars:
1. title_and_meta — title tag length+quality, meta description, keyword targeting
2. content_depth — word count, topical coverage, originality signals
3. heading_structure — H1 uniqueness, H2/H3 hierarchy, semantic grouping
4. technical_signals — schema presence, internal linking, image alt coverage
5. local_relevance — NAP info, location keywords, service-area clarity

For each pillar return {{score, grade (A=90+ B=75-89 C=60-74 D=45-59 F<45), summary, top_issues (2-3), quick_wins (2-3)}}.

Respond with ONLY valid JSON, no markdown:
{{
  "overall_score": <int>,
  "overall_grade": "<letter>",
  "business_type_detected": "<string>",
  "one_line_verdict": "<string>",
  "pillars": {{
    "title_and_meta":      {{"score": <int>, "grade": "<letter>", "summary": "<string>", "top_issues": [], "quick_wins": []}},
    "content_depth":       {{"score": <int>, "grade": "<letter>", "summary": "<string>", "top_issues": [], "quick_wins": []}},
    "heading_structure":   {{"score": <int>, "grade": "<letter>", "summary": "<string>", "top_issues": [], "quick_wins": []}},
    "technical_signals":   {{"score": <int>, "grade": "<letter>", "summary": "<string>", "top_issues": [], "quick_wins": []}},
    "local_relevance":     {{"score": <int>, "grade": "<letter>", "summary": "<string>", "top_issues": [], "quick_wins": []}}
  }},
  "priority_action": "<the single highest-impact fix this week>"
}}
"""


# --- Scrape -------------------------------------------------------------

def _scrape(url: str) -> dict:
    resp = requests.get(url, headers=_HEADERS, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    meta_desc = ""
    for tag in soup.find_all("meta"):
        if tag.get("name", "").lower() == "description":
            meta_desc = tag.get("content", "").strip()
            break

    headings = []
    h1_count = h2_count = 0
    for level in ["h1", "h2", "h3"]:
        for tag in soup.find_all(level):
            text = tag.get_text(strip=True)
            if not text:
                continue
            headings.append({"level": level.upper(), "text": text})
            if level == "h1":
                h1_count += 1
            if level == "h2":
                h2_count += 1

    schema_tags = soup.find_all("script", {"type": "application/ld+json"})
    has_schema = bool(schema_tags)
    schema_types = []
    for tag in schema_tags:
        try:
            data = json.loads(tag.string or "")
            t = data.get("@type") or (data.get("@graph", [{}])[0].get("@type", ""))
            if t:
                schema_types.append(t if isinstance(t, str) else ", ".join(t))
        except Exception:
            pass

    has_faq = bool(re.search(r"\b(faq|frequently asked|q&a)\b", resp.text, re.I))

    imgs = soup.find_all("img")
    if imgs:
        with_alt = sum(1 for i in imgs if i.get("alt"))
        alt_coverage = round((with_alt / len(imgs)) * 100)
    else:
        alt_coverage = 100

    host = urlparse(url).netloc
    internal_links = 0
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/") or host in href:
            internal_links += 1

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    body_text = soup.get_text(separator="\n", strip=True)
    lines = [ln for ln in body_text.splitlines() if len(ln.strip()) > 30]
    body_text = "\n".join(lines[:200])

    return {
        "url": url, "title": title, "meta_description": meta_desc,
        "headings": headings[:25], "h1_count": h1_count, "h2_count": h2_count,
        "body_text": body_text, "word_count": len(body_text.split()),
        "has_schema": has_schema, "schema_types": schema_types,
        "has_faq": has_faq, "alt_coverage": alt_coverage,
        "internal_links": internal_links,
    }


# --- Base scores --------------------------------------------------------

def _base_scores(s: dict) -> dict:
    t = 0
    title = s.get("title", "")
    meta_desc = s.get("meta_description", "")
    if title:
        t += 20
        if 50 <= len(title) <= 60:
            t += 25
        elif 30 <= len(title) <= 70:
            t += 12
    if meta_desc:
        t += 20
        if 120 <= len(meta_desc) <= 158:
            t += 25
        elif 80 <= len(meta_desc) <= 160:
            t += 12
    combined = (title + " " + meta_desc).lower()
    kw_hits = sum(1 for kw in ["service", "local", "near", "call", "contact", "location", "hours"] if kw in combined)
    t += min(kw_hits * 5, 10)
    title_and_meta = min(t, 100)

    wc = s.get("word_count", 0)
    if wc >= 1500:
        content_depth = 85
    elif wc >= 800:
        content_depth = 65
    elif wc >= 400:
        content_depth = 45
    elif wc >= 200:
        content_depth = 30
    else:
        content_depth = 10

    h = 0
    h1 = s.get("h1_count", 0)
    h2 = s.get("h2_count", 0)
    if h1 == 1:
        h += 40
    elif h1 > 1:
        h += 20
    if h2 >= 4:
        h += 40
    elif h2 >= 2:
        h += 25
    elif h2 >= 1:
        h += 10
    h3_count = sum(1 for hd in s.get("headings", []) if hd["level"] == "H3")
    if h3_count >= 2:
        h += 20
    elif h3_count >= 1:
        h += 10
    heading_structure = min(h, 100)

    ts = 0
    if s.get("has_schema"):
        ts += 35
    alt = s.get("alt_coverage", 0)
    if alt >= 100:
        ts += 30
    elif alt >= 80:
        ts += 20
    elif alt >= 60:
        ts += 10
    links = s.get("internal_links", 0)
    if links >= 15:
        ts += 25
    elif links >= 8:
        ts += 15
    elif links >= 3:
        ts += 8
    if s.get("has_faq"):
        ts += 10
    technical_signals = min(ts, 100)

    lr = 0
    body = s.get("body_text", "").lower()
    if re.search(r'\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}', body):
        lr += 25
    if any(kw in body for kw in ["street", "ave", "blvd", "road", "suite", "address"]):
        lr += 20
    if any(kw in body for kw in ["serving", "service area", "near me", "local", "city", "county"]):
        lr += 25
    if any(kw in body for kw in ["hours", "open", "monday", "tuesday", "sunday"]):
        lr += 15
    if any(kw in body for kw in ["contact", "call us", "get a quote", "free estimate"]):
        lr += 15
    local_relevance = min(lr, 100)

    pillars = {
        "title_and_meta": title_and_meta,
        "content_depth": content_depth,
        "heading_structure": heading_structure,
        "technical_signals": technical_signals,
        "local_relevance": local_relevance,
    }
    return {"pillars": pillars, "overall": round(sum(pillars.values()) / len(pillars))}


# --- LLM callers --------------------------------------------------------

def _call_gemini(prompt: str, api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2, "maxOutputTokens": 4000,
            "responseMimeType": "application/json",
        },
    }
    for _ in range(3):
        resp = requests.post(url, params={"key": api_key}, json=payload, timeout=60)
        if resp.status_code == 429:
            time.sleep(8)
            continue
        if resp.status_code in (401, 403):
            raise ValueError("Invalid Gemini API key")
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("Gemini rate-limited after 3 attempts")


def _call_anthropic(prompt: str, api_key: str) -> str:
    """Route Anthropic SEO audit through the shared router.

    See docs/LLM_PROTOCOL.md — direct anthropic.* / requests.post to
    api.anthropic.com is disallowed so HOGTRON_FORCE_BACKEND=local can
    redirect every Anthropic call to Ollama in one place.
    """
    from hogtron_agents._shared import claude_router
    resp = claude_router.route_messages_create(
        agent="research.seo_audit.anthropic",
        model="claude-haiku-4-5-20251001",
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
        api_key=api_key or None,
    )
    return "".join(
        getattr(b, "text", "") or ""
        for b in (resp.content or [])
        if getattr(b, "type", None) == "text"
    )


def _call_xai(prompt: str, api_key: str) -> str:
    payload = {
        "model": "grok-4-fast-non-reasoning",
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000, "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for _ in range(3):
        resp = requests.post("https://api.x.ai/v1/chat/completions",
                             headers=headers, json=payload, timeout=60)
        if resp.status_code == 429:
            time.sleep(8)
            continue
        if resp.status_code == 401:
            raise ValueError("Invalid xAI API key")
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    raise RuntimeError("xAI rate-limited after 3 attempts")


def _parse_json(raw: str) -> dict:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        relaxed = re.sub(r",(\s*[}\]])", r"\1", cleaned)
        return json.loads(relaxed)


def _call_local(prompt: str, api_key: str) -> str:
    """Route SEO audit through the local LLM router (Ollama, etc.).

    The `api_key` argument is ignored — the router reads its config from
    HOGTRON_FORCE_BACKEND / LOCAL_LLM_* env vars. Kept in the signature so
    the dispatcher table stays uniform with the other callers.
    """
    from hogtron_agents._shared import claude_router
    resp = claude_router.route_messages_create(
        agent="research.seo_audit.local",
        model="claude-haiku-4-5-20251001",
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=4000,
    )
    return "".join(
        getattr(b, "text", "") or ""
        for b in (resp.content or [])
        if getattr(b, "type", None) == "text"
    )


_PROVIDER_ENV = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
    # "local" needs no env key — handled in seo_audit() below.
}
_CALLERS = {
    "gemini": _call_gemini,
    "anthropic": _call_anthropic,
    "xai": _call_xai,
    "local": _call_local,
}


# --- Public handler -----------------------------------------------------

def seo_audit(brief: ResearchBrief) -> ResearchFinding:
    """Run an on-page SEO audit on a URL.

    brief.payload:
      url (required)
    brief.context:
      provider (optional, default 'gemini'): gemini | anthropic | xai | local
      <provider>_api_key (optional, falls back to env; ignored for local)

    When HOGTRON_FORCE_BACKEND=local is set in the environment, the provider
    is forced to "local" regardless of what the caller asked for. This is
    the safety net against accidental Claude API spend during local-mode
    development.
    """
    url = (brief.payload.get("url") or "").strip()
    if not url:
        raise ValueError("seo_audit brief.payload must include 'url'")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    provider = (brief.context.get("provider") or "gemini").lower()
    # Safety net: when the platform is forced to the local backend, never
    # spend tokens on a remote provider regardless of what the caller asked
    # for. This mirrors the Dashboard's SEO_AUDIT_PROVIDER override in
    # Hogtron-Dashboard/config.py.
    if os.environ.get("HOGTRON_FORCE_BACKEND", "").strip().lower() == "local":
        provider = "local"
    if provider not in _CALLERS:
        raise ValueError(f"unknown provider {provider!r}; must be {'|'.join(_CALLERS)}")

    if provider == "local":
        api_key = ""  # router handles its own config
    else:
        api_key = (
            brief.context.get(f"{provider}_api_key")
            or os.environ.get(_PROVIDER_ENV[provider])
        )
        if not api_key:
            return ResearchFinding(
                kind="seo_audit", status="error",
                reason=f"{_PROVIDER_ENV[provider]} not set",
                payload={"url": url, "provider": provider},
            )

    try:
        scraped = _scrape(url)
    except requests.RequestException as e:
        return ResearchFinding(
            kind="seo_audit", status="error",
            reason=f"scrape failed: {e}",
            payload={"url": url},
        )

    base = _base_scores(scraped)
    headings_text = "\n".join(f"  {h['level']}: {h['text']}" for h in scraped["headings"]) or "(none)"
    base_scores_text = (
        f"  title_and_meta:    {base['pillars']['title_and_meta']}/100\n"
        f"  content_depth:     {base['pillars']['content_depth']}/100\n"
        f"  heading_structure: {base['pillars']['heading_structure']}/100\n"
        f"  technical_signals: {base['pillars']['technical_signals']}/100\n"
        f"  local_relevance:   {base['pillars']['local_relevance']}/100\n"
        f"  overall:           {base['overall']}/100"
    )
    prompt = _PROMPT.format(
        url=scraped["url"], title=scraped["title"],
        meta_description=scraped["meta_description"],
        word_count=scraped["word_count"], h1_count=scraped["h1_count"],
        h2_count=scraped["h2_count"], has_schema=scraped["has_schema"],
        internal_links=scraped["internal_links"], alt_coverage=scraped["alt_coverage"],
        headings=headings_text, body_text=scraped["body_text"][:2000],
        base_scores_text=base_scores_text,
    )

    raw = _CALLERS[provider](prompt, api_key)
    audit = _parse_json(raw)

    return ResearchFinding(
        kind="seo_audit",
        status="ok",
        payload={
            "meta": {
                "url": scraped["url"], "title": scraped["title"],
                "word_count": scraped["word_count"],
                "has_schema": scraped["has_schema"],
                "schema_types": scraped["schema_types"],
                "has_faq": scraped["has_faq"], "provider": provider,
            },
            "audit": audit,
        },
        metadata={
            "url": url, "provider": provider,
            "overall_score": audit.get("overall_score"),
            "overall_grade": audit.get("overall_grade"),
            "base_overall": base["overall"],
        },
    )
