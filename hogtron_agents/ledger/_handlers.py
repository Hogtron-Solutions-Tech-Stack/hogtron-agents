"""Layer 1 handlers — pure-data Ledger operations.

Each handler accepts a LedgerBrief and returns a LedgerAsset. No LLM calls
here; the autonomous loop in `_autonomous.py` chains these via Claude.

A Supabase client (and optional source credentials) are passed in via the
LedgerBrief.context dict so this package doesn't depend on a specific db-
init module. The caller (dashboard, FactoryHQ, or cron) wires:

    context = {
        "supabase":     <supabase client>,
        "paypal":       {"client_id": ..., "secret": ..., "mode": "live"},
        "railway":      {"token": ..., "team_id": None},
    }
"""
from __future__ import annotations

from datetime import datetime, timezone, date
from typing import Any

from .briefs import LedgerBrief, LedgerAsset
from .tools import paypal, anthropic_spend, railway


# --------------------------------------------------------------------------- #
# pull_anthropic — token spend aggregation
# --------------------------------------------------------------------------- #
def pull_anthropic(brief: LedgerBrief) -> LedgerAsset:
    sb = _require_supabase(brief)
    days = int(brief.payload.get("days", 1))
    agg = anthropic_spend.aggregate_spend(sb, days=days)

    write = bool(brief.payload.get("persist", True))
    inserted = 0
    if write and agg["total_usd"] > 0:
        rows = []
        for entry in agg["by_day"]:
            if entry["cost"] <= 0:
                continue
            rows.append({
                "occurred_on": entry["date"],
                "source":      "anthropic",
                "category":    "tokens",
                "line_item":   f"Claude API spend ({entry['date']})",
                "amount_usd":  entry["cost"],
                "external_id": f"anthropic-{entry['date']}",
                "metadata":    {"by_dept": agg["by_dept"], "by_model": agg["by_model"]},
            })
        if rows:
            try:
                sb.table("ledger_costs").upsert(
                    rows, on_conflict="source,external_id"
                ).execute()
                inserted = len(rows)
            except Exception as e:  # noqa: BLE001
                # Upsert may fail on first run if the unique index is fresh;
                # surface the error in metadata instead of crashing.
                agg["_persist_error"] = str(e)

    summary = (
        f"Claude spend last {days}d: ${agg['total_usd']:.2f} "
        f"across {agg['run_count']} runs"
        + (f" · {inserted} ledger_costs rows upserted" if inserted else "")
    )
    return LedgerAsset(
        kind="pull_anthropic",
        summary=summary,
        payload=agg,
        metadata={"inserted": inserted, "days": days},
    )


# --------------------------------------------------------------------------- #
# pull_paypal — inbound transactions
# --------------------------------------------------------------------------- #
def pull_paypal(brief: LedgerBrief) -> LedgerAsset:
    sb = _require_supabase(brief)
    creds = (brief.context or {}).get("paypal") or {}
    cid    = creds.get("client_id")
    secret = creds.get("secret")
    mode   = creds.get("mode", "live")
    if not (cid and secret):
        raise ValueError(
            "pull_paypal needs context.paypal.client_id + secret. "
            "Wire them from the caller's config."
        )
    days = int(brief.payload.get("days", 30))
    txns = paypal.list_transactions(cid, secret, mode=mode, days=days)
    total = paypal.total_inbound(txns)

    write = bool(brief.payload.get("persist", True))
    inserted = 0
    if write and txns:
        rows = []
        for t in txns:
            paid_at = t.get("paid_at") or ""
            day = paid_at[:10] if paid_at else date.today().isoformat()
            rows.append({
                "occurred_on": day,
                "source":      "paypal",
                "category":    "revenue",
                "line_item":   (t.get("note") or t.get("payer_name") or "PayPal payment")[:240],
                "amount_usd":  float(t["amount"]),
                "external_id": t.get("txn_id"),
                "metadata":    {"payer_email": t.get("payer_email"),
                                "payer_name":  t.get("payer_name"),
                                "currency":    t.get("currency"),
                                "status":      t.get("status")},
            })
        try:
            sb.table("ledger_costs").upsert(
                rows, on_conflict="source,external_id"
            ).execute()
            inserted = len(rows)
        except Exception as e:  # noqa: BLE001
            return LedgerAsset(
                kind="pull_paypal",
                summary=f"PayPal pull failed: {e}",
                payload={"transactions": txns, "total_usd": total, "days": days},
                metadata={"error": str(e)},
            )

    return LedgerAsset(
        kind="pull_paypal",
        summary=f"PayPal: {len(txns)} txn(s), ${total:,.2f} inbound over {days}d "
                f"({inserted} upserted)",
        payload={"transactions": txns, "total_usd": total, "days": days,
                 "new_count": inserted},
        metadata={"inserted": inserted, "days": days},
    )


# --------------------------------------------------------------------------- #
# pull_railway — hosting cost month-to-date
# --------------------------------------------------------------------------- #
def pull_railway(brief: LedgerBrief) -> LedgerAsset:
    sb = _require_supabase(brief)
    creds = (brief.context or {}).get("railway") or {}
    token = creds.get("token")
    team  = creds.get("team_id")
    if not token:
        raise ValueError(
            "pull_railway needs context.railway.token. "
            "Wire RAILWAY_TOKEN from the caller's config."
        )
    usage = railway.month_to_date_usage(token, team_id=team)

    write = bool(brief.payload.get("persist", True))
    inserted = 0
    if write and usage["total_usd"] > 0:
        today = date.today().isoformat()
        period = usage["period"]
        rows = []
        for svc in usage["by_service"]:
            if svc["usd"] <= 0:
                continue
            rows.append({
                "occurred_on": today,
                "source":      "railway",
                "category":    "hosting",
                "line_item":   f"Railway · {svc.get('service_name') or svc.get('service_id') or 'unknown'} ({period})",
                "amount_usd":  svc["usd"],
                "external_id": f"railway-{period}-{svc.get('service_id') or 'all'}",
                "metadata":    {"project_id": svc.get("project_id"),
                                "service_id": svc.get("service_id"),
                                "period":     period},
            })
        if rows:
            try:
                sb.table("ledger_costs").upsert(
                    rows, on_conflict="source,external_id"
                ).execute()
                inserted = len(rows)
            except Exception as e:  # noqa: BLE001
                usage["_persist_error"] = str(e)

    return LedgerAsset(
        kind="pull_railway",
        summary=f"Railway MTD: ${usage['total_usd']:.2f} across "
                f"{len(usage['by_service'])} service(s)",
        payload=usage,
        metadata={"inserted": inserted},
    )


# --------------------------------------------------------------------------- #
# pnl_snapshot — daily roll-up
# --------------------------------------------------------------------------- #
def pnl_snapshot(brief: LedgerBrief) -> LedgerAsset:
    """Compute (and upsert) a daily P&L row from ledger_costs.

    payload.date — ISO date string, defaults to today (UTC).
    payload.notes — optional human note attached to the snapshot row.
    """
    sb = _require_supabase(brief)
    snap_date = brief.payload.get("date") or date.today().isoformat()
    notes = brief.payload.get("notes")

    rows = (sb.table("ledger_costs")
            .select("source, category, amount_usd")
            .eq("occurred_on", snap_date).execute().data) or []

    totals = {"revenue": 0.0, "tokens": 0.0, "hosting": 0.0,
              "tools": 0.0, "other": 0.0}
    sources_seen: set[str] = set()
    for r in rows:
        cat = (r.get("category") or "other").lower()
        amt = float(r.get("amount_usd") or 0)
        if cat in totals:
            totals[cat] += amt
        else:
            totals["other"] += amt
        if r.get("source"):
            sources_seen.add(r["source"])

    snap = {
        "snapshot_date":    snap_date,
        "revenue_usd":      round(totals["revenue"], 2),
        "cost_tokens_usd":  round(totals["tokens"], 4),
        "cost_hosting_usd": round(totals["hosting"], 4),
        "cost_tools_usd":   round(totals["tools"], 4),
        "cost_other_usd":   round(totals["other"], 4),
        "notes":            notes,
        "source":           "ledger_agent",
    }
    row_id = None
    try:
        res = sb.table("ledger_snapshots").upsert(
            snap, on_conflict="snapshot_date"
        ).execute()
        row_id = (res.data or [{}])[0].get("id")
    except Exception as e:  # noqa: BLE001
        snap["_persist_error"] = str(e)

    net = (snap["revenue_usd"] - snap["cost_tokens_usd"]
           - snap["cost_hosting_usd"] - snap["cost_tools_usd"]
           - snap["cost_other_usd"])
    summary = (
        f"P&L {snap_date}: revenue ${snap['revenue_usd']:.2f}, "
        f"cost ${snap['cost_tokens_usd'] + snap['cost_hosting_usd'] + snap['cost_tools_usd'] + snap['cost_other_usd']:.2f}, "
        f"net ${net:.2f}"
    )
    return LedgerAsset(
        kind="pnl_snapshot",
        summary=summary,
        payload={"date": snap_date, **snap, "net_usd": round(net, 2),
                 "sources": sorted(sources_seen)},
        metadata={"row_id": row_id, "row_count": len(rows)},
    )


# --------------------------------------------------------------------------- #
# ar_overview — open / overdue invoices
# --------------------------------------------------------------------------- #
def ar_overview(brief: LedgerBrief) -> LedgerAsset:
    sb = _require_supabase(brief)
    invs = (sb.table("invoices")
            .select("id, invoice_number, total, status, issue_date, due_date, "
                    "lead_id, leads(business_name), payments(amount, paid_at)")
            .neq("status", "void")
            .order("issue_date", desc=True).execute().data) or []

    today = date.today().isoformat()
    open_invs = []
    overdue = []
    total_open = 0.0
    total_overdue = 0.0
    for inv in invs:
        if inv.get("status") == "paid":
            continue
        inv_total = float(inv.get("total") or 0)
        paid = sum(float(p.get("amount") or 0)
                   for p in (inv.get("payments") or []))
        balance = round(inv_total - paid, 2)
        if balance <= 0:
            continue
        row = {
            "id":             inv.get("id"),
            "invoice_number": inv.get("invoice_number"),
            "business_name":  (inv.get("leads") or {}).get("business_name") or "(unknown)",
            "status":         inv.get("status"),
            "issue_date":     inv.get("issue_date"),
            "due_date":       inv.get("due_date"),
            "total":          inv_total,
            "paid":           round(paid, 2),
            "balance":        balance,
        }
        total_open += balance
        open_invs.append(row)
        due = inv.get("due_date")
        if due and due < today:
            total_overdue += balance
            overdue.append(row)

    return LedgerAsset(
        kind="ar_overview",
        summary=f"AR: {len(open_invs)} open (${total_open:,.2f}) · "
                f"{len(overdue)} overdue (${total_overdue:,.2f})",
        payload={
            "open":          open_invs,
            "overdue":       overdue,
            "totals": {"open_usd":    round(total_open, 2),
                       "overdue_usd": round(total_overdue, 2)},
        },
        metadata={"open_count": len(open_invs), "overdue_count": len(overdue)},
    )


# --------------------------------------------------------------------------- #
# client_margin — per-client P&L
# --------------------------------------------------------------------------- #
def client_margin(brief: LedgerBrief) -> LedgerAsset:
    """Per-client P&L. Revenue is invoice payments; cost is attributable
    Claude spend (Sales/Research/Creative dept_runs that referenced the
    client by lead_id, when available). Attribution is best-effort —
    dept_runs doesn't carry lead_id today, so unattributed cost is reported
    separately rather than spread across clients heuristically.
    """
    sb = _require_supabase(brief)

    invs = (sb.table("invoices")
            .select("total, status, lead_id, leads(business_name), "
                    "payments(amount)")
            .neq("status", "void").execute().data) or []

    by_client: dict[str, dict[str, Any]] = {}
    for inv in invs:
        lead = inv.get("leads") or {}
        name = lead.get("business_name") or "(unknown)"
        bucket = by_client.setdefault(name, {
            "name": name, "invoiced": 0.0, "paid": 0.0, "balance": 0.0,
        })
        total = float(inv.get("total") or 0)
        paid = sum(float(p.get("amount") or 0)
                   for p in (inv.get("payments") or []))
        bucket["invoiced"] += total
        bucket["paid"]     += paid
        bucket["balance"]  += (total - paid)

    clients = []
    for b in by_client.values():
        clients.append({
            "name":     b["name"],
            "invoiced": round(b["invoiced"], 2),
            "paid":     round(b["paid"], 2),
            "balance":  round(b["balance"], 2),
            "attributable_cost_usd": 0.0,  # placeholder until lead_id is on dept_runs
            "margin_pct": 100.0 if b["paid"] > 0 else 0.0,
        })
    clients.sort(key=lambda c: c["paid"], reverse=True)

    return LedgerAsset(
        kind="client_margin",
        summary=f"Margin: {len(clients)} client(s) with invoice history",
        payload={"clients": clients, "note": "Attributable cost = 0 today "
                 "(dept_runs.lead_id not yet wired). Treat margin as gross."},
        metadata={"client_count": len(clients)},
    )


# --------------------------------------------------------------------------- #
# threshold_check — Phase 2 cost watchdog (stub today)
# --------------------------------------------------------------------------- #
def threshold_check(brief: LedgerBrief) -> LedgerAsset:
    """Evaluate ledger_thresholds against current ledger_costs.

    Returns the breach list; the caller decides whether to fire Slack.
    Phase 2 wires this to a cron + Slack notifier.
    """
    sb = _require_supabase(brief)
    rules = (sb.table("ledger_thresholds")
             .select("*").eq("active", True).execute().data) or []

    today = date.today()
    breached = []
    healthy = []
    for rule in rules:
        period = rule.get("period") or "day"
        cutoff = _period_cutoff(today, period)
        q = (sb.table("ledger_costs")
             .select("amount_usd, source, category")
             .gte("occurred_on", cutoff.isoformat()))
        if rule.get("source") and rule["source"] != "all":
            q = q.eq("source", rule["source"])
        rows = q.execute().data or []
        actual = sum(float(r.get("amount_usd") or 0) for r in rows
                     if r.get("category") != "revenue")
        entry = {
            "source":      rule.get("source"),
            "period":      period,
            "actual_usd":  round(actual, 2),
            "limit_usd":   float(rule.get("limit_usd") or 0),
            "channel":     rule.get("alert_channel"),
            "notes":       rule.get("notes"),
        }
        if actual > float(rule.get("limit_usd") or 0):
            entry["severity"] = "breached"
            breached.append(entry)
        else:
            healthy.append(entry)

    return LedgerAsset(
        kind="threshold_check",
        summary=f"Thresholds: {len(breached)} breached, {len(healthy)} healthy",
        payload={"breached": breached, "healthy": healthy},
        metadata={"breach_count": len(breached)},
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _require_supabase(brief: LedgerBrief):
    sb = (brief.context or {}).get("supabase")
    if sb is None:
        raise ValueError(
            "LedgerBrief.context must include a 'supabase' client. "
            "Caller wires db.client() from the dashboard or FactoryHQ."
        )
    return sb


def _period_cutoff(today: date, period: str) -> date:
    if period == "month":
        return today.replace(day=1)
    if period == "week":
        from datetime import timedelta
        return today - timedelta(days=today.weekday())
    return today  # day
