"""Website mockup handler — the Creative department's client mockup workflow.

Two stateless phases:
  1. _plan_design() — Claude reads audit data + business info, produces a
                      MockupPlan (palette, hero copy, sections, trust bar, top fix).
  2. _render_html()  — Claude renders a complete single-file HTML mockup from
                       the plan. Saved to disk; no external render API needed.

What's NOT here:
  - Audit scraping (Research/ORACLE territory)
  - Delivery to client (Operations territory)
  - Proposal PDF wrapper (proposal_cover handler)

brief.payload keys:
  business_name  (required)  — display name of the client business
  url            (optional)  — live domain being audited (for context only)
  audit_data     (optional)  — dict from ResearchFinding.payload (seo_audit / geo_audit)
  address        (optional)  — physical address for footer/contact section
  phone          (optional)  — phone number for footer/contact section
  business_type  (optional)  — e.g. "HVAC", "chiropractor", "restaurant"

brief.context keys:
  anthropic_api_key (optional, falls back to ANTHROPIC_API_KEY env)
  cache_dir         (optional, falls back to ~/.hogtron/mockup_cache)
  mockup_id         (optional, used in filename)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .._shared.claude_router import route_messages_parse, route_messages_create
from .briefs import CreativeBrief, CreativeAsset


_DEFAULT_CACHE = Path(os.environ.get(
    "HOGTRON_MOCKUP_CACHE",
    str(Path.home() / ".hogtron" / "mockup_cache"),
))


# ---------------------------------------------------------------------------
# Schema — MockupPlan (structured output from Phase 1)
# ---------------------------------------------------------------------------

class MockupPlan(BaseModel):
    primary_color: str = Field(
        description="Primary brand color hex (e.g. '#1a2e4a'). Usually a dark navy/slate."
    )
    secondary_color: str = Field(
        description="Secondary brand color hex. Contrasts the primary — e.g. '#00c4cc' cyan."
    )
    accent_color: str = Field(
        description="Accent / CTA button color hex — should pop against both primary and white. E.g. '#f4c842'."
    )
    background_color: str = Field(
        description="Page background hex. Usually '#ffffff' or a very light tint."
    )
    text_color: str = Field(
        description="Body copy text hex. Usually '#1a1a1a' or similar dark."
    )
    hero_headline: str = Field(
        description="Main hero headline — punchy value prop, ≤10 words."
    )
    hero_subheadline: str = Field(
        description="Supporting hero text — 1–2 sentences expanding the headline."
    )
    cta_primary: str = Field(
        description="Primary CTA button label (≤5 words). E.g. 'Get a Free Quote'."
    )
    cta_secondary: str = Field(
        description="Secondary CTA button label (≤5 words). E.g. 'See Our Work'."
    )
    trust_signals: list[str] = Field(
        min_length=3, max_length=5,
        description=(
            "Short trust bar items — rating, guarantee, years in business, etc. "
            "E.g. ['4.9★ Google Rating', '20+ Years Serving the Valley', 'Licensed & Insured']."
        ),
    )
    sections: list[str] = Field(
        min_length=3, max_length=7,
        description=(
            "Ordered page sections to include. Valid values: hero, trust_bar, services, "
            "about, gallery, reviews, faq, contact. Always include hero and contact."
        ),
    )
    design_notes: str = Field(
        description=(
            "1–2 sentences on the design direction and what to emphasize. "
            "Guides the HTML renderer on tone and layout emphasis."
        ),
    )
    top_fix: str = Field(
        description=(
            "The single most impactful SEO/GEO fix from the audit — written as a "
            "plain-English hook HogTron uses in the pitch. "
            "E.g. 'Your Google Business title still has a typo — fixing it could recover lost map pack traffic.'"
        ),
    )


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = """You are the Creative department's website mockup planner for HogTron Solutions.

Given a business audit, design a compelling website redesign plan. Your output drives
the HTML mockup that HogTron presents to prospects — it must feel polished, professional,
and meaningfully better than what the audit found.

DESIGN PRINCIPLES:
- Dark header (navy, charcoal, or deep forest) with a contrasting accent (cyan, gold, coral)
- Trust bar directly below the nav (ratings, guarantees, years in business)
- Hero with clear value prop and two CTAs (primary = conversion, secondary = social proof)
- Sections must match the actual business type — a plumber needs services + contact,
  not a gallery; a restaurant needs menu + reservations, not FAQ
- Color palette should match business vibe:
    trades/HVAC → bold navy + orange
    medical/chiro → clean slate + teal
    food/restaurant → warm terracotta + cream
    retail → modern dark + gold or coral

CRITICAL: Respond with ONLY the raw JSON matching the schema. No prose, no markdown."""


_RENDER_SYSTEM = """You are a senior front-end developer at HogTron Solutions.
Generate a COMPLETE, pixel-perfect, single-file HTML website mockup for a client prospect.

HARD REQUIREMENTS:
- Single file: all CSS inside <style>, all JS inside <script>. Zero CDN dependencies.
- Mobile-responsive: CSS grid + flexbox, media query at 768px breakpoint.
- Use EXACT hex colors from the plan — no approximations.
- Smooth scroll behavior (html { scroll-behavior: smooth; })
- Fade-in on scroll via IntersectionObserver (pure vanilla JS, no libraries).
- NO external images. Use CSS gradients or inline SVG icons everywhere.
- Reviews section: 3 five-star Google-style reviews with realistic first names + review text.
- Contact section: form (Name, Phone, Email, Message) + real address/phone if provided.
- Footer: address, phone, copyright year, tagline.
- Nav: sticky header with logo text + 3–4 anchor links to page sections + CTA button.
- Trust bar: immediately below nav, small inline icons + trust signal text.
- All section IDs match the nav anchor links exactly.

CRITICAL: Respond with ONLY the raw HTML. Start with <!DOCTYPE html> and end with </html>.
No explanation. No markdown fences. Just the HTML."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def design_mockup(brief: CreativeBrief) -> CreativeAsset:
    """Two-phase website mockup: plan → render → save HTML → return CreativeAsset."""
    business_name = brief.payload.get("business_name") or "Local Business"
    url = brief.payload.get("url", "")
    audit_data: dict[str, Any] = brief.payload.get("audit_data") or {}
    address = brief.payload.get("address", "")
    phone = brief.payload.get("phone", "")
    business_type = brief.payload.get("business_type", "local business")
    api_key = brief.context.get("anthropic_api_key")

    # Phase 1 — design plan (structured)
    plan = _plan_design(
        business_name=business_name,
        url=url,
        audit_data=audit_data,
        business_type=business_type,
        address=address,
        phone=phone,
        api_key=api_key,
    )

    # Phase 2 — full HTML render (freeform text)
    html = _render_html(
        plan=plan,
        business_name=business_name,
        url=url,
        audit_data=audit_data,
        address=address,
        phone=phone,
        business_type=business_type,
        api_key=api_key,
    )

    # Save to file
    cache_dir = Path(brief.context.get("cache_dir") or _DEFAULT_CACHE)
    cache_dir.mkdir(parents=True, exist_ok=True)
    mockup_id = brief.context.get("mockup_id") or uuid4().hex[:8]
    slug = "".join(c if c.isalnum() else "_" for c in business_name.lower())[:20]
    file_path = cache_dir / f"mockup_{slug}_{mockup_id}.html"
    file_path.write_text(html, encoding="utf-8")

    return CreativeAsset(
        kind="mockup",
        primary_url=file_path.as_uri(),
        file_path=str(file_path),
        artifacts={
            "plan": plan.model_dump(),
            "html_bytes": len(html.encode("utf-8")),
        },
        metadata={
            "business_name": business_name,
            "url": url,
            "business_type": business_type,
            "model": "claude-sonnet-4-6",
            "top_fix": plan.top_fix,
        },
    )


# ---------------------------------------------------------------------------
# Phase 1: design plan (structured output)
# ---------------------------------------------------------------------------

def _plan_design(
    *,
    business_name: str,
    url: str,
    audit_data: dict[str, Any],
    business_type: str,
    address: str,
    phone: str,
    api_key: Optional[str],
) -> MockupPlan:
    """Claude reads audit data → structured MockupPlan."""
    # Trim audit_data to a safe summary so we don't bloat the prompt.
    # Pull the most useful keys and skip raw HTML excerpts.
    audit_summary = _summarise_audit(audit_data)

    prompt = (
        f"Business: {business_name}\n"
        f"Type: {business_type}\n"
        f"URL: {url or 'unknown'}\n"
        f"Address: {address or 'unknown'}\n"
        f"Phone: {phone or 'unknown'}\n\n"
        f"Audit findings:\n{audit_summary}\n\n"
        "Design a website redesign plan for this business."
    )

    resp = route_messages_parse(
        agent="creative.mockup.plan",
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=_PLAN_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=MockupPlan,
        api_key=api_key,
    )
    return resp.parsed_output


# ---------------------------------------------------------------------------
# Phase 2: HTML render (freeform text)
# ---------------------------------------------------------------------------

def _render_html(
    *,
    plan: MockupPlan,
    business_name: str,
    url: str,
    audit_data: dict[str, Any],
    address: str,
    phone: str,
    business_type: str,
    api_key: Optional[str],
) -> str:
    """Claude renders the full HTML mockup from the plan. Returns raw HTML string."""
    plan_json = json.dumps(plan.model_dump(), indent=2)
    prompt = (
        f"Business: {business_name} ({business_type})\n"
        f"URL: {url or 'not provided'}\n"
        f"Address: {address or 'not provided'}\n"
        f"Phone: {phone or 'not provided'}\n\n"
        f"Design plan:\n{plan_json}\n\n"
        f"Sections to include (in order): {', '.join(plan.sections)}\n\n"
        "Generate the complete single-file HTML mockup now."
    )

    resp = route_messages_create(
        agent="creative.mockup.render",
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=_RENDER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        api_key=api_key,
    )

    # Extract text from anthropic content blocks
    parts: list[str] = []
    for block in resp.content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(block["text"])
        elif hasattr(block, "text"):
            parts.append(block.text)

    html = "".join(parts).strip()

    # Strip any accidental markdown fences the model might add
    if html.startswith("```"):
        lines = html.splitlines()
        # Drop first line (```html or ```) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        elif lines[0].strip().startswith("```"):
            lines = lines[1:]
        html = "\n".join(lines).strip()

    return html


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarise_audit(audit_data: dict[str, Any]) -> str:
    """Convert audit_data dict into a compact plain-text summary for the prompt.

    Handles both seo_audit and geo_audit shapes from ResearchFinding.payload.
    Falls back gracefully if the dict doesn't match expected keys.
    """
    if not audit_data:
        return "No audit data provided."

    lines: list[str] = []

    # Overall scores
    overall = audit_data.get("overall_score") or audit_data.get("score")
    if overall is not None:
        lines.append(f"Overall score: {overall}/100")

    # SEO pillar scores
    pillars = audit_data.get("pillars") or audit_data.get("scores") or {}
    if isinstance(pillars, dict):
        for k, v in pillars.items():
            lines.append(f"  {k}: {v}")

    # Top issues / recommendations
    for key in ("issues", "top_issues", "recommendations", "fixes", "findings"):
        items = audit_data.get(key)
        if isinstance(items, list) and items:
            lines.append(f"\n{key.replace('_', ' ').title()}:")
            for item in items[:8]:  # cap at 8 to stay within prompt budget
                if isinstance(item, str):
                    lines.append(f"  - {item}")
                elif isinstance(item, dict):
                    label = item.get("label") or item.get("title") or item.get("issue") or str(item)
                    lines.append(f"  - {label}")
            break

    # GEO-specific fields
    for key in ("gbp_status", "citation_consistency", "review_velocity", "ai_overview_presence"):
        val = audit_data.get(key)
        if val is not None:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    # Generic fallback — dump top-level string/number values
    if not lines:
        for k, v in audit_data.items():
            if isinstance(v, (str, int, float, bool)):
                lines.append(f"{k}: {v}")
            if len(lines) >= 15:
                break

    return "\n".join(lines) if lines else "Audit data present but no parseable fields found."
