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

Two Etsy backends, chosen via `brief.context['backend']`:

- **`serpapi` (default when `SERPAPI_API_KEY` is set)**: site-restricted Google queries (`<phrase> site:etsy.com`). ToS-clean, ~2s/query, bypasses Etsy's anti-bot defenses. Returns `{listing_id, title, url, snippet}` — but no `sales_badge` or `price` (SerpAPI doesn't surface those).
- **`direct` (fallback)**: BS4 scrape of `etsy.com/search`. Returns the full record including `sales_badge` (the gold trend signal), but Etsy 403s scrapers aggressively. Use with polite throttling.
- **`auto`** (the actual default): serpapi if key set, else direct.

Pinterest / Reddit / TikTok deferred — when we add those, they'll likely route through SerpAPI for the same reasons.

```python
finding = r.do(ResearchBrief(
    kind="trend_signals",
    payload={"queries": ["funny coffee shirt", "teacher life shirt"], "limit_per_query": 20},
    context={"backend": "auto"},  # or "serpapi" or "direct"
))
# finding.metadata["backend"] -> "serpapi"
# finding.payload["signals"] -> [15 listings across 2 queries]
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

The reference implementation lives in `FactoryHQ/tools/tm_provider.py::FactorySQLiteTMProvider`. Its name is a holdover — it actually queries whatever DB is configured by `DATABASE_URL`. As of 2026-05-12 that's **Supabase Postgres with 771,853 live apparel-class rows** populated via `scripts/migrate_tm_marks_to_supabase.py`. The Protocol abstraction means `FactorySQLiteTMProvider` works against either SQLite or Postgres without modification.

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

## Layer 2 — `Research.run_autonomous(directive)`

Research is the first department to ship Layer 2 (autonomous reasoning over its 7 Layer 1 kinds). Commit `cb8654d`.

```python
r = Research(tm_provider=FactorySQLiteTMProvider())
result = r.run_autonomous(
    "List 3 IP-clear shirt phrases for graduation gifts.",
    anthropic_api_key="...",
    max_iterations=8,  # default 10
)
# result.summary      -> natural-language wrap-up from the model
# result.tool_calls   -> [{tool, input, elapsed_sec, result_summary, error}, ...]
# result.findings     -> [ResearchFinding, ...] (full Layer 1 results, untrimmed)
# result.cost_usd     -> ~$0.55 for the pilot directive above
# result.iterations   -> how many model turns happened
```

Architecture:
- `_autonomous.py::SYSTEM_PROMPT` defines the dept role + 7-tool catalog + operating principles (be efficient, IP guardrail is non-negotiable, no clarifying questions — just decide).
- `build_tools(research_instance)` wraps each Layer 1 kind as an `AgentTool` with a hand-tuned JSON schema and a closure-based handler that calls `research_instance.do(brief)` internally. The closure also appends every `ResearchFinding` to a shared list so the caller gets them all.
- `run_agent_loop()` from [[patterns|`_shared/agent_loop.py`]] handles the `tool_use` → `tool_result` cycle.
- `_summarize_finding()` trims each Layer 1 result before going back to the agent — full payload stays in `result.findings` for the caller, but the agent only sees the essentials (titles+URLs, not full JSON; score+verdict, not all 5 pillars). Keeps context tight across many tool calls.

First live result (2026-05-12):
- Directive: `"List 3 IP-clear shirt phrases for graduation gifts."`
- 5 iterations, 7 tool calls (1 trend_signals + 1 cluster_concepts + 5 ip_clear)
- Caught a real TM hit (`"Class of 2025: Now With Extra Letters After My Name"` → live mark `CLASS OF 2020`), recovered with a Masters Degree alternative
- Surfaced meta-insight: `"Class of [year]"` phrasings carry TM risk; recommended Creative avoid going forward. The deterministic vet_pending would not have noticed that pattern.
- 60 sec, **$0.55**

See [[architecture#layer-2-—-department-agent-loops-claude-tool-use]] for the cross-department picture.
