"""Content calendar handler — produce N post slots across a date range.

Input: business context, date range, platforms, post frequency, themes.
Output: a list of SocialPost slots in 'draft' status — each a planned post
with topic, platform, format hint, suggested date, and notes. Captions are
left blank by design; the calendar is the *plan*, not the *copy*. The
caption() handler is what fills each slot in.

This is the "what should we post about and when" half of social. The
caption() handler is the "what does it actually say" half.
"""
from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field

from ..._shared.claude_router import llm_available, route_messages_parse
from .briefs import SocialBrief, SocialAsset, SocialPost, SocialPlatform
from ._voice import voice_guardrails_block
from ._vault_loader import build_voice_context_block


class _CalendarSlot(BaseModel):
    platform: SocialPlatform
    topic: str = Field(description=(
        "Specific post topic — not a category. Bad: 'product feature'. "
        "Good: 'how Soap Gnome's restock drops fill 200 carts in 30 min'."
    ))
    format_hint: str = Field(description=(
        "One of: 'reel', 'carousel', 'single-image', 'short-video', "
        "'text-only', 'photo+poll'."
    ))
    scheduled_for: str = Field(description=(
        "ISO-8601 date OR 'YYYY-MM-DD HH:MM' local. Pick a posting time "
        "that's strong for the platform (weekday morning for LinkedIn, "
        "evening for IG, etc.)."
    ))
    angle: str = Field(description=(
        "One-sentence framing: the hook or POV the caption should take. "
        "Used as input to caption() later."
    ))
    cta: Optional[str] = Field(default=None, description=(
        "Optional call-to-action. Most posts in a healthy calendar are "
        "NOT direct CTAs — alternate value/teach posts with offer posts."
    ))


class _Calendar(BaseModel):
    strategy_summary: str = Field(description=(
        "2-3 sentences. What's the throughline of this calendar? Which "
        "audience segments are we reaching, and which buyer journey stages?"
    ))
    slots: list[_CalendarSlot] = Field(min_length=1)


SYSTEM_PROMPT_TEMPLATE = """You are HERALD: Social Media Manager planning a content
calendar for a HogTron client (or HogTron itself).

{voice_guardrails}

VOICE CONTEXT (from vault — treat as ground truth when present):
{voice_context}

A calendar is NOT a list of random post ideas. It's a structured plan:
- Mix of post types — teach, tell, sell. Rule of thumb: 50% value/teach,
  30% story/personality, 20% offer/CTA. Adjust if the user specifies.
- Mix of platforms appropriate to where the audience actually is. Don't
  spread one identical post across 6 platforms — that's amateur hour and
  it tanks reach on every platform.
- Cadence that's sustainable. 7 posts a week sounds great until week 3.
  If you're unsure of cadence, lean lighter.
- Strong scheduling — each slot has a specific topic, format, and time.
  No "TBD". No "thought leadership post". Be concrete.

HOGTRON CONTEXT
- HogTron Solutions is an AI-amplified local-business agency. Primary
  audiences: local business owners, restaurant operators, soap/craft
  Etsy sellers (FactoryHQ), and HogTron's own founder following.
- Brand voice: confident, direct, founder-led. Hates corporate fluff.
  Loves specific numbers and named outcomes.
- Brand palette is navy/cyan/gold but you don't pick the visuals —
  FORGE does. You write *what the post is about and when it goes live*.

OUTPUT
- A short strategy summary explaining what the calendar is doing.
- A list of slots. Each slot is precise enough that the caption()
  handler can turn it into copy without any guessing."""


def content_calendar(brief: SocialBrief) -> SocialAsset:
    """Plan a content calendar across platforms.

    brief.payload:
      business_context (required) — 2-5 sentence description of the
        business or campaign this calendar serves
      platforms (required) — list of SocialPlatform values to plan for
      date_range (required) — e.g. "2026-05-13 to 2026-05-27" or "next 2 weeks"
      posts_per_week (optional, default 5)
      themes (optional) — list of themes/pillars to weave in
      audience (optional) — primary audience descriptor
      cta_mix (optional) — e.g. "30% offer posts" overrides default 20%
    brief.context:
      anthropic_api_key (optional)
      model (optional, default claude-sonnet-4-6)
    """
    biz = brief.payload.get("business_context")
    platforms = brief.payload.get("platforms")
    date_range = brief.payload.get("date_range")
    if not biz or not platforms or not date_range:
        raise ValueError(
            "content_calendar brief.payload must include 'business_context', "
            "'platforms', and 'date_range'"
        )

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not llm_available(key):
        return SocialAsset(
            kind="content_calendar",
            metadata={"error": "No LLM backend configured"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"
    posts_per_week = int(brief.payload.get("posts_per_week") or 5)
    themes = brief.payload.get("themes") or []
    audience = brief.payload.get("audience") or "unspecified"
    cta_mix = brief.payload.get("cta_mix") or "~20% offer/CTA posts, rest value/story"

    user_prompt = (
        f"Business context: {biz}\n"
        f"Platforms in scope: {', '.join(platforms)}\n"
        f"Date range: {date_range}\n"
        f"Cadence: ~{posts_per_week} posts/week per platform\n"
        f"Primary audience: {audience}\n"
        f"Themes/pillars: {themes or 'pick the strongest 3-4 from the business context'}\n"
        f"CTA mix: {cta_mix}\n\n"
        "Plan the calendar. Output strategy summary + ordered slots."
    )

    voice_context = brief.context.get("voice_context")
    if voice_context is None:
        # Don't filter to one platform — calendar spans many.
        voice_context = build_voice_context_block() or "(none in vault)"
    system = SYSTEM_PROMPT_TEMPLATE.format(
        voice_guardrails=voice_guardrails_block(),
        voice_context=voice_context,
    )

    resp = route_messages_parse(
        agent="marketing.smm.calendar",
        model=model,
        max_tokens=6000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_Calendar,
        api_key=key,
    )

    parsed: _Calendar = resp.parsed_output
    posts = [
        SocialPost(
            platform=s.platform,
            caption="",                       # filled in later by caption()
            hashtags=[],
            status="draft",
            scheduled_for=s.scheduled_for,
            topic=s.topic,
            format_hint=s.format_hint,
            notes=f"Angle: {s.angle}" + (f" | CTA: {s.cta}" if s.cta else ""),
        )
        for s in parsed.slots
    ]

    return SocialAsset(
        kind="content_calendar",
        posts=posts,
        summary=parsed.strategy_summary,
        payload={"date_range": date_range, "posts_per_week": posts_per_week},
        metadata={
            "model": model,
            "platforms": platforms,
            "n_slots": len(posts),
        },
    )
