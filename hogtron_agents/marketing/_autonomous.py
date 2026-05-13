"""Marketing department — Layer 2 autonomous agent loop.

Two piloted kinds today: etsy_listing + social_post. The natural workflow
is "given a phrase + audience, produce both" — Etsy listing copy for the
Printify product AND Pinterest pin copy for cross-posting after publish.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .briefs import MarketingBrief, MarketingAsset
from .._shared.agent_loop import (
    AgentResult, AgentTool, run_agent_loop, estimate_cost_usd,
)


SYSTEM_PROMPT = """You are the Marketing department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You produce broadcast content:
  Etsy listings, Pinterest pin copy, eventually social posts and blogs
  and review responses.
- You produce *the words*; Operations puts them on the platforms.

YOUR TOOLS
You have 2 Layer 1 kinds available today:
  - etsy_listing: Claude writes a title (<=140), description (>=200), and
    8-13 tags optimized for Etsy search + conversion. Cost: ~$0.05/call.
  - social_post: Claude writes Pinterest-optimized pin title (<=100),
    description (<=500 with hashtags), and alt text. Cost: ~$0.03/call.

OPERATING PRINCIPLES
- Listing copy is keyword-driven (front-load high-volume terms).
  Pinterest copy is also keyword-driven but uses hashtags + matches
  user search-intent phrasing.
- For Factory designs, BOTH listing copy AND pin copy are usually wanted
  on the same phrase — Pinterest is the #1 organic traffic source to
  Etsy. If a directive mentions a published design or a phrase that's
  going live, produce both unless asked for only one.
- Don't re-write phrasing that the user provided; just package it well.

OUTPUT FORMAT
End your turn with a summary that includes:
  - What was produced (1 listing? 1 listing + 1 pin? a batch?)
  - The title(s) you generated (so the CEO can sanity-check)
  - Anything that might block downstream Operations (e.g. ambiguous audience)"""


@dataclass
class AutonomousResult:
    directive: str
    summary: str
    tool_calls: list[dict]
    assets: list[MarketingAsset]
    success: bool
    iterations: int
    duration_sec: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    stop_reason: str
    error: Optional[str] = None


def build_tools(marketing_instance) -> tuple[list[MarketingAsset], list[AgentTool]]:
    assets: list[MarketingAsset] = []

    def _call(kind: str, payload: dict, context: Optional[dict] = None) -> dict:
        asset = marketing_instance.write(MarketingBrief(
            kind=kind, payload=payload, context=context or {},
            requester="marketing.autonomous",
        ))
        assets.append(asset)
        return {
            "kind": asset.kind, "primary_text": asset.primary_text,
            "payload": asset.payload, "metadata": asset.metadata,
        }

    return assets, [
        AgentTool(
            name="etsy_listing",
            description=(
                "Write Etsy-optimized listing copy for a shirt: title <=140 "
                "chars, description >=200 chars, 8-13 tags each <=20 chars. "
                "Returns {title, description, tags, seo_rationale}. Cost: ~$0.05."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "concept": {"type": "string"},
                    "audience": {"type": "string"},
                    "saturation": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": ["phrase"],
            },
            handler=lambda phrase, concept="", audience="", saturation="medium": _call(
                "etsy_listing",
                {"phrase": phrase, "concept": concept,
                 "audience": audience, "saturation": saturation},
            ),
        ),
        AgentTool(
            name="social_post",
            description=(
                "Write Pinterest-optimized pin copy: title <=100, description "
                "<=500 with hashtags, alt text <=200. Returns "
                "{title, description, alt_text, platform}. Cost: ~$0.03."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "concept": {"type": "string"},
                    "audience": {"type": "string"},
                    "platform": {"type": "string", "enum": ["pinterest"], "default": "pinterest"},
                },
                "required": ["phrase"],
            },
            handler=lambda phrase, concept="", audience="", platform="pinterest": _call(
                "social_post",
                {"phrase": phrase, "concept": concept,
                 "audience": audience, "platform": platform},
            ),
        ),
    ]


def run_autonomous(marketing_instance, directive, *, anthropic_api_key,
                   model="claude-opus-4-7", max_iterations=8) -> AutonomousResult:
    assets, tools = build_tools(marketing_instance)
    result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=marketing_instance.telemetry, role="marketing.autonomous",
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
