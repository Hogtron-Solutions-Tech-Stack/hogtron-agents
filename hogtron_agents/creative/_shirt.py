"""Shirt design handler — the Creative department's POD shirt workflow.

Two stateless phases:
  1. art_direct() — Claude reads a phrase+audience, produces an ArtDirection
                    (typography, layout, recraft prompt, placement).
  2. generate()   — Recraft renders the printable PNG from the art prompt.

What's NOT here (lives in the calling pipeline):
  - DB rows / status state machines
  - Printify upload + product creation (Operations dept territory)
  - Etsy listing copy + tags (Marketing dept territory)

CRITICAL IP CONSTRAINT: this handler accepts only cleared briefs (phrase
already vetted against blocklist + USPTO). System prompt enforces "generic
motifs only" — no characters, brands, lyrics, teams.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .._shared import recraft
from .._shared.claude_router import route_messages_parse
from .briefs import CreativeBrief, CreativeAsset


# --- Schema -------------------------------------------------------------

class ArtDirection(BaseModel):
    shirt_color: str = Field(
        description="Garment color name: 'heather grey', 'black', 'natural', "
                    "'mauve', 'dust blue', etc. Pick what flatters the phrase + audience."
    )
    typography_style: str = Field(
        description="Font family vibe: 'distressed serif', 'bold sans-serif', "
                    "'handwritten script', 'vintage western', 'retro 70s rounded', etc."
    )
    layout_description: str = Field(
        description="How the text is arranged on the shirt: stacked lines, "
                    "arched, single bold line, etc. Be specific about hierarchy."
    )
    accent_element: str = Field(
        description="Small decorative graphic that complements the text. "
                    "Should NOT include any branded imagery, logos, or characters. "
                    "Generic motifs only (sun, coffee cup, stars, leaves, etc.)."
    )
    color_palette: list[str] = Field(
        min_length=2, max_length=5,
        description="Hex codes for design colors (text + accent). 2-5 colors."
    )
    mood_tags: list[str] = Field(
        min_length=2, max_length=5,
        description="Words like 'cozy', 'edgy', 'vintage', 'minimal', "
                    "'maximalist' — drives Recraft's substyle selection."
    )
    recraft_prompt: str = Field(
        description=(
            "The exact prompt sent to Recraft. MUST start with "
            "'Standalone graphic artwork on a fully transparent background — '. "
            "MUST include the candidate phrase verbatim. MUST describe typography, "
            "layout, and accent motif. "
            "CRITICAL — DO NOT include any of these words/concepts: "
            "shirt, t-shirt, tee, garment, clothing, fabric, apparel, mockup, "
            "neckline, collar, sleeve, hanger. The output is printable artwork "
            "that will be placed onto a shirt by Printify; it MUST NOT itself "
            "depict or contain a shirt silhouette, outline, or frame. Think of "
            "it as a sticker design — just the art, nothing around it. "
            "MUST NOT mention any brand names, characters, or copyrighted "
            "material. 2-4 sentences."
        )
    )
    placement_y: float = Field(
        ge=0.20, le=0.55,
        description=(
            "Vertical position on the shirt as a normalized coordinate. "
            "0.30 wide horizontal, 0.35 standard, 0.40 vertically tall, "
            "0.45 very tall / banner-topped designs. Bias toward 0.35-0.40."
        ),
    )


SYSTEM_PROMPT = """You are the Creative department's shirt-design handler for HogTron Factory.

Your job: read an approved shirt phrase and produce an art direction that
will be sent to an image generation model (Recraft) to create the printable
front graphic.

CRITICAL — IP RULES (these are non-negotiable):
- Your `accent_element` and `recraft_prompt` must NEVER reference:
  characters, mascots, brand logos, athletes, celebrities, song lyrics,
  movie/TV imagery, sports teams, college logos
- Generic motifs only: sun, moon, stars, coffee cup, flowers, leaves,
  arrows, hearts, geometric shapes, abstract patterns
- The phrase itself has already been IP-cleared. The art around it cannot
  reintroduce risk.

DESIGN PRINCIPLES:
- Typography is the hero. Most Etsy POD bestsellers are 80% text.
- Choose a shirt color that contrasts well with the printable colors.
  Avoid white-on-white or dark-on-dark.
- Match style to audience. A "girl dad" shirt for sentimental gifting
  wants warm/handwritten. A "World's Okayest Grill Dad" wants bold/blocky.
- The recraft_prompt MUST describe ONLY the printable artwork — never
  the garment. Think "vinyl sticker design" or "screen print transfer,"
  not "t-shirt." Verboten words: shirt, t-shirt, tee, garment, apparel,
  neckline, collar, sleeve. Just describe the art.
- Always specify 'fully transparent background' so Printify can place it.
- Keep the art simple enough to scale to 4500x5400px without artifacts.

PLACEMENT (placement_y):
- 0 = top of print area (near collar), 1 = bottom. 0.30 puts a horizontal
  logo at chest level. Taller designs need higher placement_y so the top
  doesn't crowd the neckline. When in doubt, bias DOWN — slightly-low
  looks intentional; cut-off-at-collar looks broken."""


_DEFAULT_CACHE = Path(os.environ.get(
    "HOGTRON_DESIGN_CACHE",
    str(Path.home() / ".hogtron" / "design_cache"),
))


# --- Public entry point -------------------------------------------------

def design_shirt(brief: CreativeBrief) -> CreativeAsset:
    """Two-phase shirt design: Claude art-direct -> Recraft render.

    brief.payload keys:
      phrase    (required) — the cleared text
      audience  (optional) — who the shirt is for
      saturation (optional) — market crowding signal
    brief.context keys:
      anthropic_api_key (optional, falls back to env)
      recraft_api_key   (optional, falls back to env)
      cache_dir         (optional, falls back to ~/.hogtron/design_cache)
      design_id         (optional, used in filename)
    """
    phrase = brief.payload.get("phrase")
    if not phrase:
        raise ValueError("shirt brief.payload must include 'phrase'")

    direction = _art_direct(
        phrase=phrase,
        audience=brief.payload.get("audience"),
        saturation=brief.payload.get("saturation"),
        api_key=brief.context.get("anthropic_api_key"),
    )

    cache_dir = Path(brief.context.get("cache_dir") or _DEFAULT_CACHE)
    design_id = brief.context.get("design_id") or uuid4().hex[:8]
    local_path = cache_dir / f"design_{design_id}.png"

    result = recraft.generate(
        prompt=direction.recraft_prompt,
        api_key=brief.context.get("recraft_api_key"),
    )
    recraft.download(result["url"], local_path)

    return CreativeAsset(
        kind="shirt",
        primary_url=result["url"],
        file_path=str(local_path),
        artifacts={
            "art_direction": direction.model_dump(),
            "recraft_prompt": direction.recraft_prompt,
            "shirt_color": direction.shirt_color,
            "placement_y": direction.placement_y,
        },
        metadata={
            "model": "claude-sonnet-4-6",
            "recraft_model": result.get("model"),
            "recraft_style": result.get("style"),
        },
    )


# --- Phase 1: art direction (stateless) --------------------------------

def _art_direct(
    *,
    phrase: str,
    audience: Optional[str],
    saturation: Optional[str],
    api_key: Optional[str],
) -> ArtDirection:
    """Claude art-direction call. Routed through claude_router so that:
      - Default backend is API (Sean's approved framing)
      - Max subscription is used opportunistically when HOGTRON_TRY_MAX=true
        and the quota gate is green
      - Telemetry is logged for every call to %LOCALAPPDATA%\\HogTron\\logs\\
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    # API key only enforced on the canonical path; router will fail loudly
    # if it's needed for fallback and missing. We still require it here to
    # preserve the existing "fail before doing any expensive work" pattern.
    if not key and os.environ.get("HOGTRON_TRY_MAX", "false").lower() != "true":
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Pass via brief.context or env, "
            "or set HOGTRON_TRY_MAX=true to attempt Max subscription first."
        )

    prompt = (
        f"Phrase: {phrase!r}\n"
        f"Audience: {audience or 'unspecified'}\n"
        f"Market saturation: {saturation or 'unspecified'}\n\n"
        "Produce an art direction for this shirt."
    )
    resp = route_messages_parse(
        agent="creative.shirt",
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        output_format=ArtDirection,
        api_key=key,
    )
    return resp.parsed_output
