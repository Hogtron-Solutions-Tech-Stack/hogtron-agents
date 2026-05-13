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

Handler = Callable[["Marketing", MarketingBrief], MarketingAsset]


class Marketing:
    NAME = "Marketing"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[MarketingKind, Handler] = {
            "etsy_listing": _do_etsy_listing,
            "social_post": _do_social_post,
            "blog_post": _do_blog_post,
            "review_response": _do_review_response,
            "ad_copy": _do_ad_copy,
            "email_outreach": _do_email_outreach,
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
