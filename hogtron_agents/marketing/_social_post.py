"""Social-post handler — Claude writes Pinterest-optimized copy for a listing.

Ported from FactoryHQ/agents/pinterester.py LLM half. Pinterest is search-
driven, not feed-driven — the copy targets keyword queries rather than
visual aesthetics. Hashtags work here (unlike Etsy).

Caller uses the returned title/description/alt_text in a follow-up
Operations.do(publish_pinterest) call. Marketing produces the words;
Operations puts them on the platform.

v1 supports Pinterest only. Instagram captions and TikTok captions
would be additional kinds or `platform` payload param.
"""
from __future__ import annotations

import os

from pydantic import BaseModel, Field

from .._shared.claude_router import route_messages_parse
from .briefs import MarketingBrief, MarketingAsset


class _PinCopy(BaseModel):
    title: str = Field(max_length=100, description=(
        "Pinterest pin title — max 100 chars. Pattern: '[Shirt phrase] | "
        "[Product noun] | [Buyer descriptor or occasion]'. Pinterest titles "
        "show in search results and are clickable. Front-load the most "
        "search-worthy phrase. Title case. No emojis."
    ))
    description: str = Field(max_length=500, description=(
        "Pinterest description — max 500 chars. First sentence: what the "
        "product IS and who it's for. Then 2-3 sentences with specific "
        "selling points (fabric, fit, occasion). End with 4-6 lowercase "
        "hashtags (#funnyshirt #giftforhim etc.). Keywords matter more "
        "than prose. No emojis."
    ))
    alt_text: str = Field(max_length=200, description=(
        "Accessibility alt text describing the shirt design visually. "
        "Example: 'White unisex tee with bold black text reading Grill "
        "Sergeant above crossed spatulas illustration.' Visible to "
        "screen readers and used by Pinterest's vision indexing."
    ))


SYSTEM_PROMPT = """You are the Marketing department's social-post handler.
Your job is to write Pinterest-optimized copy for a HogTron Factory shirt listing.

PINTEREST CONTEXT:
- Pinterest is search-driven, not feed-driven. Users TYPE QUERIES like
  "funny coffee shirt for mom" or "fathers day grilling gift." Match the
  user's exact mental model.
- Title + description are searchable text. Front-load the highest-volume
  keywords. Generic descriptive phrases beat clever copy here.
- Hashtags work (unlike on Etsy where they're ignored). Use 4-6,
  lowercase, no spaces inside the tag.
- The PIN'S JOB is to get the click to Etsy. Don't write to "sell" — write
  to "match a search intent."

HARD CONSTRAINTS:
- Title <=100 chars. Description <=500 chars. Alt text <=200 chars.
- No emojis (Pinterest renders them inconsistently across platforms).
- No competitor brand names. No "as seen on" claims. No superlatives.
- No fake urgency ("limited time!"). Pinterest demotes spammy copy."""


def social_post(brief: MarketingBrief) -> MarketingAsset:
    """Write Pinterest-optimized pin copy.

    brief.payload:
      phrase (required) — the shirt phrase
      concept (optional)
      audience (optional)
      platform (optional, default 'pinterest') — only 'pinterest' in v1
    brief.context:
      anthropic_api_key (optional, falls back to env)
      model (optional, default 'claude-sonnet-4-6')
    """
    phrase = brief.payload.get("phrase")
    if not phrase:
        raise ValueError("social_post brief.payload must include 'phrase'")

    platform = (brief.payload.get("platform") or "pinterest").lower()
    if platform != "pinterest":
        return MarketingAsset(
            kind="social_post",
            metadata={"error": f"platform {platform!r} not supported in v1; only 'pinterest'"},
        )

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return MarketingAsset(
            kind="social_post",
            metadata={"error": "ANTHROPIC_API_KEY not set"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"

    user_prompt = (
        f"Phrase: {phrase!r}\n"
        f"Concept: {brief.payload.get('concept') or ''}\n"
        f"Audience: {brief.payload.get('audience') or 'unspecified'}\n\n"
        "Write the Pinterest pin copy for this shirt."
    )

    resp = route_messages_parse(
        agent="marketing.social_post",
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_PinCopy,
        api_key=key,
    )

    copy: _PinCopy = resp.parsed_output
    return MarketingAsset(
        kind="social_post",
        primary_text=copy.title,
        payload={
            "title": copy.title,
            "description": copy.description,
            "alt_text": copy.alt_text,
            "platform": "pinterest",
        },
        metadata={
            "model": model,
            "phrase": phrase,
            "title_len": len(copy.title),
            "description_len": len(copy.description),
        },
    )
