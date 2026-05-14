"""Anthropic API spend — aggregate ceo_runs + dept_runs cost columns.

Source of truth: Supabase tables `ceo_runs.cost_usd + ops_cost_usd` and
`dept_runs.cost_usd + ops_cost_usd`. The agent loop in `_shared/agent_loop.py`
populates these on every run, so summing them gives us actual Claude spend
without hitting Anthropic's billing API.

The caller passes in a Supabase client (avoids the agent package depending
on a specific db-init pattern). Returns plain dicts so it serializes cleanly
into LedgerAsset.payload.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


_MODEL_TIER = {
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-haiku-4-5":          "Haiku",
    "claude-sonnet-4-6":         "Sonnet",
    "claude-opus-4-7":           "Opus",
}


def _tier(model: str | None) -> str:
    if not model:
        return "Other"
    return _MODEL_TIER.get(model, "Other")


def aggregate_spend(supabase, *, days: int = 1) -> dict[str, Any]:
    """Sum Claude spend over the last `days` days.

    Returns:
      {
        total_usd: float,
        window_days: int,
        by_dept: {dept_name: float},
        by_model: {tier: float},
        by_day:   [{date: 'YYYY-MM-DD', cost: float}, ...],  # oldest first
        run_count: int,
      }
    """
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff = cutoff_dt.isoformat()

    by_dept: dict[str, float] = defaultdict(float)
    by_model: dict[str, float] = defaultdict(float)
    by_day: dict[str, float] = defaultdict(float)
    run_count = 0

    # CEO orchestration spend
    ceo_rows = (supabase.table("ceo_runs")
                .select("started_at, model, cost_usd, ops_cost_usd")
                .gte("started_at", cutoff).execute().data) or []
    for r in ceo_rows:
        cost = float(r.get("cost_usd") or 0) + float(r.get("ops_cost_usd") or 0)
        by_dept["ceo"] += cost
        by_model[_tier(r.get("model"))] += cost
        ts = r.get("started_at") or ""
        if ts:
            by_day[str(ts)[:10]] += cost
        run_count += 1

    # Department spend (includes ledger itself once it starts running)
    dept_rows = (supabase.table("dept_runs")
                 .select("created_at, department, model, cost_usd, ops_cost_usd")
                 .gte("created_at", cutoff).execute().data) or []
    for r in dept_rows:
        cost = float(r.get("cost_usd") or 0) + float(r.get("ops_cost_usd") or 0)
        dept = r.get("department") or "unknown"
        by_dept[dept] += cost
        by_model[_tier(r.get("model"))] += cost
        ts = r.get("created_at") or ""
        if ts:
            by_day[str(ts)[:10]] += cost
        run_count += 1

    # Fill in zero-cost days so the trend chart isn't gappy
    by_day_ordered = []
    for i in range(days):
        d = (cutoff_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        by_day_ordered.append({"date": d, "cost": round(by_day.get(d, 0.0), 4)})

    total = sum(by_dept.values())
    return {
        "total_usd":   round(total, 4),
        "window_days": days,
        "by_dept":     {k: round(v, 4) for k, v in by_dept.items()},
        "by_model":    {k: round(v, 4) for k, v in by_model.items()},
        "by_day":      by_day_ordered,
        "run_count":   run_count,
    }
