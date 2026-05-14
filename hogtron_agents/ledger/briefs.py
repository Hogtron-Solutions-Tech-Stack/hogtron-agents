"""Ledger department brief + asset types.

Ledger produces *financial state* — internal-only deliverables that
describe revenue, cost, margin, and AR. Compare to Sales (closing motions
for prospects) and Operations (publish actions). Ledger never touches
external surfaces; it reads from PayPal/Anthropic/Railway and writes only
to Supabase ledger_* tables.
"""
from __future__ import annotations

from typing import Literal, Any, Optional
from pydantic import BaseModel, Field


LedgerKind = Literal[
    "pnl_snapshot",        # Roll up revenue + cost for a date (or date range) → ledger_snapshots row
    "pull_paypal",         # Sync PayPal transactions into ledger_costs (revenue) + payments
    "pull_anthropic",      # Aggregate ceo_runs + dept_runs cost_usd → ledger_costs (tokens)
    "pull_railway",        # Pull Railway usage → ledger_costs (hosting)
    "client_margin",       # Per-client P&L: revenue from invoices - attributable cost
    "ar_overview",         # Open / overdue invoice rollup
    "threshold_check",     # Phase 2: evaluate ledger_thresholds → alert payload
]


class LedgerBrief(BaseModel):
    kind: LedgerKind
    payload: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    requester: Optional[str] = None


class LedgerAsset(BaseModel):
    """Internal-only deliverable. Structure varies by kind:

    - pnl_snapshot: payload has {date, revenue_usd, cost_*_usd, net_usd,
        sources: [...]}; metadata has the snapshot row id
    - pull_paypal: payload has {transactions: [...], new_count, total_usd,
        days}; metadata has dedup stats
    - pull_anthropic: payload has {by_dept: {...}, by_model: {...},
        total_usd, window_days}
    - pull_railway: payload has {by_service: [...], total_usd, period}
    - client_margin: payload has {clients: [{name, invoiced, paid, attributable_cost,
        margin_pct}]}
    - ar_overview: payload has {open: [...], overdue: [...], totals}
    - threshold_check: payload has {breached: [...], healthy: [...]};
        each alert: {source, period, actual_usd, limit_usd, severity}
    """
    kind: LedgerKind
    summary: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
