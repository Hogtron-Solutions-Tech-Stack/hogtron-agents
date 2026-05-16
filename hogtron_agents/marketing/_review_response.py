"""Review-response handler — Marketing drafts a reply to a Google review.

Migrated from `Hogtron-Tools/packages/review-bot/reviewResponder.js`
(Soap Gnome hardcoded) to a generic per-tenant Marketing kind. The
original JS prompt baked the business name, services, signature, and
phone number into a single string; this Python port takes all of that
from `brief.payload.tenant_voice_context` so any tenant can use the
same handler.

Sentinel orchestrates: detect the review → call this handler with the
tenant's voice context + review body → receive the draft → apply
tenant's approval rules (auto-post 5★? queue <5★?) → post via the GBP
client (see services/sentinel/providers/gbp_reviews.py).

The brief.payload shape is intentionally simple so the orchestration
layer can build it from a TenantConfig + raw review without leaking
the full TenantConfig schema into Marketing.
"""
from __future__ import annotations

import os

import anthropic
from pydantic import BaseModel, Field

from .briefs import MarketingBrief, MarketingAsset


class _ReviewReply(BaseModel):
    body: str = Field(description=(
        "The review reply text, ready to post verbatim to GBP. Plain "
        "text only — no asterisks, no markdown. Ends with the supplied "
        "signature. Stays under the supplied word limit. For positive "
        "reviews (4-5 stars) thanks specifically; for negative reviews "
        "(1-3 stars) apologises, acknowledges the specific issue, and "
        "offers the recovery path (phone call or alternate service)."
    ))
    tone: str = Field(description=(
        "Two-word summary of the tone used. Examples: 'warm grateful', "
        "'apologetic recovery', 'neutral acknowledgment'. Lets the "
        "approval queue UI surface tone at a glance."
    ))
    flags: list[str] = Field(default_factory=list, description=(
        "Optional escalation flags. Use 'human_required' if the review "
        "raises legal/health/safety issues, contains a name/PII, or "
        "asks something the AI shouldn't answer. Use 'awaiting_facts' "
        "if the reply needs info we don't have. Empty list is fine."
    ))


SYSTEM_PROMPT = """You are the Marketing department's review-response handler.
Your job: write a single Google Business Profile reply to one customer review.

VOICE
- Sound like a real, warm human being. Never a corporation.
- Match the tenant's brand voice exactly as described below. If the
  brand voice list says "spotless, friendly, well-maintained" then
  every reply should feel that way.
- Avoid the words listed under voice_avoid. Avoid every cheesy phrase
  ever printed on a corporate response card: "your time matters",
  "earn back your stars", "we strive to provide", "your feedback is
  important to us", etc.

FORMATTING (HARD RULES)
- Plain text only. No asterisks. No markdown. No emoji unless the
  tenant's voice explicitly includes emoji.
- Stay under the supplied word_limit. Count words; trim ruthlessly.
- End with the supplied signature, verbatim, on its own line.

RATING-BASED PATTERN (apply automatically)
- 5★: Thank warmly. Reference one specific thing they mentioned. One
  short sentence is often enough.
- 4★: Thank warmly. Reference the specific thing they liked. Briefly
  acknowledge any minor complaint and how you'll address it.
- 3★ or lower: Apologise sincerely. Acknowledge the SPECIFIC problem
  in their words (not "your experience"). Offer the recovery path:
  the phone number to call, the alternate service to try.
- 1-2★: Same as 3★ but lead with the apology. Don't get defensive.
  Don't argue. Don't say "we'll do better" without saying how.

WHAT NEVER TO DO
- Never invent facts not given in the prompt. If the reviewer claims
  a specific staff member did something, don't confirm or deny —
  acknowledge the experience and offer to follow up.
- Never use the reviewer's full name if it's unusual (PII concern).
  Generic "thank you" is safer than "thank you Margaret Hennessy".
- Never make promises the tenant can't keep ("we'll refund every
  unhappy customer"). Offer concrete next steps the tenant CAN do.
- Never post if the review raises a regulated issue (medical advice,
  legal claim, accusation of crime). Set flags=['human_required']
  instead — the orchestrator will queue for human handling.

OUTPUT
Return JSON matching the schema. The `body` field is what gets posted
verbatim. The `tone` and `flags` fields drive the approval queue UI."""


def review_response(brief: MarketingBrief) -> MarketingAsset:
    """Draft a GBP review reply.

    brief.payload (required):
      review_text:  the review body
      rating:       1-5 star rating (int)
    brief.payload (optional, defaults sensible):
      author:           reviewer's display name (used cautiously per voice rules)
      tenant_voice_context: dict with the per-tenant strings the prompt
                            needs. Built by the orchestrator from
                            TenantConfig.review_response_config and
                            TenantConfig.brand. Keys:
        business_name      — display name (e.g. "Soap Gnome Laundromat")
        location           — city/state (e.g. "Little Ferry, NJ")
        services_summary   — one-line services list
        business_context   — multi-paragraph background for the prompt
        signature          — verbatim closing line
        phone_to_mention   — offered in negative replies
        word_limit         — int, default 75
        brand_voice        — list of voice words (matches tenant brand.voice)
        brand_voice_avoid  — list of words to never sound like

    brief.context (optional):
      anthropic_api_key   — falls back to env
      model               — default claude-sonnet-4-6
    """
    review_text = brief.payload.get("review_text")
    if not review_text:
        return MarketingAsset(
            kind="review_response",
            metadata={"error": "review_response brief.payload requires 'review_text'"},
        )
    rating = brief.payload.get("rating")
    try:
        rating = int(rating) if rating is not None else None
    except (TypeError, ValueError):
        rating = None

    tenant_ctx = brief.payload.get("tenant_voice_context") or {}
    business_name = tenant_ctx.get("business_name", "the business")
    location = tenant_ctx.get("location", "")
    services = tenant_ctx.get("services_summary", "")
    bg = tenant_ctx.get("business_context", "")
    signature = tenant_ctx.get("signature", "").strip()
    phone = tenant_ctx.get("phone_to_mention", "")
    word_limit = int(tenant_ctx.get("word_limit") or 75)
    voice = tenant_ctx.get("brand_voice") or []
    voice_avoid = tenant_ctx.get("brand_voice_avoid") or []
    author = brief.payload.get("author") or "Guest"

    key = brief.context.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return MarketingAsset(
            kind="review_response",
            metadata={"error": "ANTHROPIC_API_KEY not set"},
        )
    model = brief.context.get("model") or "claude-sonnet-4-6"

    voice_block = ""
    if voice:
        voice_block += "voice (be these things): " + ", ".join(voice) + "\n"
    if voice_avoid:
        voice_block += "voice_avoid (never sound like): " + ", ".join(voice_avoid) + "\n"

    user_prompt = (
        f"TENANT: {business_name}"
        + (f" in {location}" if location else "")
        + "\n"
        + (f"services: {services}\n" if services else "")
        + (f"background: {bg}\n" if bg else "")
        + (f"phone (for negative-recovery): {phone}\n" if phone else "")
        + (f"signature (use verbatim at end): {signature}\n" if signature else "")
        + f"word_limit: {word_limit}\n"
        + (voice_block or "")
        + "\n"
        + f"REVIEW from {author}"
        + (f" ({rating}-star)" if rating else "")
        + f":\n\"{review_text}\"\n\n"
        "Write the reply now."
    )

    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.parse(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=_ReviewReply,
    )

    reply: _ReviewReply = resp.parsed_output

    # Soft guard: trim trailing whitespace + drop accidental markdown
    body = reply.body.strip().replace("**", "").replace("__", "")
    # Soft guard: enforce word limit (model usually respects it, but if not, truncate)
    words = body.split()
    if len(words) > word_limit + 5:  # tiny tolerance for split irregularities
        body = " ".join(words[:word_limit]).rstrip(",.;:") + "…"

    return MarketingAsset(
        kind="review_response",
        primary_text=body[:120],   # short summary for list views
        payload={
            "body": body,
            "tone": reply.tone,
            "flags": list(reply.flags or []),
            "rating": rating,
            "word_count": len(body.split()),
        },
        metadata={
            "model": model,
            "review_len_chars": len(review_text),
            "tenant_business_name": business_name,
            "has_human_required_flag": "human_required" in (reply.flags or []),
        },
    )
