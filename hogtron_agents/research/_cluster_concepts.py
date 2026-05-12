"""Cluster-concepts handler — Claude synthesizes raw signals into concepts
with phrase candidates.

Ported from FactoryHQ/agents/researcher.py synthesize(). Stateless: caller
supplies signals + optional seasonal hint; returns structured concepts.
"""
from __future__ import annotations

import os
from typing import Optional

import anthropic
from pydantic import BaseModel, Field

from .briefs import ResearchBrief, ResearchFinding


class _Phrase(BaseModel):
    text: str = Field(description="The shirt phrase, exact wording as it would appear")
    rationale: str = Field(description="One-sentence reason this fits the concept and avoids IP risk")


class _Concept(BaseModel):
    concept: str = Field(description="Short concept tag, e.g. 'tired mom humor'")
    audience: str = Field(description="Who buys this: demographic + emotional state")
    saturation: str = Field(description="low | medium | high — competition level on Etsy")
    seasonal_window: Optional[str] = Field(
        default=None,
        description="If this concept ties to an upcoming holiday, name it (e.g. 'Mother's Day'). Else null.",
    )
    phrases: list[_Phrase] = Field(min_length=3, max_length=8)


class _SynthesisOutput(BaseModel):
    concepts: list[_Concept] = Field(min_length=1, max_length=10)
    reasoning: str = Field(
        description="2-3 sentences on how concepts were chosen and which seasonal windows informed them"
    )


SYSTEM_PROMPT = """You are the Research department's concept-clustering handler for HogTron Factory,
a print-on-demand shirt business. Your job is to synthesize concept briefs that the
Creative department will turn into shirts sold on Etsy.

STRICT IP RULES — phrases that violate these are useless because they will
be auto-rejected downstream (Etsy bans permanent). Do not generate them:
- No named characters, brands, or franchises (Disney, Marvel, Nintendo,
  Pokemon, Bluey, Hello Kitty, Stanley, Yeti, Nike, etc.)
- No public figures or celebrities (living or dead — estates are aggressive)
- No song lyrics or movie/TV quotes
- No sports team or league references
- No registered phrases (avoid trademarked apparel slogans — if a phrase
  sounds like an existing brand on a shirt, skip it)

QUALITY BAR — what makes a good POD phrase:
- Generic-enough niche language that hasn't been trademarked
- Punny, observational, or affirmation-style humor
- Speaks to an emotional state ("tired mom") or identity ("plant person")
- 3-8 words typically; can be longer for full-sentence jokes
- Avoids overdone clichés ("but first coffee", "live laugh love")

CONCEPT QUALITY:
- Each concept should have a clear audience and emotional hook
- Saturation rating: low = lane is open; medium = some competition;
  high = many shops selling similar — still valid since execution
  on tags/photos wins
- For each concept, generate 3-8 phrase variants that explore the angle

When the user provides seasonal context, prioritize concepts that fit
those upcoming windows. Listings need to be live 4-8 weeks before the
holiday for Etsy to rank them."""


def cluster_concepts(brief: ResearchBrief) -> ResearchFinding:
    """Cluster raw market signals into Etsy-shirt concepts with phrase candidates.

    brief.payload:
      signals (list[dict], optional) — raw market signals (e.g. Etsy listings
        with title/sales_badge keys). Empty list is fine; synthesis will lean
        on the seasonal_hint instead.
      max_concepts (int, default 5)
      seasonal_hint (str, optional) — pre-rendered text about upcoming
        commercial windows (Mother's Day, Father's Day, etc.). Caller is
        responsible for generating this (different stores, different calendars).
    brief.context:
      anthropic_api_key (optional, falls back to env)
      model (optional, default 'claude-opus-4-7')
    """
    signals = brief.payload.get("signals") or []
    max_concepts = int(brief.payload.get("max_concepts") or 5)
    seasonal_hint = brief.payload.get("seasonal_hint") or ""

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return ResearchFinding(
            kind="cluster_concepts", status="error",
            reason="ANTHROPIC_API_KEY not set",
        )
    model = brief.context.get("model") or "claude-opus-4-7"

    user_prompt = _build_user_prompt(signals, max_concepts, seasonal_hint)
    client = anthropic.Anthropic(api_key=key)

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            output_format=_SynthesisOutput,
        )
    except anthropic.APIError as e:
        return ResearchFinding(
            kind="cluster_concepts", status="error",
            reason=f"Claude API error: {e}",
        )

    output: _SynthesisOutput = response.parsed_output
    return ResearchFinding(
        kind="cluster_concepts",
        status="ok",
        payload={
            "concepts": [c.model_dump() for c in output.concepts],
            "reasoning": output.reasoning,
        },
        metadata={
            "n_concepts": len(output.concepts),
            "n_phrases": sum(len(c.phrases) for c in output.concepts),
            "n_signals_in": len(signals),
            "model": model,
        },
    )


def _build_user_prompt(signals: list[dict], max_concepts: int, seasonal_hint: str) -> str:
    parts = []
    if seasonal_hint:
        parts.append(seasonal_hint)
        parts.append("")
    if signals:
        parts.append(f"Recent market signals ({len(signals)} listings):")
        for s in signals[:50]:
            badge = f" [{s.get('signal_text') or s.get('sales_badge') or ''}]" if (s.get('signal_text') or s.get('sales_badge')) else ""
            parts.append(f"  - {s.get('title', '')}{badge}")
        parts.append("")
        parts.append(
            "Cluster these signals into concepts. Use them as evidence of what's "
            "selling, not as phrases to copy directly."
        )
    else:
        parts.append(
            "No scraped market signals provided. Generate concepts "
            "from the seasonal calendar above plus general POD evergreen niches "
            "(coffee humor, teacher life, plant parent, pet humor, etc.)."
        )
    parts.append("")
    parts.append(
        f"Produce up to {max_concepts} concepts. Prioritize concepts whose "
        f"seasonal_window is NOW or SOON. Each concept needs 3-8 phrase variants."
    )
    return "\n".join(parts)
