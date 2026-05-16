"""Repurpose handler — turn a source asset into a fan-out of social posts.

Source can be: a blog post, a customer review, a photo, an offer, a FAQ,
a case study, or a raw note. The handler reads the source, extracts the
2-5 strongest atomic ideas inside it, and produces a platform-native post
for each (idea × platform).

This is the highest-leverage SMM kind. One blog post → 10-15 cross-platform
posts. One 5-star review → an IG carousel + a LinkedIn POV + an X quote.
"""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from .briefs import (
    SocialBrief, SocialAsset, SocialPost, SocialPlatform, SourceKind,
)
from ._voice import voice_guardrails_block, hook_formula_block, cta_block
from ._vault_loader import build_voice_context_block


class _RepurposedPost(BaseModel):
    platform: SocialPlatform
    atomic_idea: str = Field(description=(
        "The ONE specific idea from the source this post is built on. "
        "Must be quotable in a sentence."
    ))
    caption: str = Field(description=(
        "Platform-native caption. Respect platform conventions and limits."
    ))
    hashtags: list[str] = Field(description="Lowercase, no '#' prefix.")
    format_hint: str = Field(description=(
        "'reel', 'carousel', 'single-image', 'short-video', 'text-only', "
        "or 'photo+poll'."
    ))
    needs_graphic: bool = Field(description=(
        "True if this post needs a visual from FORGE. False if text-only "
        "or if the source already provides usable media (e.g. 'photo' source)."
    ))


class _RepurposePlan(BaseModel):
    extracted_ideas: list[str] = Field(
        min_length=1,
        description="The atomic ideas you pulled from the source, in order of strength.",
    )
    posts: list[_RepurposedPost] = Field(min_length=1)


SYSTEM_PROMPT_TEMPLATE = """You are HERALD: Social Media Manager, repurposing one
source asset into a fan-out of platform-native posts.

{voice_guardrails}

{hooks}

{cta}

VOICE CONTEXT (from vault — treat as ground truth when present):
{voice_context}

REPURPOSING IS NOT COPY-PASTING
- Do not chop the source into N excerpts. Extract the *atomic ideas* and
  rebuild each idea as a native post on the target platform.
- One source typically has 2-5 atomic ideas worth posting. If you can only
  find 1, say so — don't pad.
- Each post must read like it was written for that platform, not
  translated to it.

PLATFORM RULES OF THUMB
- instagram: hook in first line, story in middle, soft CTA at end, 3-8 tags
- facebook:  conversational, light tags, link in first comment if any
- linkedin:  first-person POV, 3-5 short paragraphs, 2-4 tags max
- x:         one punchy line, 280-char hard limit, 1-2 tags
- tiktok:    spoken hook in first 3 words, 4-6 tags
- pinterest: keyword-rich, search-driven, 4-6 tags
- youtube_community: text/poll update, no hashtags

GRAPHIC HANDOFF
- Set needs_graphic=true if the post requires a visual asset (most do).
- For a 'photo' source the visual is already provided — needs_graphic=false.
- For a quote-style post that works text-only on x, needs_graphic=false."""


def repurpose(brief: SocialBrief) -> SocialAsset:
    """Fan out a source asset into platform-native posts.

    brief.payload:
      source_kind (required) — SourceKind ('blog_post', 'review', 'photo', etc.)
      source_text (required) — the raw content to repurpose
      platforms (required) — list of SocialPlatform values
      audience (optional)
      max_posts (optional, default 8)
    brief.context:
      anthropic_api_key (optional)
      model (optional, default claude-sonnet-4-6)
    """
    source_kind: Optional[SourceKind] = brief.payload.get("source_kind")
    source_text = brief.payload.get("source_text")
    platforms = brief.payload.get("platforms")
    if not source_kind or not source_text or not platforms:
        raise ValueError(
            "repurpose brief.payload must include 'source_kind', "
            "'source_text', and 'platforms'"
        )

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return SocialAsset(
            kind="repurpose",
            metadata={"error": "ANTHROPIC_API_KEY not set"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"
    max_posts = int(brief.payload.get("max_posts") or 8)
    audience = brief.payload.get("audience") or "the source's existing audience"

    user_prompt = (
        f"Source kind: {source_kind}\n"
        f"Target platforms: {', '.join(platforms)}\n"
        f"Audience: {audience}\n"
        f"Cap output at {max_posts} posts total — quality over count.\n\n"
        f"--- SOURCE ---\n{source_text}\n--- /SOURCE ---\n\n"
        "Extract the atomic ideas, then build platform-native posts for each."
    )

    voice_context = brief.context.get("voice_context")
    if voice_context is None:
        voice_context = build_voice_context_block() or "(none in vault)"
    system = SYSTEM_PROMPT_TEMPLATE.format(
        voice_guardrails=voice_guardrails_block(),
        hooks=hook_formula_block(),
        cta=cta_block(),
        voice_context=voice_context,
    )

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.parse(
        model=model,
        max_tokens=6000,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_RepurposePlan,
    )

    parsed: _RepurposePlan = resp.parsed_output
    posts: list[SocialPost] = []
    for p in parsed.posts[:max_posts]:
        clean_tags = [t.lstrip("#").strip().lower() for t in p.hashtags if t.strip()]
        graphic_req = None
        if p.needs_graphic:
            from .briefs import GraphicRequest
            graphic_req = GraphicRequest(
                concept=f"{p.platform} {p.format_hint} — {p.atomic_idea}",
                aspect_ratio=_aspect_for(p.platform, p.format_hint),
                style_notes="HogTron navy/cyan/gold, clean, modern, brand-consistent",
            )

        posts.append(SocialPost(
            platform=p.platform,
            caption=p.caption,
            hashtags=clean_tags,
            topic=p.atomic_idea,
            format_hint=p.format_hint,
            status="needs_graphic" if p.needs_graphic else "draft",
            graphic_request=graphic_req,
            notes=f"Repurposed from {source_kind}; idea: {p.atomic_idea}",
        ))

    return SocialAsset(
        kind="repurpose",
        posts=posts,
        summary=(
            f"Repurposed {source_kind} into {len(posts)} posts across "
            f"{len(set(p.platform for p in posts))} platform(s). "
            f"Atomic ideas: {len(parsed.extracted_ideas)}."
        ),
        payload={
            "source_kind": source_kind,
            "extracted_ideas": parsed.extracted_ideas,
        },
        metadata={"model": model, "n_posts": len(posts)},
    )


def _aspect_for(platform: str, format_hint: str) -> str:
    if format_hint in ("reel", "short-video"):
        return "9:16"
    if platform == "pinterest":
        return "2:3"
    if platform == "x":
        return "16:9"
    if platform == "linkedin":
        return "1.91:1"
    return "1:1"
