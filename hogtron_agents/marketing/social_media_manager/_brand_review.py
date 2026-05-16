"""Brand review handler — score a draft social post against the brand standard.

This is the quality gate that sits between SMM compose and human approval.
Run it on any SocialPost (typically one returned by caption/repurpose) to
get a 0-10 score per criterion plus concrete rewrite suggestions.

Two layers of review run here:

  1. Deterministic checks (banned terms, char limit, hashtag count) — fast,
     no LLM cost. These produce hard-coded verdict downgrades.

  2. LLM critique (voice fit, audience language, hook strength, CTA quality) —
     scored 0-10 with a one-sentence rationale and concrete rewrites.

Pattern target: a caller composes a caption, runs brand_review, and either
ships, edits, or rewrites based on the verdict. OVERSEER will eventually
gate auto-progression to status='ready_for_approval' on a minimum score.
"""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from .briefs import SocialBrief, SocialAsset, BrandReviewScore
from ._voice import (
    BANNED_TERMS, SOFT_FLAGS, PLATFORM_STRUCTURE,
    voice_guardrails_block, hook_formula_block, cta_block,
)
from ._vault_loader import build_voice_context_block


class _LLMReview(BaseModel):
    """LLM-only portion of the review. Deterministic checks merge in later."""
    voice_fit: int = Field(ge=0, le=10, description=(
        "How well the post matches the brand voice (rhythm, register, "
        "specificity vs. generic). 10 = indistinguishable from a top human "
        "post by this brand."
    ))
    audience_language: int = Field(ge=0, le=10, description=(
        "Does it use phrases the ICP actually uses (per vault audience "
        "language, when provided)? 10 = pulls verbatim phrases from the ICP."
    ))
    hook_strength: int = Field(ge=0, le=10, description=(
        "Does the first line match a named hook formula AND earn the scroll-"
        "stop? 10 = the first 60 chars are unskippable."
    ))
    cta_quality: int = Field(ge=0, le=10, description=(
        "Is there a clear, specific CTA with an action verb? "
        "10 = one specific CTA, action verb up front, low friction."
    ))
    rewrite_suggestions: list[str] = Field(min_length=0, max_length=5, description=(
        "Concrete rewrite proposals. Each entry is either a replacement line "
        "or a one-sentence directive ('cut the second paragraph — it stalls "
        "the hook'). Empty if verdict is ship_it."
    ))
    rationale: str = Field(description=(
        "One paragraph explaining the overall score in plain English. The "
        "human reviewer reads this first."
    ))


def _deterministic_checks(caption: str, platform: str, hashtags: list[str]) -> dict:
    """Run rule-based checks; return platform_fit score + hit lists."""
    caption_lc = caption.lower()
    banned_hits = [t for t in BANNED_TERMS if t.lower() in caption_lc]
    soft_hits = []
    for tok in SOFT_FLAGS:
        # word-boundary check (simple) so "really" doesn't match "realistically"
        if f" {tok} " in f" {caption_lc} " or caption_lc.startswith(tok + " "):
            soft_hits.append(tok)

    platform_fit = 10
    p_struct = PLATFORM_STRUCTURE.get(platform)
    if p_struct:
        # Char-limit penalty
        if len(caption) > p_struct["char_limit"]:
            platform_fit -= 5
        # Hashtag-count band penalty — parse "3-8" style ranges
        band = p_struct["hashtag_count"]
        # crude min/max parse
        nums = [int(s) for s in band.replace("(", " ").replace(")", " ").split() if s.isdigit()]
        n_tags = len(hashtags)
        if nums:
            lo = min(nums)
            hi = max(nums)
            if n_tags < lo:
                platform_fit -= 2
            if n_tags > hi:
                platform_fit -= 3

    platform_fit = max(0, min(10, platform_fit))

    return {
        "banned_hits": banned_hits,
        "soft_hits": soft_hits,
        "platform_fit": platform_fit,
    }


SYSTEM_PROMPT_TEMPLATE = """You are HERALD: Social Media Manager running a
BRAND REVIEW on a draft social post. Score it like a senior editor who has
written for this brand for two years.

{voice_guardrails}

{hooks}

{cta}

VOICE CONTEXT (anything below comes from the vault — treat as ground truth):
{voice_context}

SCORING RULES
- Every criterion is 0-10. 7+ means "would ship as-is on a tired Friday."
- Do NOT pad scores. A 5 should feel like a 5 — usable but unimpressive.
- "rewrite_suggestions" must be SPECIFIC. Bad: 'punch up the hook'.
  Good: 'replace line 1 with: How a 4-person crew booked 12 audits last week.'
- One rationale paragraph, plain English, for the human reviewer."""


def brand_review(brief: SocialBrief) -> SocialAsset:
    """Score a draft post against the brand standard.

    brief.payload:
      caption (required) — the draft caption text
      platform (required) — SocialPlatform
      hashtags (optional, list[str])
      topic (optional) — what the post is about (helps audience-language scoring)
    brief.context:
      anthropic_api_key (optional)
      model (optional, default claude-sonnet-4-6)
      voice_context (optional) — pre-built block; if None, loader pulls from vault
      min_overall (optional, default 7) — used by caller to gate ready_for_approval
    """
    caption = brief.payload.get("caption")
    platform = brief.payload.get("platform")
    if not caption or not platform:
        raise ValueError("brand_review brief.payload must include 'caption' and 'platform'")

    hashtags = brief.payload.get("hashtags") or []
    topic = brief.payload.get("topic") or "unspecified"

    # 1. Deterministic checks
    det = _deterministic_checks(caption, platform, hashtags)

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return SocialAsset(
            kind="brand_review",
            metadata={"error": "ANTHROPIC_API_KEY not set"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"

    voice_context = brief.context.get("voice_context")
    if voice_context is None:
        voice_context = build_voice_context_block(platform=platform) or "(none in vault)"

    system = SYSTEM_PROMPT_TEMPLATE.format(
        voice_guardrails=voice_guardrails_block(),
        hooks=hook_formula_block(),
        cta=cta_block(),
        voice_context=voice_context,
    )

    user_prompt = (
        f"Platform: {platform}\n"
        f"Topic: {topic}\n"
        f"Hashtags: {hashtags or '(none)'}\n\n"
        f"--- DRAFT CAPTION ---\n{caption}\n--- /DRAFT ---\n\n"
        f"Deterministic checks already ran:\n"
        f"  banned-term hits: {det['banned_hits'] or 'none'}\n"
        f"  soft-flag hits:   {det['soft_hits'] or 'none'}\n"
        f"  platform_fit:     {det['platform_fit']}/10\n\n"
        "Score the caption on voice_fit, audience_language, hook_strength, "
        "cta_quality. Propose concrete rewrites if score is below 8 on any "
        "criterion."
    )

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.parse(
        model=model,
        max_tokens=3000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_LLMReview,
    )

    llm: _LLMReview = resp.parsed_output

    # 2. Combine scores. Banned terms cap overall at 4 (ship-blocker).
    weighted_overall = (
        llm.voice_fit * 0.25
        + llm.audience_language * 0.15
        + llm.hook_strength * 0.25
        + llm.cta_quality * 0.15
        + det["platform_fit"] * 0.20
    )
    overall = int(round(weighted_overall))
    if det["banned_hits"]:
        overall = min(overall, 4)

    verdict: str
    if det["banned_hits"]:
        verdict = "rewrite"
    elif overall >= 8:
        verdict = "ship_it"
    elif overall >= 6:
        verdict = "minor_edits"
    elif overall >= 4:
        verdict = "rewrite"
    else:
        verdict = "reject"

    score = BrandReviewScore(
        voice_fit=llm.voice_fit,
        audience_language=llm.audience_language,
        hook_strength=llm.hook_strength,
        cta_quality=llm.cta_quality,
        platform_fit=det["platform_fit"],
        banned_term_hits=det["banned_hits"],
        soft_flag_hits=det["soft_hits"],
        overall=overall,
        verdict=verdict,  # type: ignore[arg-type]
        rewrite_suggestions=llm.rewrite_suggestions,
        rationale=llm.rationale,
    )

    return SocialAsset(
        kind="brand_review",
        posts=[],
        summary=f"{verdict.upper()} — overall {overall}/10. {llm.rationale[:140]}",
        payload=score.model_dump(),
        metadata={
            "model": model,
            "platform": platform,
            "caption_len": len(caption),
            "n_banned_hits": len(det["banned_hits"]),
        },
    )
