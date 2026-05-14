"""HERALD: Social Media Manager.

A specialist inside the Marketing (HERALD) department. Plans calendars,
writes captions, repurposes source assets into multi-platform posts, and
builds hashtag packs. Never publishes — that's ANVIL's job.

Internal package for now. Promote to MarketingKind dispatch (or split into
its own department) once the kinds settle.
"""
from .briefs import (
    SocialBrief,
    SocialAsset,
    SocialKind,
    SocialPlatform,
    SocialPostStatus,
    SocialPost,
    SourceKind,
    GraphicRequest,
    PublishIntent,
    BrandReviewScore,
)
from .manager import SocialMediaManager
from ._voice import (
    HOOK_FORMULAS,
    BANNED_TERMS,
    SOFT_FLAGS,
    CTA_VERBS,
    PLATFORM_STRUCTURE,
)
from ._vault_loader import build_voice_context_block

__all__ = [
    "SocialMediaManager",
    "SocialBrief",
    "SocialAsset",
    "SocialKind",
    "SocialPlatform",
    "SocialPostStatus",
    "SocialPost",
    "SourceKind",
    "GraphicRequest",
    "PublishIntent",
    "BrandReviewScore",
    # voice exports — useful for callers building custom prompts
    "HOOK_FORMULAS",
    "BANNED_TERMS",
    "SOFT_FLAGS",
    "CTA_VERBS",
    "PLATFORM_STRUCTURE",
    "build_voice_context_block",
]
