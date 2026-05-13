---
tags: [hogtron, agents, roadmap]
aliases: [status, what-next]
---

# Roadmap

## What shipped (2026-05-12)

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

**Infrastructure**
- ✅ Repo created: `C:\Users\sbilg\Code\hogtron-agents\` (6 commits)
- ✅ Constraint locked: [[infra|Supabase for DB, Railway+subdomains for hosting]]
- ✅ Constraint locked: client mockup URLs are frozen
- ✅ Docs written (this folder) as Obsidian-friendly vault, mirrored into `Hogtron Solutions LLC/Agentic System/`

## Next up

### Immediate (sessions 1-2)
- [x] **Apify decision** — chose **option (b)**: dashboard keeps its richer tools (`seo_audit`, `lead_scraper`) as-is. Apify's ROI only justifies the cost+latency for JS-rendered SEO audits; for email enrichment and Maps fallback it loses to plain HTTP + Google Places. If Research ever needs JS-rendered scraping, we add a `WebScraperProvider` Protocol (same shape as `TMProvider`) and inject Apify from the caller. Two callers stay deferred: `seo_audit.py`, `lead_scraper.py`. No further migration churn here.
- [x] **Live-test the migrated Researcher end-to-end** (2026-05-12). Phases 2 + 3 ran cleanly. Phase 1 hit Etsy bot-detection (403) — not a migration issue. Two bugs caught + fixed during the test (Postgres SQL compat: `f708fc0`; error-logging order: `4144757`). Claude correctly prioritized seasonal windows when given empty signals. All 46 phrases cleared due to pre-existing `tm_marks` empty-table issue — see below.
- [ ] **Migrate `tm_marks` USPTO data to Supabase**. Pre-existing debt surfaced by the live test: the 1.67M-mark USPTO corpus is loaded only in the local SQLite file, not Supabase Postgres. `ip_clear` runs cleanly through the dispatcher but matches nothing because the table is empty. Either re-import the USPTO bulk download into Supabase or keep tm_marks in SQLite with a hybrid connection. Until resolved, IP clearance is **blocklist-only** in production — characters/brands/lyrics still caught, but TM strikes won't be.
- [ ] **Etsy scraping** — currently 403'd. Options: rotate UA, add residential proxy, switch to SerpAPI-style indirect approach for trend_signals (`site:etsy.com` queries). Same pattern used for `platform_presence` already.
- [ ] Live-test `find_leads` once GCP billing is unpaused OR via OSM-only path.
- [ ] **PDF pipeline migration** — `FactoryHQ/agents/pdf_researcher.py` still uses `etsy_search.search()` + `blocklist.check()` directly. Same migration shape as `researcher.py`.

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
