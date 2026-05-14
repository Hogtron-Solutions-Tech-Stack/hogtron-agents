"""Ledger department — Layer 2 autonomous agent loop.

Internal-only. Given a directive ("refresh today's P&L", "what did we burn
on Claude this week?"), the loop chains Layer 1 kinds and summarizes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import LedgerBrief, LedgerAsset
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Ledger department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You are INTERNAL ONLY — you
  never produce client-facing content. You answer two kinds of questions:
  "what did we make?" and "what did we spend?"
- You pull from PayPal (revenue), Anthropic-via-Supabase (tokens), and
  Railway (hosting), then roll the numbers into a P&L snapshot.

YOUR TOOLS
- pull_anthropic: aggregate Claude API spend over a window
- pull_paypal: list inbound PayPal transactions (+ persist to ledger_costs)
- pull_railway: pull Railway month-to-date usage by service
- pnl_snapshot: roll up a date's ledger_costs into ledger_snapshots
- client_margin: per-client P&L from invoice payments
- ar_overview: open + overdue invoices
- threshold_check: evaluate budget thresholds and report breaches

OPERATING PRINCIPLES
- Be efficient. Don't pull data the directive doesn't ask about.
- Be honest. If a source is misconfigured (no PayPal token, no Railway
  token), say so in the summary — don't pretend the number is zero.
- All cost numbers are USD unless stated otherwise.
- You write to Supabase ledger_costs and ledger_snapshots. The dashboard
  /ledger page reads from those tables.

OUTPUT FORMAT
End your turn with a clear text summary:
  - Revenue / cost / net for the period in question
  - Notable line items (top 1-2 spend drivers, big PayPal payments)
  - Any budget threshold breaches
  - Anything the CEO should act on"""


@dataclass
class AutonomousResult:
    directive: str
    summary: str
    tool_calls: list[dict]
    assets: list[LedgerAsset]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(ledger_instance, context: dict) -> tuple[list[LedgerAsset], list[AgentTool]]:
    assets: list[LedgerAsset] = []

    def _call(kind: str, payload: dict) -> dict:
        asset = ledger_instance.build(LedgerBrief(
            kind=kind, payload=payload, context=context,
            requester="ledger.autonomous",
        ))
        assets.append(asset)
        # Trim payload for the context window — drop the heaviest fields.
        p = dict(asset.payload)
        if "transactions" in p and isinstance(p["transactions"], list):
            p["transactions"] = p["transactions"][:5]
        if "raw" in p:
            p.pop("raw", None)
        if "open" in p and isinstance(p["open"], list):
            p["open"] = p["open"][:10]
        if "clients" in p and isinstance(p["clients"], list):
            p["clients"] = p["clients"][:10]
        return {"kind": asset.kind, "summary": asset.summary,
                "payload": p, "metadata": asset.metadata}

    return assets, [
        AgentTool(
            name="pull_anthropic",
            description="Aggregate Claude API spend from ceo_runs + dept_runs "
                        "over the last N days. Writes ledger_costs rows.",
            input_schema={
                "type": "object",
                "properties": {
                    "days":    {"type": "integer", "default": 1},
                    "persist": {"type": "boolean", "default": True},
                },
            },
            handler=lambda **kw: _call("pull_anthropic", kw),
        ),
        AgentTool(
            name="pull_paypal",
            description="List inbound PayPal transactions and upsert into "
                        "ledger_costs (revenue). Requires paypal creds in context.",
            input_schema={
                "type": "object",
                "properties": {
                    "days":    {"type": "integer", "default": 30},
                    "persist": {"type": "boolean", "default": True},
                },
            },
            handler=lambda **kw: _call("pull_paypal", kw),
        ),
        AgentTool(
            name="pull_railway",
            description="Pull Railway month-to-date usage by service and upsert "
                        "into ledger_costs (hosting). Requires railway token in context.",
            input_schema={
                "type": "object",
                "properties": {
                    "persist": {"type": "boolean", "default": True},
                },
            },
            handler=lambda **kw: _call("pull_railway", kw),
        ),
        AgentTool(
            name="pnl_snapshot",
            description="Roll up a single date's ledger_costs into a ledger_snapshots row.",
            input_schema={
                "type": "object",
                "properties": {
                    "date":  {"type": "string", "description": "ISO date YYYY-MM-DD (default today UTC)"},
                    "notes": {"type": "string"},
                },
            },
            handler=lambda **kw: _call("pnl_snapshot", kw),
        ),
        AgentTool(
            name="ar_overview",
            description="List open + overdue invoices with balances.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda **kw: _call("ar_overview", kw),
        ),
        AgentTool(
            name="client_margin",
            description="Per-client P&L from invoice history.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda **kw: _call("client_margin", kw),
        ),
        AgentTool(
            name="threshold_check",
            description="Evaluate ledger_thresholds; report any breaches.",
            input_schema={"type": "object", "properties": {}},
            handler=lambda **kw: _call("threshold_check", kw),
        ),
    ]


def run_autonomous(ledger_instance, directive, *, anthropic_api_key,
                   context: dict,
                   model="claude-sonnet-4-6", max_iterations=6,
                   progress_callback=None, should_cancel=None) -> AutonomousResult:
    assets, tools = build_tools(ledger_instance, context)
    result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=ledger_instance.telemetry, role="ledger.autonomous",
        progress_callback=progress_callback, should_cancel=should_cancel,
    )
    return AutonomousResult(
        directive=directive, summary=result.final_message,
        tool_calls=[{"tool": tc.tool, "input": tc.input,
                     "elapsed_sec": tc.elapsed_sec, "error": tc.error}
                    for tc in result.tool_calls],
        assets=assets, success=result.success,
        iterations=result.iterations, duration_sec=result.duration_sec,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        cost_usd=estimate_cost_usd(model, result.input_tokens, result.output_tokens),
        stop_reason=result.stop_reason, error=result.error,
    )
