"""Sales department — Layer 2 autonomous agent loop.

Sales' Layer 1 surface is currently 1 piloted kind (aggregator_audit_report),
so the agent loop is trivial today — it'll basically call that one tool and
summarize. The interface still matters: it's how Layer 3 (the CEO loop)
will dispatch directives uniformly across all 5 departments.

As more kinds ship (proposal, follow_up, pricing_quote, contract), they
get added to build_tools() and the agent gains real composition power.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import SalesBrief, SalesAsset
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Sales department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You receive directives for
  specific prospects and produce closing-motion deliverables: audit
  reports, proposals, pricing quotes, contracts, follow-up messages.
- You compose findings from other departments (Research audits, Creative
  mockups, Marketing copy) into prospect-facing artifacts.

YOUR TOOLS
You have 1 Layer 1 kind available as a tool today:
  - aggregator_audit_report: build a structured restaurant-aggregator
    audit deliverable given the restaurant profile + per-platform status
    (typically sourced upstream from Research.platform_presence)

OPERATING PRINCIPLES
- Be efficient: don't call tools you don't need.
- Be honest: if the input data is thin (no platform_status, missing
  restaurant fields), say so in the summary.
- The deliverable is for a SPECIFIC PROSPECT — don't generalize.

OUTPUT FORMAT
End your turn with a clear text summary:
  - What deliverable you built
  - Key numbers from it (listed count, projection, # recommendations)
  - Anything the CEO should know before sending it to the prospect"""


@dataclass
class AutonomousResult:
    directive: str
    summary: str
    tool_calls: list[dict]
    assets: list[SalesAsset]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(sales_instance) -> tuple[list[SalesAsset], list[AgentTool]]:
    assets: list[SalesAsset] = []

    def _call(kind: str, payload: dict) -> dict:
        asset = sales_instance.build(SalesBrief(
            kind=kind, payload=payload, requester="sales.autonomous",
        ))
        assets.append(asset)
        # Trim for context window
        summary = {"kind": asset.kind, "summary": asset.summary, "metadata": asset.metadata}
        # Include payload but cap recommendations list to first 5
        p = dict(asset.payload)
        if "recommendations" in p:
            p["recommendations"] = p["recommendations"][:5]
        summary["payload"] = p
        return summary

    return assets, [
        AgentTool(
            name="aggregator_audit_report",
            description=(
                "Build a restaurant aggregator audit deliverable. Returns the "
                "structured report dict (per_platform, projection, "
                "recommendations, competitive_intel, summary, meta). Cost: $0."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "restaurant": {
                        "type": "object",
                        "description": "Restaurant profile dict (name, address, city, state, zip, phone, website, cuisine)",
                    },
                    "platform_status": {
                        "type": "object",
                        "description": "Per-platform-slug dict with listed/url/rating/review_count/notes",
                    },
                    "competitor_count": {"type": "integer", "default": 12},
                    "competitors_on_aggregators": {"type": "integer", "default": 9},
                    "competitors_on_three_or_more": {"type": "integer", "default": 5},
                    "median_competitor_platform_count": {"type": "integer", "default": 3},
                    "hogtron_setup_fee": {"type": "integer", "default": 750},
                    "hogtron_monthly_optimization": {"type": "integer", "default": 199},
                    "prepared_by": {"type": "string", "default": "Sean Bilger"},
                    "prepared_for_meeting_date": {"type": "string"},
                },
                "required": ["restaurant", "platform_status"],
            },
            handler=lambda **kw: _call("aggregator_audit_report", kw),
        ),
    ]


def run_autonomous(sales_instance, directive, *, anthropic_api_key,
                   model="claude-opus-4-7", max_iterations=8,
                   progress_callback=None, should_cancel=None) -> AutonomousResult:
    assets, tools = build_tools(sales_instance)
    result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=sales_instance.telemetry, role="sales.autonomous",
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
