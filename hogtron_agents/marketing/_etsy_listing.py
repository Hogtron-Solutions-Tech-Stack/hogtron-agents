"""Etsy listing handler — Claude writes Etsy-optimized title + description + tags.

Ported from FactoryHQ/agents/marketer.py write_listing(). Stateless: brief
in, MarketingAsset out. Caller (FactoryHQ marketer.py) handles DB and the
Printify push (Operations dept territory).
"""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from .briefs import MarketingBrief, MarketingAsset


class _Listing(BaseModel):
    title: str = Field(
        max_length=140,
        description=(
            "Etsy title — max 140 chars. Front-load the highest-volume "
            "keywords. Common pattern: '[Phrase] | [Audience descriptor] "
            "Shirt | [Gift occasion]'. Use title case. Avoid all caps, "
            "special characters except | and -."
        ),
    )
    description: str = Field(
        min_length=200,
        description=(
            "Etsy description — 200-2000 chars. Start with a 1-sentence hook "
            "that includes the phrase. Then 3-5 bullet points about fit, "
            "fabric, fit-to-occasion. Mention Bella+Canvas 3001 unisex. End "
            "with care + size guidance. No emojis. Markdown supported."
        ),
    )
    tags: list[str] = Field(
        min_length=8, max_length=13,
        description=(
            "Etsy tags — max 13, each max 20 chars. Mix: 2-3 exact-phrase "
            "tags, 4-5 broader category tags, 2-3 occasion tags, 1-2 audience "
            "tags. All lowercase. Each tag MUST be ≤20 chars including spaces."
        ),
    )
    seo_rationale: str = Field(
        description="One sentence: which keywords you optimized for and why."
    )


SYSTEM_PROMPT = """You are the Marketing department's Etsy listing handler for HogTron Factory.
Your job is to write Etsy listing copy that ranks well and converts.

ETSY ALGORITHM CONTEXT:
- Title keywords carry the most weight; first 40 chars weighted highest
- Tags should be PHRASES, not single words (Etsy explicitly recommends this)
- Tag-title overlap helps; don't waste a tag that's already in the title
- Listings need 4-8 weeks of indexed history to rank — write for evergreen
  searchability, not viral phrases
- Buyers search problem-state language: 'tired mom shirt' not 'maternal
  exhaustion apparel'

CONVERSION CONTEXT:
- Description hook (line 1) is what shows in search previews — make it sell
- Bullet points scan better than paragraphs on mobile
- Mentioning Bella+Canvas 3001 builds trust (it's a known premium blank)
- Don't write descriptions like ads. Write them like a friend recommending
  the shirt.

HARD CONSTRAINTS:
- Title ≤140 chars
- Each tag ≤20 chars (Etsy will silently drop tags >20 chars)
- 13 tags maximum
- No emojis in title or tags (Etsy strips them inconsistently)
- No competitor brand names, no 'as seen on TV', no superlatives ('best ever')"""


def etsy_listing(brief: MarketingBrief) -> MarketingAsset:
    """Generate Etsy listing copy for a shirt design.

    brief.payload:
      phrase (required) — the shirt phrase
      concept (optional) — concept tag (e.g. 'tired mom humor')
      audience (optional) — who buys this
      saturation (optional) — market crowding signal
    brief.context:
      anthropic_api_key (optional, falls back to env)
      model (optional, default claude-opus-4-7)
    """
    phrase = brief.payload.get("phrase")
    if not phrase:
        raise ValueError("etsy_listing brief.payload must include 'phrase'")

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return MarketingAsset(
            kind="etsy_listing",
            metadata={"error": "ANTHROPIC_API_KEY not set"},
        )
    model = brief.context.get("model") or "claude-opus-4-7"

    user_prompt = (
        f"Phrase: {phrase!r}\n"
        f"Concept: {brief.payload.get('concept') or ''}\n"
        f"Audience: {brief.payload.get('audience') or 'unspecified'}\n"
        f"Market saturation: {brief.payload.get('saturation') or 'unspecified'}\n\n"
        "Write the Etsy listing for this shirt."
    )

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.parse(
        model=model,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_Listing,
    )

    listing: _Listing = resp.parsed_output

    # Final guardrails (Claude is good but not perfect)
    tags = [t.strip().lower()[:20] for t in listing.tags][:13]
    title = listing.title[:140]

    return MarketingAsset(
        kind="etsy_listing",
        primary_text=title,
        payload={
            "title": title,
            "description": listing.description,
            "tags": tags,
            "seo_rationale": listing.seo_rationale,
        },
        metadata={
            "model": model,
            "phrase": phrase,
            "n_tags": len(tags),
            "title_len": len(title),
        },
    )
