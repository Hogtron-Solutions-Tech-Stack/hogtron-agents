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
- [ ] **Apify decision** — either (a) bring Apify into Research's `seo_audit` + `find_leads`, or (b) accept the dashboard keeps its richer tools long-term. Drives whether seo_audit + lead_scraper get migrated. Only Research caller migration left after this decision.
- [ ] Live-test the migrated Researcher end-to-end (run `python -m agents.researcher discover` → `synthesize` → `vet` on a small batch and confirm parity with pre-migration behavior).
- [ ] Live-test `cluster_concepts` once a real signal corpus is freshly scraped (covered by the above).
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
