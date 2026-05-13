---
tags: [hogtron, agents, department, research]
aliases: [research, intel-dept]
---

# Research Department

> Intel: market trends, lead discovery, IP clearance, SEO/GEO audits, platform-presence detection.

## Status

✅ All 7 kinds live. 4 live-tested, 2 smoke-tested only.

| Kind | Status | Used by |
|---|---|---|
| `ip_clear` | ✅ live-tested (USPTO 1.67M marks) | Factory (gates every design) |
| `geo_audit` | ✅ live-tested (discinsanity.com → 5/F, matches existing data) | Agency |
| `seo_audit` | ✅ live-tested (discinsanity.com → 37/F via Anthropic Haiku, matches existing) | Agency |
| `platform_presence` | ✅ live-tested (Joe's Pizza Bethlehem PA → not on DoorDash) | Agency |
| `cluster_concepts` | ✅ smoke-tested (Claude cost — live test deferred) | Factory |
| `trend_signals` | ✅ smoke-tested (Etsy scraping risk — live test deferred) | Factory |
| `find_leads` | ✅ smoke-tested (GCP billing paused) | Agency |

## Usage

```python
from hogtron_agents.research import Research, ResearchBrief

r = Research(tm_provider=my_tm_adapter)  # tm_provider only needed for ip_clear

finding = r.do(ResearchBrief(
    kind="ip_clear",
    payload={"phrase": "Coffee makes me less stabby"},
))
# finding.status -> "clear" | "blocked" | "tm_hit" | "error"
```

## Kinds

### `ip_clear`

Two-stage IP clearance:
1. **Blocklist** (pure, no IO) — checks against known characters, brands, public figures, lyric fragments. Hard reject on hit.
2. **USPTO trademark check** — exact match + n-gram + fuzzy (rapidfuzz, 92% threshold) against live apparel-class marks (classes 025 + 035).

The TM data lookup is delegated to a [[patterns#the-provider-protocol-pattern|TMProvider Protocol]]. FactoryHQ implements it against its SQLite `tm_marks` table; future Supabase migration is a one-line caller change.

```python
finding = r.do(ResearchBrief(kind="ip_clear", payload={"phrase": "Pikachu Vibes"}))
# status="blocked", reason="blocklist hit: character_or_brand"

finding = r.do(ResearchBrief(kind="ip_clear", payload={"phrase": "Coffee makes me less stabby"}))
# status="clear" (when TMProvider returns no hits)
```

### `geo_audit`

Thin client for the deployed [GEO Auditor service](https://geo-auditor-aryw.onrender.com). Scrapes + scores 5 GEO pillars (conversational clarity, entity density, direct-answer formatting, citation worthiness, schema). Returns the same JSON shape the dashboard's report templates expect.

```python
finding = r.do(ResearchBrief(kind="geo_audit", payload={"url": "discinsanity.com"}))
# finding.metadata["overall_score"] -> 5
# finding.metadata["overall_grade"] -> "F"
```

### `seo_audit`

Scrape + LLM-score 5 on-page SEO pillars (title_and_meta, content_depth, heading_structure, technical_signals, local_relevance). Programmatic base scores anchor the LLM to prevent score drift.

Three provider options, selected via `brief.context["provider"]`:
- `gemini` (default) — free tier on Google AI Studio
- `anthropic` — Claude Haiku, cheapest paid
- `xai` — Grok

```python
finding = r.do(ResearchBrief(
    kind="seo_audit",
    payload={"url": "discinsanity.com"},
    context={"provider": "anthropic"},
))
# finding.metadata["overall_score"] -> 37
# finding.payload["audit"]["one_line_verdict"] -> "Critical SEO gaps..."
```

### `platform_presence`

Auto-detects which delivery aggregators a restaurant is listed on. Site-restricted Google queries via SerpAPI (e.g. `"Joe's Pizza" Bethlehem PA site:doordash.com`). Parallel per-platform via `ThreadPoolExecutor`. Confidence-scored matches.

Platforms: DoorDash, Uber Eats, Grubhub, Slice (pizza-only).

```python
finding = r.do(ResearchBrief(
    kind="platform_presence",
    payload={"name": "Joe's Pizza", "city": "Bethlehem", "state": "PA"},
))
# finding.payload["results"]["doordash"] -> {"listed": False, ...}
```

**Note:** the *report generation* (revenue projection, recommendations, HogTron pricing) lives in hogtron-dashboard — that's Sales/Marketing territory, not Research. Research just detects presence.

### `cluster_concepts`

Claude Opus 4.7 + Pydantic structured output. Given raw signals + optional seasonal hint, returns Etsy-shirt concepts with phrase candidates. Same IP rules as Creative's shirt handler enforce no characters/brands/lyrics at synthesis time.

```python
finding = r.do(ResearchBrief(
    kind="cluster_concepts",
    payload={
        "signals": [...],         # list of {title, sales_badge} from trend_signals
        "max_concepts": 5,
        "seasonal_hint": "Mother's Day is in 4 weeks...",
    },
))
# finding.payload["concepts"] -> [{concept, audience, saturation, seasonal_window, phrases}, ...]
```

### `trend_signals`

Scrapes Etsy public search results. BeautifulSoup + polite throttling (2.5s default, configurable). Each search returns `{listing_id, title, url, price, shop, sales_badge}`.

Pinterest / Reddit / TikTok deferred — direct scraping has worse ToS posture than the SerpAPI route used for `platform_presence`. When we add those, they'll likely route through SerpAPI.

```python
finding = r.do(ResearchBrief(
    kind="trend_signals",
    payload={"queries": ["funny coffee shirt", "teacher life shirt"], "limit_per_query": 20},
))
# finding.payload["signals"] -> [40 listings across 2 queries]
```

### `find_leads`

Google Places (New API) primary → OSM Overpass fallback. By zip / city+state / county+state. Returns leads with standard schema: `business_name, industry, address, city, state, zip, county, phone, website, rating, review_count, source`.

V1 scope intentionally **skips** Foursquare, Apify, and email enrichment — they live in the dashboard's `lead_scraper.py` for now. Caller can extend.

```python
finding = r.do(ResearchBrief(
    kind="find_leads",
    payload={"industry": "pizzeria", "city": "Bethlehem", "state": "PA", "limit": 20},
))
# finding.payload["leads"] -> [...]
# finding.metadata["source"] -> "google" or "osm"
```

## TMProvider — implementation guide

When you want to use `ip_clear`, you need to supply a `TMProvider`:

```python
from hogtron_agents.research import Research, TMProvider

class MyTMProvider:
    def query_exact(self, candidates: list[str]) -> list[dict]:
        # return live apparel-class marks (classes 025/035) where
        # mark_normalized exactly matches any candidate
        ...
    def query_prefix_bucket(self, prefixes: set[str]) -> list[dict]:
        # return live apparel-class marks where mark_normalized starts
        # with any 3-char prefix. Research will rapidfuzz-score them.
        ...

r = Research(tm_provider=MyTMProvider())
```

The reference implementation against FactoryHQ's SQLite tm_marks is in this session's live test in [[roadmap#what-shipped-2026-05-12]]. The Supabase version (deferred per [[infra]]) will be a similar adapter pointing at Postgres.

## Migration impact on existing code

**hogtron-dashboard/tools/geo_audit.py** — ✅ **migrated** (commit `d8bca1b`). Plugin `run(params)` now builds a `ResearchBrief(kind='geo_audit', ...)` and unwraps `finding.payload`. JSON return shape identical (verified: discinsanity.com → score 5 / grade F before and after).

**hogtron-dashboard/tools/aggregator_audit/checkers/platform_checks.py::check_all_platforms** — ✅ **migrated** (commit `d8bca1b`). The multi-platform entrypoint delegates to `Research(kind='platform_presence')`. The single-platform `check_platform()`, `PLATFORM_DOMAINS`, and `LISTING_PATTERNS` were preserved for any direct callers. Route handler at `routes/aggregator_audit.py:174` unchanged.

**hogtron-dashboard/tools/seo_audit.py** — ⏸️ **deferred**. Has an opt-in `use_apify` checkbox in the dashboard form for JS-rendered sites. Research's `seo_audit` intentionally scoped out Apify (Operations concern). Migrating would silently drop that feature. Decision point captured in [[roadmap#next-up]].

**hogtron-dashboard/tools/lead_scraper.py** — ⏸️ **deferred**. Has Foursquare + Apify + email enrichment beyond Research's `find_leads` v1 scope.

**FactoryHQ/agents/researcher.py** — ✅ **all three phases migrated** (commit `c50d30b`). Same pattern as `designer.py`: queue runner + DB writes + state machine + tm_checks cache stayed in `researcher.py`; the three phases now delegate to Research:

| Phase | Before | After |
|---|---|---|
| `discover()` | per-query `etsy_search.search()` loop | one `Research.do(trend_signals)` call |
| `synthesize()` | direct `anthropic.Anthropic().messages.parse()` with local Pydantic schemas + 60-line SYSTEM_PROMPT | one `Research.do(cluster_concepts)` call |
| `vet_pending()` | `blocklist.check()` + `trademark_check.check()` per phrase | one `Research.do(ip_clear)` call per phrase, with the local `tm_checks` cache preserved as inline `_tm_cache_get`/`_tm_cache_put` helpers (kept in FactoryHQ — caller owns caching per [[patterns#the-stateless-departments-stateful-callers]]) |

The `_Phrase` / `_Concept` / `_SynthesisOutput` Pydantic schemas, the synthesis SYSTEM_PROMPT, and `_build_user_prompt` are all gone from `researcher.py` — single source of truth now lives in `hogtron_agents.research._cluster_concepts`.

**New adapter:** `FactoryHQ/tools/tm_provider.py` contains `FactorySQLiteTMProvider`, satisfying the `TMProvider` Protocol against FactoryHQ's SQLite `tm_marks` table. The one file that needs to change when tm_marks moves to Supabase per [[infra]].

**Sean's WIP first:** before migrating, the `research_blanks()` + `research_pod_lineup()` functions (Adam picking shirt blanks for HogTron merch + recommending color/blueprint expansion for CottonForgeBoutique) were committed as `e6d0832` to keep authorship clean.
