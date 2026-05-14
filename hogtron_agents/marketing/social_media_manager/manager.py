"""HERALD: Social Media Manager — the specialist class.

Same dispatcher pattern as Marketing/Creative/etc. One agent. One
entrypoint: compose(brief). Dispatches by kind to the right handler.

Position in the agent stack:
    ORACLE (Research)  → what to post about
    FORGE  (Creative)  → graphics/visuals on request
    HERALD (Marketing) → THIS: strategy, captions, calendars, hashtags
    ANVIL  (Operations)→ scheduling/publishing AFTER approval
    OVERSEER (CEO)     → cross-department orchestration + approvals

The SMM never publishes. Outputs include `publish_intent` seeds so an
approver can hand them to ANVIL, but the SMM itself has no Operations
dependency.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import SocialBrief, SocialAsset, SocialKind
from ..._shared.telemetry import TelemetrySink, NullSink, working
from . import _calendar, _caption, _repurpose, _hashtags, _brand_review

Handler = Callable[["SocialMediaManager", SocialBrief], SocialAsset]


class SocialMediaManager:
    NAME = "HERALD: Social Media Manager"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[SocialKind, Handler] = {
            "content_calendar": _do_calendar,
            "caption": _do_caption,
            "repurpose": _do_repurpose,
            "hashtag_pack": _do_hashtags,
            "brand_review": _do_brand_review,
        }

    def compose(self, brief: SocialBrief) -> SocialAsset:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(
                f"SocialMediaManager has no handler for kind={brief.kind!r}"
            )
        with working(self.telemetry, self.NAME, f"compose({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: SocialKind, handler: Handler) -> None:
        self._handlers[kind] = handler


# --- Handlers ----------------------------------------------------------

def _do_calendar(self: SocialMediaManager, brief: SocialBrief) -> SocialAsset:
    return _calendar.content_calendar(brief)


def _do_caption(self: SocialMediaManager, brief: SocialBrief) -> SocialAsset:
    return _caption.caption(brief)


def _do_repurpose(self: SocialMediaManager, brief: SocialBrief) -> SocialAsset:
    return _repurpose.repurpose(brief)


def _do_hashtags(self: SocialMediaManager, brief: SocialBrief) -> SocialAsset:
    return _hashtags.hashtag_pack(brief)


def _do_brand_review(self: SocialMediaManager, brief: SocialBrief) -> SocialAsset:
    return _brand_review.brand_review(brief)
