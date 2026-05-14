---
tags: [hogtron, agents, department, ledger, finance]
aliases: [ledger, finance-dept]
---

# Ledger Department

> Internal-only finance head. Pulls revenue and cost from PayPal, Anthropic (via Supabase telemetry), and Railway into a daily P&L. Owns AR overview, per-client margin, and the cost-watchdog threshold engine.

Ledger is **internal-only** — it never produces client-facing content. Where [[sales-department|Sales]] writes prospect deliverables and [[operations-department|Operations]] publishes outward, Ledger reports inward.

## Status

✅ Scaffolded (2026-05-13). All seven Layer-1 kinds implemented. Cron entrypoint ready (`scripts/ledger_daily.py` in hogtron-dashboard). Threshold-check is wired but the Phase-2 Slack alerter is not yet — today the threshold panel on `/ledger` shows breach state only.

| Kind | Status | Notes |
|---|---|---|
| `pull_anthropic` | ✅ | Aggregates `ceo_runs.cost_usd + ops_cost_usd` and `dept_runs.cost_usd + ops_cost_usd` over a window. No external API. |
| `pull_paypal` | ✅ | Owns the PayPal REST integration ported from `hogtron-dashboard/tools/paypal_sync.py`. The dashboard module is now a thin adapter. |
| `pull_railway` | ✅ | GraphQL usage query — needs `RAILWAY_TOKEN` (Team Token). Pulls month-to-date USD per service. |
| `pnl_snapshot` | ✅ | Rolls a given date's `ledger_costs` rows into `ledger_snapshots`. Upsert on `snapshot_date`. |
| `client_margin` | ✅ | Per-client P&L from invoice + payment history. Attributable-cost stub (dept_runs.lead_id not yet wired). |
| `ar_overview` | ✅ | Open + overdue invoices with balances. |
| `threshold_check` | ✅ | Evaluates `ledger_thresholds` against today's `ledger_costs`. Returns breach list. Phase 2 wires Slack. |

## Usage

```python
from hogtron_agents.ledger import Ledger, LedgerBrief
import db  # caller wires their Supabase client

ctx = {
    "supabase": db.client(),
    "paypal":   {"client_id": "...", "secret": "...", "mode": "live"},
    "railway":  {"token": "...", "team_id": None},
}

l = Ledger()
asset = l.build(LedgerBrief(kind="pnl_snapshot",
                            payload={"date": "2026-05-13"},
                            context=ctx))
print(asset.summary)
```

Autonomous:

```python
result = l.run_autonomous(
    "Pull today's spend, refresh PayPal for 7 days, snapshot P&L, "
    "and tell me if we're tracking under budget.",
    anthropic_api_key=key, context=ctx,
)
```

## Schema

Three Supabase tables added in `hogtron-dashboard/scripts/migration_009_ledger.sql`:

- **`ledger_snapshots`** — one row per UTC day (unique on `snapshot_date`); revenue + cost-by-category columns + a generated `net_usd`.
- **`ledger_costs`** — granular per-line spend log. Unique on `(source, external_id)` for idempotent re-pulls.
- **`ledger_thresholds`** — budget rules: `{source, period, limit_usd, alert_channel}`. Seeded with four sensible defaults.

## Integration

- **/bridge** — LEDGER is the 7th agent in the roster (color `#10b981`, callsign `LEDGER`). Auto-picked up by `bridge_data` once it writes to `dept_runs`. Triggerable ad-hoc with five canned directive presets.
- **/ledger** — full dashboard page reads from the three tables + invoices/payments. KPI strip (revenue/cost/net/burn/AR), daily trend chart, source + category breakdown, AR tables, threshold gauges, recent-cost log.
- **scripts/ledger_daily.py** — standalone cron entrypoint. Pulls all sources, then writes today's snapshot. Wire to Railway Scheduled Jobs or local crontab.

## Design notes

- **Why department-head and not just a script?** Three of the seven kinds compose well under an LLM loop ("did we burn too much on Opus this week, and if so which dept?"). Wrapping them as tools means the CEO agent can call Ledger as part of an end-of-day rollup directive.
- **Why Sonnet 4.6 default?** Ledger work is deterministic aggregation plus light reasoning. Opus is overkill; Haiku struggles when the loop needs to chain three pulls and a snapshot.
- **Why a generated `net_usd` column?** So the dashboard never has to recompute it client-side and snapshot rows stay consistent under partial updates.
- **Attribution is honest.** `client_margin` does not heuristically spread unattributed cost across clients. When `dept_runs.lead_id` ships, real attribution comes for free.
