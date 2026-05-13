---
tags: [hogtron, agents, roadmap]
aliases: [status, what-next]
---

# Roadmap

## What shipped (2026-05-12)

**Layer 1 finalized.** All 5 departments scaffolded with 30 kinds total. **15 piloted with real handlers** (50%), 15 stubbed for future builds (net-new kinds + bigger ports tackled per Layer 2 need). The keystone POD shirt lifecycle is now end-to-end functional through departments:

```
Research(trend_signals)        # SerpAPI Etsy queries
  -> Research(cluster_concepts) # Claude concepts + phrases
  -> Research(ip_clear)         # blocklist + 771K USPTO marks
  -> Creative(shirt)            # Claude art-direct + Recraft render
  -> Operations(printify_upload)# create draft product
  -> Marketing(etsy_listing)    # Claude title/desc/tags
  -> Operations(publish_etsy)   # push draft to Etsy
  -> Operations(render_video)   # ffmpeg Ken Burns MP4
  -> Marketing(social_post)     # Claude Pinterest copy
  -> Operations(publish_pinterest) # create pin
```

Agency lifecycle is partial:
```
Research(find_leads) -> Research(seo_audit) -> Research(geo_audit)
  -> Research(platform_presence) -> Sales(aggregator_audit_report)
  -> ⏳ Sales(proposal) -> ⏳ Operations(deploy_proposal)
```




**Creative department**
- ✅ Package scaffolding (`hogtron_agents/`), pip-installable editable
- ✅ `shirt` kind fully ported from FactoryHQ/agents/designer.py
- ✅ Live-tested: World's Okayest Grill Dad, 25s end-to-end, IP guardrail clean
- ✅ FactoryHQ migrated to use Creative (designer.py 714 → 416 lines) — **committed (`405d2d8` on FactoryHQ)**
- ⏳ `pdf_page`, `mockup`, `proposal_cover`, `canva_asset` stubbed

**Research department**
- ✅ Dispatcher + all 7 kinds wired
- ✅ `ip_clear` ported + live-tested against 1.67M USPTO marks
- ✅ `geo_audit` ported + live-tested (discinsanity.com → 5/F)
- ✅ `seo_audit` ported + live-tested via Anthropic Haiku (discinsanity.com → 37/F)
- ✅ `platform_presence` ported + live-tested (Joe's Pizza Bethlehem → not on DoorDash)
- ✅ `cluster_concepts` ported (smoke-tested only — Claude cost)
- ✅ `trend_signals` ported (smoke-tested only — scraping risk)
- ✅ `find_leads` ported (Google Places + OSM fallback, smoke-tested only — GCP paused)

**Caller migrations to Research (proof points)**
- ✅ `hogtron-dashboard/tools/geo_audit.py` — delegates to Research (commit `d8bca1b`). Plugin shape preserved; route handler unchanged.
- ✅ `hogtron-dashboard/tools/aggregator_audit/checkers/platform_checks.py::check_all_platforms` — delegates to Research (commit `d8bca1b`). Single-platform helpers + LISTING_PATTERNS preserved for direct callers.
- ✅ `FactoryHQ/agents/researcher.py` — **all three phases migrated** (commit `c50d30b`). discover→trend_signals, synthesize→cluster_concepts, vet_pending→ip_clear. Sean's `research_blanks` + `research_pod_lineup` WIP committed first as `e6d0832`. New `FactoryHQ/tools/tm_provider.py` adapts SQLite tm_marks to the Research TMProvider Protocol — the one file that changes when tm_marks moves to Supabase.
- ⏸️ `hogtron-dashboard/tools/seo_audit.py` — **deferred**. Has opt-in Apify branch Research v1 doesn't support; migrating would silently drop a feature.
- ⏸️ `hogtron-dashboard/tools/lead_scraper.py` — **deferred**. Has Foursquare + Apify + email enrichment beyond Research's `find_leads` v1 scope.

**Marketing department**
- ✅ Dispatcher + 6 kinds wired (commit `09de5c9`)
- ✅ `etsy_listing` ported from FactoryHQ/agents/marketer.py (commit `09de5c9`). Pydantic `_Listing` schema, Etsy SYSTEM_PROMPT, tag/title guardrails.
- ✅ `social_post` ported from FactoryHQ/agents/pinterester.py LLM half (commit `8a749ef`). `_PinCopy` schema with title/description/alt_text caps. Companion to `publish_pinterest` in Operations.
- ⏳ `blog_post`, `review_response` stubbed with port-target pointers
- ⏳ `ad_copy`, `email_outreach` stubbed as net-new

**Sales department**
- ✅ Dispatcher + 5 kinds wired (commit `f83de78`)
- ✅ `aggregator_audit_report` ported from dashboard/tools/aggregator_audit/generator.py. Pure business logic: per-platform analysis, revenue projection with diminishing returns, ranked recommendations. Smoke+parity test against Tony's Pizza scenario passed.
- ⏳ `proposal` stubbed (port from dashboard proposal generator)
- ⏳ `follow_up`, `pricing_quote`, `contract` stubbed as net-new

**Operations department**
- ✅ Dispatcher + 7 kinds wired (commit `e0ea4c4`)
- ✅ `printify_upload` ported from FactoryHQ/agents/designer.py upload() (commit `e0ea4c4`). Inlines Printify HTTP calls so the department is self-contained.
- ✅ `publish_etsy` ported from FactoryHQ/agents/marketer.py publish() (commit `8a749ef`). Single POST to Printify's publish_product endpoint. cost_estimate_usd=$0.20 per call.
- ✅ `publish_pinterest` ported from FactoryHQ/agents/pinterester.py API half (commit `8a749ef`). POST /v5/pins to Pinterest API.
- ✅ `render_video` ported from FactoryHQ/tools/video.py + distributor.py (commit `8a749ef`). ffmpeg + PIL composition into 1080x1920 vertical MP4. Self-contained, local-only, free.
- ⏳ `deploy_mockup`, `deploy_proposal` stubbed with port-target pointers
- ⏳ `publish_shopify` stubbed as net-new (Shopify account fresh as of 2026-05-12)
- 💡 Every Operations kind carries `cost_estimate_usd` for Layer 3 budget caps

**Infrastructure**
- ✅ Repo: `C:\Users\sbilg\Code\hogtron-agents\` — 11 commits
- ✅ Constraint locked: [[infra|Supabase for DB, Railway+subdomains for hosting]]
- ✅ Constraint locked: client mockup URLs are frozen
- ✅ Docs written + mirrored into `Hogtron Solutions LLC/Agentic System/` (Obsidian RAG vault)

## Layer 2 — autonomous reasoning over Layer 1

**Pilot shipped on Research (2026-05-12, commit `cb8654d`).**

`Research.run_autonomous(directive)` takes a natural-language CEO-style directive and chains Layer 1 kinds as Claude tool calls until the directive is fulfilled.

Architecture: ~80-line agent loop in [`_shared/agent_loop.py`](C:/Users/sbilg/Code/hogtron-agents/hogtron_agents/_shared/agent_loop.py), uses anthropic SDK's `tool_use` API directly (no `claude-agent-sdk` dep). Per-dept module in `<dept>/_autonomous.py` defines the SYSTEM_PROMPT + JSON schema per kind + result trimming.

**First live result:**
- Directive: `"List 3 IP-clear shirt phrases for graduation gifts."`
- 5 iter, 7 tool calls (1 trend_signals → 1 cluster_concepts → 5 ip_clear), 60s, **$0.55**
- Caught a real TM hit, recovered with an alternate phrase, surfaced meta-insight (`"Class of [year]"` stem is risky)

**Layer 2 complete across all 5 departments (commit `84f4ef9`):**
- ✅ Research — 7 tools
- ✅ Marketing — 2 tools (etsy_listing + social_post). Live-tested: $0.14, 2 iter, both pieces produced + flagged downstream issue.
- ✅ Sales — 1 tool (aggregator_audit_report). Bare today; interface ready for future kinds.
- ✅ Operations — 4 tools (printify_upload, publish_etsy, publish_pinterest, render_video). SYSTEM_PROMPT enforces autonomy-ladder rung 0 (hold publish_* without explicit auth).
- ✅ Creative — 1 tool (shirt). Same shape for consistency.

## Layer 3 — CEO loop (shipped)

`CEO.run_autonomous(directive)` dispatches across all 5 departments. Each CEO tool call is itself a Layer 2 dept loop — costs compound.

Live result (2026-05-12): 1 directive → 3 dept calls → journal-ready summary in 161s, $1.08. The CEO autonomously surfaced 2 real downstream issues (image resolution mismatch, blank verification) without being asked. See [[architecture#layer-3-—-ceo-loop-cross-department-orchestration]] for the architecture detail.

**The 3-layer architecture is now complete and exercised end-to-end.**

## Daily wiring (shipped 2026-05-12 late)

The 5am cron has been swapped from the narrower `researcher.synthesize + vet_pending` to the full CEO loop:

- **`FactoryHQ/scripts/daily_ceo.py`** (commit `28b11a9`) — `run_daily_ceo()` constructs the CEO with all 5 dept instances (including `FactorySQLiteTMProvider` for Research), fires the configured directive, renders a journal entry, writes it to `hogtron-dashboard/docs/daily_log/YYYY-MM-DD-ceo.md`. CLI-callable for ad-hoc runs: `python scripts/daily_ceo.py "custom directive"`.
- **`FactoryHQ/jobs.py`** — replaces the `researcher_daily` APScheduler job with `ceo_daily` at 05:00. Old `run_researcher_synth` kept callable for CLI but no longer cron-scheduled.
- **Dashboard CSS** (commit `c8947c8`) — added `.user-ceo` dot color (pink `#f472b6`) so the Journal calendar renders CEO entries alongside Sean (cyan) + Anthony (gold) + combined (purple).

## Cost telemetry (shipped 2026-05-12 late)

Two new Supabase tables for tracking Layer 3 spend (commit `1fd9fd9`):

- **`ceo_runs`** — one row per `ceo.run_autonomous()` call. Captures source, directive, success, summary, duration, iterations, input/output tokens, Claude cost USD, real-world ops cost USD, stop_reason, error, journal_path.
- **`dept_runs`** — one row per nested dept call (FK to `ceo_runs.id`, CASCADE). Captures department, iterations, tool_calls_count, cost_usd, ops_cost_usd, summary.

Wired into `daily_ceo.py`: after each run, `log_run_to_db()` inserts both rows. Telemetry failures don't fail the run — the journal entry is the authoritative artifact.

Charts available:
```sql
-- Daily total spend
SELECT date(started_at), SUM(cost_usd + ops_cost_usd)
FROM ceo_runs GROUP BY 1 ORDER BY 1 DESC;

-- Per-department share over 7 days
SELECT department, SUM(cost_usd)
FROM dept_runs WHERE created_at > now() - interval '7 days'
GROUP BY 1 ORDER BY 2 DESC;
```

## Status: Layer 1 + first Layer 2 pilot

The 5-department dispatcher pattern is stable. 15 piloted Layer 1 kinds prove the architecture across LLM-driven work (Creative/Marketing/Research), pure logic (Sales aggregator_audit_report), external API calls (Operations publish_*), and local compute (Operations render_video). Layer 2 proven viable on Research.

Remaining Layer 1 stubs split into:
- **Net-new kinds (8):** `ad_copy`, `email_outreach`, `review_response`, `blog_post`, `follow_up`, `pricing_quote`, `contract`, `publish_shopify`. No existing source to port; build when Layer 2 needs them.
- **Ports deferred for use-case-driven need (7):** `pdf_page`, `mockup`, `proposal_cover`, `canva_asset`, `proposal`, `deploy_mockup`, `deploy_proposal`. Have port sources but tackling each when a Layer 2 directive surfaces the need.

## Next up

### Immediate (sessions 1-2)
- [x] **Apify decision** — chose **option (b)**: dashboard keeps its richer tools (`seo_audit`, `lead_scraper`) as-is. Two callers stay deferred. No further migration churn here.
- [x] **Live-test the migrated Researcher end-to-end** (2026-05-12). Phases 2 + 3 ran cleanly. Two bugs caught + fixed during the test (Postgres SQL compat: `f708fc0`; error-logging order: `4144757`).
- [x] **Migrate `tm_marks` USPTO data to Supabase** (commit `18d6f6d`). 771,853 live apparel-class rows streamed from local SQLite to Supabase Postgres in 444s @ 1738 rows/sec. New tool: `scripts/migrate_tm_marks_to_supabase.py` (re-runnable when USPTO refreshes). One wrinkle handled: Postgres btree index caps row size at ~2704 bytes, so `mark_normalized` is truncated to 500 chars during insert (real brand marks are short; long-form descriptions don't match typical shirt phrases anyway). **Verified**: `ip_clear` now catches real TM strikes — "Mama Bear" → 11 marks. IP guardrail is functional in production.
- [x] **Etsy scraping bypass** (commit `3d26ace`). Added SerpAPI backend to `trend_signals`: site-restricted Google queries (`<phrase> site:etsy.com`). ToS-clean, fast (~2s/query), not subject to Etsy's anti-bot defenses. Selected via `brief.context['backend']` = 'serpapi' | 'direct' | 'auto'. Auto picks serpapi when `SERPAPI_API_KEY` is set. Direct backend kept as fallback (only path that surfaces sales_badge data). **Verified**: 15 signals across 2 queries in 3.8s, zero errors.
- [ ] **Live-test `find_leads`** once GCP billing is unpaused OR via OSM-only path.
- [ ] **PDF pipeline migration** — `FactoryHQ/agents/pdf_researcher.py` still uses `etsy_search.search()` + `blocklist.check()` directly. Same migration shape as `researcher.py`.
- [x] **Caller migrations for new departments** (2026-05-12). Three completed:
  - `hogtron-dashboard/tools/aggregator_audit/generator.py` → Sales (commit `2ad70d7`). 267 → 99 lines. Parity verified against Tony's Pizza scenario.
  - `FactoryHQ/agents/marketer.py` → Marketing (commit `4029c56`). 263 → 203 lines. write_listing() now a queue runner around Marketing.write(etsy_listing); publish() unchanged pending Operations(publish_etsy).
  - `FactoryHQ/agents/designer.py::upload()` → Operations (commit `37a0961`). Phase 3 now delegates to Operations.do(printify_upload). regenerate() still uses tools.printify directly — needs a future `printify_swap_image` kind.
- [x] **Re-run end-to-end Researcher test** (2026-05-12, second pass). Full pipeline produced **real** results this time:
  - Phase 1 (discover via SerpAPI): 8 signals from `plant mom shirt` in 5s after fixing key forwarding in `FactoryHQ/agents/researcher.py` (commit `1cd80e5`). The first attempt fell through to the `direct` backend because `SERPAPI_API_KEY` wasn't forwarded via `brief.context`. Same pattern as `anthropic_api_key` in `synthesize`.
  - Phase 2 (synthesize via Claude): 3 concepts, 25s. Claude prioritized Father's Day + Graduation + Memorial Day correctly.
  - Phase 3 (vet_pending against real tm_marks): **3 of 18 phrases tm_fail'd** (17% strike-risk rejection rate). Real catches: "World's Okayest Dad" (1 mark), "Class of 2026: We Made It Weird" (2 marks), "Land of the Free, Home of the Grill" (3 marks), "Pour Decisions: A Teacher's Summer" (2 marks). These would have shipped to Etsy under the pre-migration trivially-clear regime.
  - DB state at end of run: 17 concepts in vetting, 10 tm_fail phrases, 85 cleared phrases, 61 queued briefs. **The full Research pipeline is functional in production.**

### Week 2 — Marketing department
- [ ] Port `etsy_listing` from FactoryHQ/agents/marketer.py
- [ ] Port `social_post` (Pinterest cross-post copy)
- [ ] Port `blog_post` from dashboard Social-to-Blog Engine
- [ ] Port `review_response` from dashboard AI Smart Review Responder
- [ ] Live-test against Discinsanity's published listings

### Week 3 — Sales department
- [ ] Port `proposal` from dashboard (10-page template assembly)
- [ ] Port `aggregator_audit_report` from dashboard
- [ ] Build `follow_up` net-new (no port source)

### Week 4 — Operations department
- [ ] Port `publish_etsy` from FactoryHQ marketer.py
- [ ] Add `publish_shopify` net-new (use Printify→Shopify channel)
- [ ] Port `publish_pinterest` from FactoryHQ pinterester.py
- [ ] Port `render_video` from FactoryHQ distributor.py
- [ ] Port `printify_upload` from FactoryHQ designer.py
- [ ] Port `deploy_mockup` + `deploy_proposal` from dashboard

### After all 5 departments at Layer 1
- [ ] Spike [[architecture#layer-2-—-department-agent-loops-claude-agent-sdk|Layer 2]] on **Research** (cheapest mistakes)
- [ ] Add per-department API spend telemetry → Supabase `dept_costs` table
- [ ] Add daily budget caps + Slack alerts
- [ ] Build [[architecture#layer-3-—-ceo-loop-cross-department-orchestration|Layer 3 CEO loop]]
- [ ] Move up the [[architecture#the-autonomy-ladder|autonomy ladder]] one rung at a time

## Known migration debt

- **FactoryHQ → Supabase**: SQLite tables to migrate. Bounded list in [[infra#database-—-supabase-only]].
- **Pinterest API trial**: still pending approval per project memory.
- **GCP billing paused** (2026-05-06): blocks `find_leads` Google path. OSM works in the interim.
- **Gemini API key stale**: blocks `seo_audit` default path. Anthropic Haiku works as fallback.

## Architectural decisions worth re-evaluating

- **IP clearance as its own department (Legal/Compliance)?** Currently sits in Research. If it gates more than just Creative (e.g. Marketing copy needs trademark checks before publishing ads, Sales needs to verify client names aren't trademarked), might graduate. Easy to extract — that's the point of the interface.
- **Operations as 1 department or split (Publishing + Infra)?** Watch as kinds accumulate. If Operations gets >10 kinds, consider splitting.
- **Should `canva_asset` be its own department later?** Canva is a big enough surface area (logos, decks, social posts, business cards) that it might warrant its own dept later. For now it's a Creative kind.
- **Layer 2 spike target.** Currently planning to spike on Research first (cheapest mistakes). Alternative: spike on Marketing first since the directives are more interesting ("plan next week's content calendar") even if mistakes cost more.

## Reading order for newcomers

[[overview]] → [[architecture]] → [[patterns]] → pick a department.
