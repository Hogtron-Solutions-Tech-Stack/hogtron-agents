"""Caption handler — Claude writes platform-specific caption variants.

v2: pulls platform structure + hook formulas + voice guardrails from the
shared _voice module, and the live brand-voice / audience-language /
proven-hook context from the Obsidian vault loader. Each variant is forced
to use a DIFFERENT named hook formula, not just a different paraphrase —
so the reviewer is comparing real angles, not synonyms.
"""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from .briefs import SocialBrief, SocialAsset, SocialPost, SocialPlatform
from ._voice import (
    HOOK_FORMULAS, PLATFORM_STRUCTURE,
    voice_guardrails_block, hook_formula_block, platform_block, cta_block,
)
from ._vault_loader import build_voice_context_block


class _CaptionVariant(BaseModel):
    hook_formula: str = Field(description=(
        "Name of the hook formula used for this variant. Must be one of the "
        "names listed in HOOK FORMULAS — pick a different one for each "
        "variant so the reviewer is comparing real angles."
    ))
    caption: str = Field(description=(
        "The caption body. Respect platform character limit. First line "
        "executes the named hook formula. Use platform-appropriate line "
        "breaks. Hashtags inline at end if platform expects them there."
    ))
    hashtags: list[str] = Field(description=(
        "Lowercase, no leading '#'. Count must match platform conventions."
    ))
    format_hint: str = Field(description=(
        "One of: 'reel', 'carousel', 'single-image', 'short-video', "
        "'text-only', 'photo+poll'."
    ))
    rationale: str = Field(description=(
        "One sentence: why THIS hook formula for THIS audience on THIS platform."
    ))


class _CaptionSet(BaseModel):
    variants: list[_CaptionVariant] = Field(
        min_length=1, max_length=4,
        description=(
            "Distinct caption variants. Each variant MUST use a different "
            "hook_formula — no two variants share a formula."
        ),
    )


SYSTEM_PROMPT_TEMPLATE = """You are HERALD: Social Media Manager — HogTron's
social-media specialist inside the Marketing department.

You produce drafts. A human reviews them. Approved drafts go to ANVIL for
publishing. You never publish.

{voice_guardrails}

{platform}

{hooks}

{cta}

VOICE CONTEXT (from the Obsidian vault — treat as ground truth when present):
{voice_context}

OUTPUT REQUIREMENTS
- Each variant uses a DIFFERENT named hook_formula. No two variants share one.
- First 60 chars of every caption must execute the named hook formula —
  if reviewer can't recognize the pattern, you picked the wrong formula.
- Hashtag count and emoji policy MUST match the PLATFORM block above.
- One specific CTA per variant. Action verb up front.
- The rationale field tells the human WHY this formula × this audience."""


def caption(brief: SocialBrief) -> SocialAsset:
    """Generate caption variants for a single post on a specific platform.

    brief.payload:
      platform (required) — one of SocialPlatform
      topic (required) — what the post is about
      angle (optional) — desired angle/framing
      audience (optional) — who this is for
      cta (optional) — the call to action
      n_variants (optional, default 3, max 4)
      hook_formulas (optional) — list of formula names to constrain choice
        (default: any of HOOK_FORMULAS). Useful when you want
        ["question", "contrarian", "story_opening"] only.
      include_graphic_request (optional, default False)
    brief.context:
      anthropic_api_key (optional, falls back to env)
      model (optional, default claude-sonnet-4-6)
      voice_context (optional) — pre-built block; if None, vault loader runs
    """
    platform: Optional[SocialPlatform] = brief.payload.get("platform")
    topic = brief.payload.get("topic")
    if not platform or not topic:
        raise ValueError("caption brief.payload must include 'platform' and 'topic'")
    if platform not in PLATFORM_STRUCTURE:
        return SocialAsset(
            kind="caption",
            metadata={"error": f"unsupported platform: {platform!r}"},
        )

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return SocialAsset(kind="caption", metadata={"error": "ANTHROPIC_API_KEY not set"})
    model = brief.context.get("model") or "claude-sonnet-4-6"

    n_variants = int(brief.payload.get("n_variants") or 3)
    n_variants = max(1, min(4, n_variants))
    char_limit = PLATFORM_STRUCTURE[platform]["char_limit"]

    # Caller can constrain to a subset of hook formulas.
    hook_subset: list[str] = brief.payload.get("hook_formulas") or list(HOOK_FORMULAS.keys())
    hook_subset = [h for h in hook_subset if h in HOOK_FORMULAS]

    voice_context = brief.context.get("voice_context")
    if voice_context is None:
        voice_context = build_voice_context_block(platform=platform) or "(none in vault)"

    system = SYSTEM_PROMPT_TEMPLATE.format(
        voice_guardrails=voice_guardrails_block(),
        platform=platform_block(platform),
        hooks=hook_formula_block(hook_subset),
        cta=cta_block(),
        voice_context=voice_context,
    )

    user_prompt = (
        f"Topic: {topic}\n"
        f"Angle: {brief.payload.get('angle') or 'pick the strongest one'}\n"
        f"Audience: {brief.payload.get('audience') or 'HogTron general following'}\n"
        f"CTA: {brief.payload.get('cta') or 'soft — drive curiosity to profile'}\n"
        f"Hook formulas allowed: {', '.join(hook_subset)}\n\n"
        f"Write {n_variants} distinct caption variants. Each variant must use a "
        f"different hook_formula from the list above."
    )

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.parse(
        model=model,
        max_tokens=3500,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_CaptionSet,
    )

    parsed: _CaptionSet = resp.parsed_output
    include_graphic = bool(brief.payload.get("include_graphic_request"))

    # Enforce hook-formula uniqueness across variants — if Claude duplicated,
    # drop dupes and tell the caller via metadata. (Better than silently
    # shipping near-paraphrases.)
    seen: set[str] = set()
    deduped: list[_CaptionVariant] = []
    dupe_skipped = 0
    for v in parsed.variants:
        if v.hook_formula in seen:
            dupe_skipped += 1
            continue
        seen.add(v.hook_formula)
        deduped.append(v)

    posts: list[SocialPost] = []
    for v in deduped:
        graphic_req = None
        if include_graphic:
            from .briefs import GraphicRequest
            graphic_req = GraphicRequest(
                concept=f"{platform} post on '{topic}' — hook: {v.hook_formula}",
                aspect_ratio=_aspect_for(platform, v.format_hint),
                style_notes="HogTron navy/cyan/gold, clean, modern, brand-consistent",
            )

        caption_text = v.caption[:char_limit]
        clean_tags = [t.lstrip("#").strip().lower() for t in v.hashtags if t.strip()]

        posts.append(SocialPost(
            platform=platform,
            caption=caption_text,
            hashtags=clean_tags,
            topic=topic,
            format_hint=v.format_hint,
            status="needs_graphic" if include_graphic else "draft",
            graphic_request=graphic_req,
            notes=f"[{v.hook_formula}] {v.rationale}",
        ))

    return SocialAsset(
        kind="caption",
        posts=posts,
        summary=f"{len(posts)} caption variants for {platform} on '{topic}'",
        metadata={
            "model": model,
            "platform": platform,
            "topic": topic,
            "n_variants": len(posts),
            "hook_formulas_used": [p.notes.split("]")[0].strip("[") for p in posts if p.notes],
            "duplicate_formulas_skipped": dupe_skipped,
        },
    )


def _aspect_for(platform: str, format_hint: str) -> str:
    """Sensible default aspect ratios per platform/format."""
    if format_hint in ("reel", "short-video"):
        return "9:16"
    if platform == "pinterest":
        return "2:3"
    if platform == "x":
        return "16:9"
    if platform == "linkedin":
        return "1.91:1"
    return "1:1"
