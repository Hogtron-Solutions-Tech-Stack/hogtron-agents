"""Marketing department head.

One agent. One entrypoint: write(brief). Dispatches by kind to the right
handler. All kinds share Claude client setup + brand voice via prompt
fragments.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import MarketingBrief, MarketingAsset, MarketingKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import _etsy_listing, _social_post, _autonomous
from .social_media_manager import SocialMediaManager, SocialBrief

Handler = Callable[["Marketing", MarketingBrief], MarketingAsset]


class Marketing:
    NAME = "Marketing"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        # Shared SMM instance — reused across the 5 social kinds so we don't
        # rebuild the dispatcher dict per call.
        self._smm = SocialMediaManager(telemetry=self.telemetry)
        self._handlers: dict[MarketingKind, Handler] = {
            "etsy_listing": _do_etsy_listing,
            "social_post": _do_social_post,
            "blog_post": _do_blog_post,
            "review_response": _do_review_response,
            "ad_copy": _do_ad_copy,
            "email_outreach": _do_email_outreach,
            # HERALD: Social Media Manager (delegates to social_media_manager/)
            "content_calendar": _do_smm("content_calendar"),
            "caption":          _do_smm("caption"),
            "repurpose":        _do_smm("repurpose"),
            "hashtag_pack":     _do_smm("hashtag_pack"),
            "brand_review":     _do_smm("brand_review"),
        }

    def write(self, brief: MarketingBrief) -> MarketingAsset:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Marketing has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"write({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: MarketingKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    def run_autonomous(self, directive: str, *, anthropic_api_key: str,
                       model: str = "claude-sonnet-4-6", max_iterations: int = 8,
                       progress_callback=None, should_cancel=None):
        """Layer 2 — chain Marketing kinds in response to a directive.

        Default Sonnet 4.6 — copy generation rarely benefits from Opus for
        the lengths Marketing typically writes. Override for long-form blog
        posts or nuanced brand voice work.
        """
        return _autonomous.run_autonomous(
            self, directive, anthropic_api_key=anthropic_api_key,
            model=model, max_iterations=max_iterations,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )


# --- Handlers -----------------------------------------------------------

def _do_etsy_listing(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    return _etsy_listing.etsy_listing(brief)


def _do_social_post(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    return _social_post.social_post(brief)


def _do_blog_post(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    """Port target: hogtron-dashboard Social-to-Blog Engine."""
    raise NotImplementedError(
        "blog_post pending migration from hogtron-dashboard Social-to-Blog Engine"
    )


def _do_review_response(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    """Port target: hogtron-dashboard AI Smart Review Responder."""
    raise NotImplementedError(
        "review_response pending migration from hogtron-dashboard AI Smart Review Responder"
    )


def _do_ad_copy(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    """Net-new: Etsy Ads / Google Ads short copy. No existing port source."""
    raise NotImplementedError("ad_copy not yet implemented — net-new kind")


def _do_email_outreach(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
    """Net-new: cold outreach drafts to leads. No existing port source."""
    raise NotImplementedError("email_outreach not yet implemented — net-new kind")


# --- HERALD: Social Media Manager delegation -----------------------------
# Each of the 5 social kinds is a thin wrapper that converts MarketingBrief
# to SocialBrief, calls SocialMediaManager.compose(), and converts the
# returned SocialAsset back to a MarketingAsset. No business logic lives
# here — the SMM subpackage owns it.

def _do_smm(kind: str) -> Handler:
    """Build a handler that routes the brief to SocialMediaManager.compose()."""
    def _handler(self: Marketing, brief: MarketingBrief) -> MarketingAsset:
        social_asset = self._smm.compose(SocialBrief(
            kind=kind,
            payload=brief.payload,
            context=brief.context,
            requester=brief.requester,
        ))
        # Adapt SocialAsset → MarketingAsset. The SMM's `posts` list and
        # `summary` ride in MarketingAsset.payload so callers using the
        # standard Marketing interface get everything without importing
        # SMM-specific types. Direct SMM users can still call
        # SocialMediaManager().compose() and keep the typed SocialPost objects.
        return MarketingAsset(
            kind=brief.kind,
            primary_text=social_asset.summary,
            payload={
                "summary": social_asset.summary,
                "posts": [p.model_dump() for p in social_asset.posts],
                **social_asset.payload,
            },
            metadata=social_asset.metadata,
        )
    return _handler
