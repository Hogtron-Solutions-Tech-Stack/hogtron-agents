"""respond_to_reviews handler — full orchestration of the GBP review
responder migrated from Hogtron-Tools/review-bot.

The Node.js script (which was Soap-Gnome-hardcoded) did everything in
one process: fetched GBP reviews, drafted replies with Claude
directly, posted them. This Python port splits responsibilities along
the agent boundaries:

  Sentinel (this handler)  fetches reviews, applies tenant approval
                           rules, posts or queues
  Marketing.review_response drafts the reply text using tenant voice
  GBPReviewsClient         GBP API I/O

Per-tenant approval rules come from tenant.review_response_config:
  auto_post_5_star      bool (default False)
  auto_post_4_star      bool (default False)
  auto_post_below_4     bool (default False)

The HERALD draft itself may set flags=['human_required'] (e.g. medical
claims, legal issues). That ALWAYS overrides the tenant's auto-post
rule — we never post a draft the model said needs human review.

brief.payload (optional):
  tenant_id          — slug. Required.
  max_per_run        — cap responses per invocation (default 10).
                       Rate-limit protection during backfill.
  only_review_name   — process just one specific review (skip the
                       list_reviews call). For manual re-runs after
                       fixing a draft.
brief.context:
  tenant_config_loader — TenantConfigLoader (required)
  gbp_client_fn        — factory(tenant_id) → GBPReviewsClient (required)
  marketing_instance   — Marketing() (required for drafting)
  notify_owner_fn      — optional callable for queueing drafts
  anthropic_api_key    — falls through to env if missing
"""
from __future__ import annotations

import os
from typing import Any, Optional

from .briefs import SentinelBrief, SentinelFinding
from ._tenant_config import TenantConfig, TenantConfigLoader, TenantNotFound


def respond_to_reviews(brief: SentinelBrief) -> SentinelFinding:
    p = brief.payload or {}
    ctx = brief.context or {}

    tenant_id = p.get("tenant_id")
    if not tenant_id:
        return SentinelFinding(
            kind="respond_to_reviews", status="error",
            reason="payload.tenant_id is required",
        )

    loader: TenantConfigLoader = ctx.get("tenant_config_loader")
    gbp_factory = ctx.get("gbp_client_fn")
    marketing = ctx.get("marketing_instance")
    if not (loader and gbp_factory and marketing):
        return SentinelFinding(
            kind="respond_to_reviews", status="error",
            reason="brief.context requires tenant_config_loader + gbp_client_fn + marketing_instance",
        )

    try:
        tenant = loader.load(str(tenant_id))
    except TenantNotFound:
        return SentinelFinding(
            kind="respond_to_reviews", status="error",
            reason=f"tenant {tenant_id!r} not configured",
        )

    rr_cfg = tenant.review_response_config
    if not rr_cfg.enabled:
        return SentinelFinding(
            kind="respond_to_reviews", status="ok",
            payload={"reviews_processed": 0, "results": []},
            reason=f"review_response disabled for tenant {tenant_id!r}",
            metadata={"skipped_reason": "rr_disabled"},
        )
    if not rr_cfg.gbp_location_id:
        return SentinelFinding(
            kind="respond_to_reviews", status="error",
            reason=f"tenant {tenant_id!r} review_response enabled but gbp_location_id is empty",
        )

    # Build GBP client + Marketing brief context
    try:
        gbp = gbp_factory(tenant_id)
    except Exception as e:  # noqa: BLE001
        return SentinelFinding(
            kind="respond_to_reviews", status="error",
            reason=f"gbp_client_fn({tenant_id!r}) failed: {e}",
        )

    # Determine which reviews to process
    only_name = p.get("only_review_name")
    if only_name:
        # Single-review mode — caller did the lookup, we just need its
        # state. For simplicity we fetch the full list and filter.
        all_reviews = gbp.list_reviews(rr_cfg.gbp_location_id,
                                       only_unanswered=False, max_results=200)
        targets = [r for r in all_reviews if r.name == only_name]
    else:
        max_per_run = max(1, min(int(p.get("max_per_run") or 10), 50))
        targets = gbp.list_reviews(rr_cfg.gbp_location_id,
                                   only_unanswered=True, max_results=max_per_run)

    if not targets:
        return SentinelFinding(
            kind="respond_to_reviews", status="ok",
            payload={"reviews_processed": 0, "results": []},
            reason=f"no unanswered reviews for tenant {tenant_id!r}",
        )

    voice_ctx = _build_tenant_voice_context(tenant)
    api_key = ctx.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    notify_fn = ctx.get("notify_owner_fn")

    results: list[dict] = []
    n_posted = 0
    n_queued = 0
    n_errored = 0
    n_skipped_no_pii = 0
    for review in targets:
        outcome = _handle_one_review(
            review=review, tenant=tenant, voice_ctx=voice_ctx,
            marketing=marketing, gbp=gbp, api_key=api_key,
            notify_fn=notify_fn, rr_cfg=rr_cfg,
        )
        results.append(outcome)
        action = outcome.get("action")
        if action == "posted":
            n_posted += 1
        elif action == "queued":
            n_queued += 1
        elif action == "errored":
            n_errored += 1
        elif action == "skipped":
            n_skipped_no_pii += 1

    return SentinelFinding(
        kind="respond_to_reviews", status="ok",
        payload={"reviews_processed": len(targets), "results": results},
        metadata={
            "tenant_id": tenant_id,
            "tenant_name": tenant.client.name,
            "gbp_location_id": rr_cfg.gbp_location_id,
            "n_posted": n_posted,
            "n_queued": n_queued,
            "n_errored": n_errored,
            "n_skipped": n_skipped_no_pii,
        },
        reason=(f"processed {len(targets)} review(s) for {tenant_id!r}: "
                f"{n_posted} posted, {n_queued} queued, {n_errored} errored"),
    )


def _build_tenant_voice_context(tenant: TenantConfig) -> dict:
    """Translate TenantConfig into the payload Marketing.review_response
    expects in `tenant_voice_context`."""
    rr = tenant.review_response_config
    return {
        "business_name":     tenant.client.name,
        "location":          (tenant.client.locations[0]
                              if tenant.client.locations else ""),
        "services_summary":  rr.services_summary,
        "business_context":  rr.business_context,
        "signature":         rr.signature,
        "phone_to_mention":  rr.phone_to_mention,
        "word_limit":        rr.word_limit,
        "brand_voice":       tenant.brand.voice,
        "brand_voice_avoid": tenant.brand.voice_avoid,
    }


def _handle_one_review(*, review, tenant, voice_ctx, marketing, gbp,
                       api_key, notify_fn, rr_cfg) -> dict:
    """Returns a result dict for the result log."""
    # Import lazily so this module doesn't pull the Marketing pkg
    # transitively at import time.
    from ..marketing.briefs import MarketingBrief

    # 1. Draft via HERALD/Marketing
    try:
        asset = marketing.write(MarketingBrief(
            kind="review_response",
            payload={
                "review_text": review.body or "",
                "rating": review.rating,
                "author": review.author_name,
                "tenant_voice_context": voice_ctx,
            },
            context={"anthropic_api_key": api_key} if api_key else {},
            requester=f"sentinel.respond_to_reviews:{tenant.tenant_id}",
        ))
    except Exception as e:  # noqa: BLE001
        return {
            "review_name": review.name,
            "rating": review.rating,
            "action": "errored",
            "stage": "draft",
            "error": str(e)[:200],
        }
    if asset.metadata.get("error"):
        return {
            "review_name": review.name,
            "rating": review.rating,
            "action": "errored",
            "stage": "draft",
            "error": asset.metadata["error"],
        }

    body = asset.payload.get("body", "").strip()
    flags = list(asset.payload.get("flags") or [])
    tone = asset.payload.get("tone")

    # 2. Decide post-vs-queue
    auto_eligible = _is_auto_post_eligible(review.rating, rr_cfg, flags)

    # 3. Post or queue
    if auto_eligible:
        try:
            gbp.post_reply(review.name, body)
        except Exception as e:  # noqa: BLE001
            # Posting failed — degrade to queue so a human can intervene
            if notify_fn:
                try:
                    notify_fn({
                        "kind": "review_response_post_failed",
                        "tenant": tenant.client.name,
                        "review_id": review.review_id,
                        "review_rating": review.rating,
                        "review_body": review.body[:300],
                        "draft_body": body,
                        "error": str(e)[:200],
                    })
                except Exception:
                    pass
            return {
                "review_name": review.name,
                "rating": review.rating,
                "action": "errored",
                "stage": "post",
                "error": str(e)[:200],
                "draft_body": body,
            }
        return {
            "review_name": review.name,
            "rating": review.rating,
            "action": "posted",
            "tone": tone,
            "body": body,
            "flags": flags,
        }

    # Queue path — notify a human
    queue_reason = "model_flagged_human_required" if "human_required" in flags else "approval_rule_required"
    if notify_fn:
        try:
            notify_fn({
                "kind": "review_response_draft_pending_approval",
                "tenant": tenant.client.name,
                "review_id": review.review_id,
                "review_rating": review.rating,
                "review_author": review.author_name,
                "review_body": review.body[:500],
                "draft_body": body,
                "tone": tone,
                "flags": flags,
                "queue_reason": queue_reason,
            })
        except Exception as e:  # noqa: BLE001
            print(f"[respond_to_reviews] notify_owner_fn errored: {e}")
    return {
        "review_name": review.name,
        "rating": review.rating,
        "action": "queued",
        "queue_reason": queue_reason,
        "tone": tone,
        "body": body,
        "flags": flags,
    }


def _is_auto_post_eligible(rating: int, rr_cfg, flags: list[str]) -> bool:
    """A draft is auto-postable when:
      1. Model didn't flag for human review, AND
      2. Tenant's per-star rule allows auto-post for this rating
    """
    if "human_required" in (flags or []):
        return False
    ap = rr_cfg.approval_rules
    if rating == 5:
        return ap.auto_post_5_star
    if rating == 4:
        return ap.auto_post_4_star
    if rating <= 3:
        return ap.auto_post_below_4
    # Unknown rating (0 or weird value) — never auto-post
    return False
