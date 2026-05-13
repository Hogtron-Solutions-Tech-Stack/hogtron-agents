---
tags: [hogtron, agents, infra, decision]
aliases: [infrastructure, hosting, database]
---

# Infrastructure

Hard constraints on database and hosting for all HogTron systems. Locked 2026-05-12.

## Database — Supabase only

All persistent state goes to the shared Supabase Postgres. No new SQLite files. No new local-only DBs.

**Why**: single source of truth across machines (Sean + Anthony work from different machines), shared schema, free tier covers current scale, already wired for hogtron-dashboard.

**How to apply**: When designing a new module that needs persistence, default to a new table in Supabase. SQLite is acceptable only for ephemeral local caches (e.g. the Recraft download cache used by [[creative-department|Creative]]'s shirt handler). Anything a teammate or production might need to read goes to Supabase.

**Migration debt**: FactoryHQ currently runs SQLite locally. That's existing tech debt to migrate, not a precedent to extend. The migration is bounded by:
- `tm_marks` table (1.67M rows, regenerable from USPTO bulk downloads) — can be re-imported into Supabase rather than copied
- `raw_signals`, `concepts`, `phrase_candidates`, `briefs`, `designs`, `agents`, `agent_logs` tables — straight schema port
- Designer/Researcher/Marketer/Distributor agent code already reads via SQLAlchemy with portable SQL, so the swap is mostly the connection string

## Hosting — Railway, subdomain pattern

All hosted services live on Railway under a subdomain of `hogtron-solutions.com`. Pattern: `<service>.hogtron-solutions.com`.

Existing:
- `dashboard.hogtron-solutions.com` — hogtron-dashboard
- mockup gallery (Railway URL, custom subdomain deferred — see below)

**Why**: consistent SSL, predictable DNS via IONOS, one billing surface, Railway's deploy approvals already wired with the dashboard's deploy pill.

## ⚠️ DO NOT TOUCH: live client mockup URLs

The Railway-hosted client mockup gallery URLs are already shared with active customers:
- Sorcery & Scripts
- Discinsanity
- Full Send Nutrition

Those URLs are **frozen**.

**How to apply**: Never change the mockup gallery's Railway URL, route paths, or file naming. New mockup features add routes; they don't rename existing ones. If a rebuild is needed, preserve old URLs as redirects.

## External accounts in play

| Service | Purpose | Status |
|---|---|---|
| **Anthropic (Claude)** | All LLM reasoning (departments + Layer 2/3) | Active |
| **Recraft** | Image generation for Creative (shirt kind, future POD kinds) | Active |
| **Printify** | POD fulfillment, connects to Etsy + Shopify | Active |
| **Etsy** (CottonForgeBoutique) | POD sales channel | Active |
| **Shopify** | New sales channel (added 2026-05-12). Not yet wired. | Pending integration |
| **Canva** (via Canva MCP) | Design work for Creative `canva_asset` kind | Connected, kind stubbed |
| **Pinterest** | Cross-posting for Etsy listings | Trial access pending |
| **Google Places API** | `find_leads` primary provider | GCP billing paused 2026-05-06 |
| **OpenStreetMap (Overpass + Nominatim)** | `find_leads` free fallback | Active |
| **SerpAPI** | `platform_presence` Google site-restricted searches | Active (free tier, 100/mo) |
| **Foursquare** | dashboard lead scraper fallback | Active (not in Research v1) |
| **Apify** | Dashboard JS-rendered scraping (opt-in) | Available (not in Research v1) |
| **Gemini / xAI** | `seo_audit` optional providers | Gemini key stale, xAI not tested |
| **Groq** | dashboard SEO audit (legacy) | Active |
| **USPTO** | `ip_clear` trademark data (bulk download) | 1.67M marks loaded locally |
| **Railway** | All hosted services | Active |
| **Supabase** | All persistent state | Active |
| **IONOS** | DNS for hogtron-solutions.com | Active |

## Cost discipline (Layer 2/3)

The 5am `ceo_daily` cron (`FactoryHQ/scripts/daily_ceo.py`) fires `ceo.run_autonomous()` once per day. Typical spend per run: **$1-1.50 Claude + $0 ops** (publishing is held at autonomy rung 0). Live test today (3-dept chain) was $1.08.

### Spend telemetry tables (Supabase, shipped 2026-05-12)
- **`ceo_runs`** — one row per CEO call. Captures total Claude cost (CEO + nested dept), ops cost (Etsy fees, etc.), duration, iterations, journal_path, source (`daily_cron` | `ad_hoc` | etc.).
- **`dept_runs`** — one row per nested dept call within a ceo_runs row. FK on `ceo_run_id` with CASCADE delete.

### Still to come
- Hard daily caps per department + global cap (no enforcement yet — telemetry first to establish baselines)
- Budget alerts via Slack webhook
- A dashboard widget rendering daily spend trend
