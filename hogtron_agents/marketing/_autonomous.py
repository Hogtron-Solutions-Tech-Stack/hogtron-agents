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


SYSTEM_PROMPT = """You are HERALD, the Marketing department of HogTron Solutions.

YOUR ROLE
- You report to the CEOs (Sean + Anthony). You produce broadcast content:
  Etsy listings, Pinterest pin copy, social posts across platforms,
  content calendars, repurposing, hashtag packs, and brand reviews.
- You produce *the words*; Operations (ANVIL) puts them on the platforms.

YOUR TOOLS

Factory / commerce (legacy):
  - etsy_listing: Etsy title (<=140) + description (>=200) + 8-13 tags. ~$0.05.
  - social_post:  Pinterest pin title/description/alt_text. ~$0.03.

Social Media Manager (HERALD specialist subpackage):
  - caption:           Multi-platform caption variants with named hook formulas
                       (surprising_stat, contrarian, question, scenario, etc.).
                       Each variant uses a DIFFERENT hook formula. ~$0.05.
  - content_calendar:  N-day calendar of post slots across platforms with
                       topic + format + scheduled_for + angle. ~$0.10-0.15.
  - repurpose:         Turn a source asset (blog, review, photo, FAQ, offer,
                       case_study) into a fan-out of platform-native posts.
                       ~$0.08-0.12.
  - hashtag_pack:      Tiered (broad / niche / local) hashtag bundles +
                       SEO keyword phrases for a topic and platform. ~$0.03.
  - brand_review:      Score a draft caption against voice / audience /
                       hook / CTA / platform-fit. Returns 0-10 + concrete
                       rewrite suggestions. Deterministic banned-term hit
                       caps overall score at 4 (ship-blocker). ~$0.04.

SUPPORTED PLATFORMS (for caption / repurpose / hashtag_pack / brand_review):
  instagram, facebook, linkedin, x, tiktok, pinterest, youtube_community

OPERATING PRINCIPLES
- Listing copy is keyword-driven (front-load high-volume terms).
  Social captions match the platform's native register — LinkedIn reads
  differently from TikTok. Don't translate one to the other.
- For Factory designs, BOTH listing copy AND pin copy are usually wanted
  on the same phrase — Pinterest is the #1 organic traffic source to
  Etsy. If a directive mentions a published design, produce both unless
  asked for only one.
- For social campaigns: plan with content_calendar before writing individual
  captions; run brand_review on any draft before flagging it as ready.
- Don't re-write phrasing the user provided; just package it well.
- Never publish — your output is always a draft. ANVIL publishes after
  human approval.

OUTPUT FORMAT
End your turn with a summary that includes:
  - What was produced (1 listing? 3 LinkedIn variants? a 14-day calendar?)
  - The hook formula(s) used (so the CEO can sanity-check angle variety)
  - Anything that might block downstream Operations (ambiguous audience,
    missing graphic for a needs_graphic post, brand_review verdict)"""


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
        # ---- HERALD: Social Media Manager tools --------------------------
        AgentTool(
            name="caption",
            description=(
                "Write 1-4 platform-native caption variants for one post. "
                "Each variant uses a DIFFERENT named hook formula. Returns "
                "{posts: [{platform, caption, hashtags, notes, ...}]} via the "
                "Marketing dispatcher. Cost: ~$0.05."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": [
                        "instagram", "facebook", "linkedin", "x", "tiktok",
                        "pinterest", "youtube_community",
                    ]},
                    "topic": {"type": "string"},
                    "angle": {"type": "string"},
                    "audience": {"type": "string"},
                    "cta": {"type": "string"},
                    "n_variants": {"type": "integer", "minimum": 1, "maximum": 4},
                    "hook_formulas": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Subset of hook formulas to constrain variants to.",
                    },
                    "include_graphic_request": {"type": "boolean"},
                },
                "required": ["platform", "topic"],
            },
            handler=lambda platform, topic, angle="", audience="", cta="",
                           n_variants=3, hook_formulas=None,
                           include_graphic_request=False: _call(
                "caption",
                {"platform": platform, "topic": topic, "angle": angle,
                 "audience": audience, "cta": cta, "n_variants": n_variants,
                 "hook_formulas": hook_formulas or None,
                 "include_graphic_request": include_graphic_request},
            ),
        ),
        AgentTool(
            name="content_calendar",
            description=(
                "Plan an N-day content calendar across platforms. Returns "
                "{posts: [N draft slots with topic/format/scheduled_for/angle], "
                "summary: strategy rationale}. Cost: ~$0.10-0.15."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "business_context": {"type": "string"},
                    "platforms": {"type": "array", "items": {"type": "string"}},
                    "date_range": {"type": "string"},
                    "posts_per_week": {"type": "integer"},
                    "themes": {"type": "array", "items": {"type": "string"}},
                    "audience": {"type": "string"},
                    "cta_mix": {"type": "string"},
                },
                "required": ["business_context", "platforms", "date_range"],
            },
            handler=lambda business_context, platforms, date_range,
                           posts_per_week=5, themes=None, audience="",
                           cta_mix="": _call(
                "content_calendar",
                {"business_context": business_context, "platforms": platforms,
                 "date_range": date_range, "posts_per_week": posts_per_week,
                 "themes": themes or [], "audience": audience, "cta_mix": cta_mix},
            ),
        ),
        AgentTool(
            name="repurpose",
            description=(
                "Fan out one source asset into platform-native posts. Source "
                "kinds: blog_post, review, photo, offer, faq, case_study, "
                "raw_note. Returns up to max_posts posts across requested "
                "platforms. Cost: ~$0.08-0.12."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "source_kind": {"type": "string", "enum": [
                        "blog_post", "review", "photo", "offer", "faq",
                        "case_study", "raw_note",
                    ]},
                    "source_text": {"type": "string"},
                    "platforms": {"type": "array", "items": {"type": "string"}},
                    "audience": {"type": "string"},
                    "max_posts": {"type": "integer"},
                },
                "required": ["source_kind", "source_text", "platforms"],
            },
            handler=lambda source_kind, source_text, platforms,
                           audience="", max_posts=8: _call(
                "repurpose",
                {"source_kind": source_kind, "source_text": source_text,
                 "platforms": platforms, "audience": audience,
                 "max_posts": max_posts},
            ),
        ),
        AgentTool(
            name="hashtag_pack",
            description=(
                "Build a tiered hashtag pack (broad / niche / local) plus "
                "keyword phrases for a topic on one platform. Returns "
                "{broad, niche, local, keyword_phrases}. Cost: ~$0.03."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "platform": {"type": "string"},
                    "locale": {"type": "string"},
                    "audience": {"type": "string"},
                },
                "required": ["topic", "platform"],
            },
            handler=lambda topic, platform, locale="", audience="": _call(
                "hashtag_pack",
                {"topic": topic, "platform": platform,
                 "locale": locale, "audience": audience},
            ),
        ),
        AgentTool(
            name="brand_review",
            description=(
                "Score a draft caption against voice / audience / hook / "
                "CTA / platform-fit. Returns overall 0-10 + verdict "
                "(ship_it / minor_edits / rewrite / reject) + rewrite "
                "suggestions. Banned-term hit caps overall at 4. Cost: ~$0.04."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "caption": {"type": "string"},
                    "platform": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "topic": {"type": "string"},
                },
                "required": ["caption", "platform"],
            },
            handler=lambda caption, platform, hashtags=None, topic="": _call(
                "brand_review",
                {"caption": caption, "platform": platform,
                 "hashtags": hashtags or [], "topic": topic},
            ),
        ),
    ]


def run_autonomous(marketing_instance, directive, *, anthropic_api_key,
                   model="claude-sonnet-4-6", max_iterations=8,
                   progress_callback=None, should_cancel=None) -> AutonomousResult:
    assets, tools = build_tools(marketing_instance)
    result = run_agent_loop(
        system=SYSTEM_PROMPT, user_message=directive, tools=tools,
        api_key=anthropic_api_key, model=model, max_iterations=max_iterations,
        telemetry=marketing_instance.telemetry, role="marketing.autonomous",
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
