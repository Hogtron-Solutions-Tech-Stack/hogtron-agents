"""Creative department -- Layer 2 autonomous agent loop.

shirt + mockup are live. Same shape as other depts -- kept consistent
so Layer 3 (CEO loop) dispatches uniformly. When pdf_page / proposal_cover /
canva_asset ship as real handlers, they get added to build_tools() automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import CreativeBrief, CreativeAsset
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Creative department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You produce visual deliverables:
  POD shirt designs, PDF pages, client website mockups, proposal covers,
  Canva assets.
- Every visual you produce must pass HogTron's IP guardrails -- no
  characters, brands, lyrics, celebrities, sports teams. Generic motifs
  only.

YOUR TOOLS
You have 2 kinds available today:

  - shirt: Claude art-direct + Recraft render -> transparent PNG + art
    direction (shirt color, typography, layout, accent, palette, mood,
    Recraft prompt, placement_y). Cost: ~$0.05 Claude + ~$0.05 Recraft
    per shirt.

  - mockup: Claude plans palette/sections/copy + Claude renders a complete
    single-file HTML website mockup for a client prospect. Takes audit data
    from ORACLE, returns a local HTML file path + file URI. Use this when
    the directive mentions a client domain, business name, or audit results
    and asks for a mockup, redesign, or website preview.
    Cost: ~$0.15-0.25 Claude per mockup (two-phase: plan + render).

OPERATING PRINCIPLES
- Shirt phrases arriving here have ALREADY been cleared by Research(ip_clear).
  Do not re-vet -- trust the input.
- The art around a shirt phrase still must not introduce IP risk.
- Be efficient with Recraft credits -- only one render per phrase unless
  the directive asks for variants.
- For mockups, include as much audit context as you have -- the more
  audit_data you pass, the sharper the top_fix hook and design plan.

OUTPUT FORMAT
End your turn with a tight summary:
  - For shirts: each design produced, key art-direction attributes (color,
    typography, placement_y), any notes for the CEO.
  - For mockups: business name, file_path of the saved HTML, top_fix hook
    (the pitch line FORGE surfaced), and any design notes."""


@dataclass
class AutonomousResult:
    directive: str
    summary: str
    tool_calls: list[dict]
    assets: list[CreativeAsset]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(creative_instance) -> tuple[list[CreativeAsset], list[AgentTool]]:
    assets: list[CreativeAsset] = []

    def _call(kind: str, payload: dict, context: Optional[dict] = None) -> dict:
        asset = creative_instance.design(CreativeBrief(
            kind=kind, payload=payload, context=context or {},
            requester="creative.autonomous",
        ))
        assets.append(asset)
        ad = asset.artifacts.get("art_direction", {})
        return {
            "kind": asset.kind,
            "primary_url": asset.primary_url,
            "file_path": asset.file_path,
            "shirt_color": ad.get("shirt_color"),
            "typography_style": ad.get("typography_style"),
            "placement_y": ad.get("placement_y"),
            "mood_tags": ad.get("mood_tags"),
            "top_fix": asset.metadata.get("top_fix"),
            "html_bytes": asset.artifacts.get("html_bytes"),
            "metadata": asset.metadata,
        }

    shirt_tool = AgentTool(
        name="shirt",
        description=(
            "Generate a POD shirt design from a cleared phrase. Returns "
            "the Recraft URL + local file path + key art-direction "
            "fields (color, typography, placement_y, mood). "
            "Cost: ~$0.10 per call (Claude + Recraft)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "phrase": {
                    "type": "string",
                    "description": "The cleared shirt phrase. Must already be IP-clear.",
                },
                "audience": {
                    "type": "string",
                    "description": "Who buys this (e.g. Father's Day gift for dads)",
                },
                "saturation": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Market crowding signal from Research, if known.",
                },
            },
            "required": ["phrase"],
        },
        handler=lambda phrase, audience="", saturation="medium": _call(
            "shirt",
            {"phrase": phrase, "audience": audience, "saturation": saturation},
        ),
    )

    mockup_tool = AgentTool(
        name="mockup",
        description=(
            "Generate a complete single-file HTML website mockup for a client prospect. "
            "Claude plans the palette, sections, and copy, then renders the full HTML. "
            "Returns a local file path + file URI to the saved HTML. "
            "Use when the directive references a client domain, business name, or audit "
            "results and asks for a redesign, mockup, or website preview. "
            "Cost: ~$0.15-0.25 per call (two Claude calls: plan + render)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "business_name": {
                    "type": "string",
                    "description": "Display name of the client business.",
                },
                "url": {
                    "type": "string",
                    "description": "The client live domain, e.g. valleyhvac.com. Optional.",
                },
                "audit_data": {
                    "type": "object",
                    "description": (
                        "Audit results from ORACLE (seo_audit or geo_audit payload). "
                        "Pass overall_score, pillars, issues, gbp_status, etc."
                    ),
                },
                "address": {
                    "type": "string",
                    "description": "Physical address for footer and contact section.",
                },
                "phone": {
                    "type": "string",
                    "description": "Phone number for footer and contact section.",
                },
                "business_type": {
                    "type": "string",
                    "description": (
                        "Type of business -- drives sections and color palette. "
                        "E.g. HVAC, chiropractor, restaurant, dental practice."
                    ),
                },
            },
            "required": ["business_name"],
        },
        handler=lambda business_name, url="", audit_data=None,
                     address="", phone="", business_type="local business": _call(
            "mockup",
            {
                "business_name": business_name,
                "url": url,
                "audit_data": audit_data or {},
                "address": address,
                "phone": phone,
                "business_type": business_type,
            },
        ),
    )

    return assets, [shirt_tool, mockup_tool]


def run_autonomous(creative_instance, directive, *, anthropic_api_key,
                   model="claude-sonnet-4-6", max_iterations=6,
                   progress_callback=None, should_cancel=None) -> AutonomousResult:
    assets, tools = build_tools(creative_instance)
    result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=creative_instance.telemetry, role="creative.autonomous",
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
