---
tags: [hogtron, agents, herald, social-media-manager]
aliases: [smm, social-media-manager, herald-smm]
---

# HERALD: Social Media Manager

> A specialist inside HERALD (Marketing). Plans calendars, writes captions, repurposes assets into platform-native posts, and builds hashtag packs. **Does not publish.**

## Where this lives in the stack

| Customer-facing name | Department | Role for social |
|---|---|---|
| ORACLE | Research | Surfaces what to post about (trends, leads, audits) |
| FORGE | Creative | Renders graphics/visuals on request |
| **HERALD: SMM** | **Marketing (this package)** | **Strategy, captions, calendars, hashtags, repurposing, drafts** |
| ANVIL | Operations | Schedules + publishes — only after human approval |
| OVERSEER | CEO | Cross-department orchestration + approvals |

The SMM never calls ANVIL directly. It produces drafts and `publish_intent` seeds; a human reviewer hands approved posts to ANVIL.

## Status

🚧 Internal build, not yet wired into `Marketing.write()` dispatch. Kinds piloted standalone; promote into `MarketingKind` once stable.

| Kind | Status | Notes |
|---|---|---|
| `content_calendar` | ✅ piloted v2 | N slots across platforms; voice-aware |
| `caption` | ✅ piloted v2 | Multi-platform; named hook-formula variety enforced |
| `repurpose` | ✅ piloted v2 | Source asset → fan-out; voice-aware |
| `hashtag_pack` | ✅ piloted v2 | Tiered (broad / niche / local) + keyword phrases |
| `brand_review` | ✅ new in v2 | Quality gate: 0-10 per criterion + concrete rewrites |

### v2 upgrade (this session)

Applied the `marketing:content-creation` skill's methodology and the Obsidian vault's voice/audience knowledge:

- **`_voice.py`** — shared module with 11 named hook formulas (`surprising_stat`, `contrarian`, `question`, `scenario`, `bold_claim`, `story_opening`, `how_to`, `listicle`, `why_x_is_wrong`, `what_x_taught_us`, `do_this_not_that`), per-platform structure templates (char limits, sweet spots, hashtag bands, format strengths, emoji policy), banned-term list, soft-flag list, CTA action verbs.
- **`_vault_loader.py`** — reads `Content/Brand Voice.md`, `Audience/Audience Language.md`, `Content/Hook Swipe File.md`, `Content/What Works - <Platform>.md`, `Audience/ICP Profile.md` from the Obsidian vault and produces a context block injected into every handler's system prompt. Strips scaffold placeholders; degrades gracefully when files are empty. Override path with `OBSIDIAN_VAULT` env var.
- **Hook-formula variety** — `caption()` now forces each variant to use a different named hook formula. Dupes are dropped post-parse so the reviewer always compares real angles, not paraphrases. Caller can constrain to a subset via `payload["hook_formulas"]`.
- **`brand_review` kind** — deterministic checks (banned terms, char limit, hashtag count → `platform_fit` 0-10) combined with LLM scoring on `voice_fit`, `audience_language`, `hook_strength`, `cta_quality`. Returns weighted `overall` 0-10, verdict (`ship_it` / `minor_edits` / `rewrite` / `reject`), and up to 5 concrete rewrite suggestions. Banned-term hits cap overall at 4 (hard ship-blocker).

## Usage

```python
from hogtron_agents.marketing.social_media_manager import (
    SocialMediaManager, SocialBrief,
)

smm = SocialMediaManager()

# 1. Plan a calendar
cal = smm.compose(SocialBrief(
    kind="content_calendar",
    payload={
        "business_context": "Soap Gnome — small-batch goat-milk soap, Etsy + DTC, Tampa FL",
        "platforms": ["instagram", "pinterest", "tiktok"],
        "date_range": "2026-05-13 to 2026-05-27",
        "posts_per_week": 4,
        "themes": ["restock drops", "founder story", "ingredient education"],
        "audience": "soap collectors, gift buyers, eczema-conscious skin care",
    },
))
# cal.summary -> strategy rationale
# cal.posts   -> list[SocialPost] with topic/time/format/angle (empty caption)

# 2. Fill in a slot — each variant uses a different named hook formula
post = smm.compose(SocialBrief(
    kind="caption",
    payload={
        "platform": "instagram",
        "topic": "Friday restock — 6 new bars, 8pm ET",
        "angle": "tease the scents, build FOMO without fake urgency",
        "cta": "drop a notification bell emoji to get pinged",
        "n_variants": 3,
        "hook_formulas": ["question", "story_opening", "contrarian"],  # optional constrain
        "include_graphic_request": True,
    },
))
# post.posts[0].caption / .hashtags / .graphic_request
# post.posts[0].notes -> "[question] Why this hook for soap collectors..."
# post.metadata["hook_formulas_used"] -> ["question", "story_opening", "contrarian"]

# 2b. Brand-review the variant before approval
review = smm.compose(SocialBrief(
    kind="brand_review",
    payload={
        "caption": post.posts[0].caption,
        "platform": "instagram",
        "hashtags": post.posts[0].hashtags,
        "topic": post.posts[0].topic,
    },
))
# review.payload -> BrandReviewScore dict with verdict, overall, rewrite_suggestions
# verdict "ship_it" means caller can flip status to ready_for_approval

# 3. Repurpose a blog post
fanout = smm.compose(SocialBrief(
    kind="repurpose",
    payload={
        "source_kind": "blog_post",
        "source_text": "<full blog markdown>",
        "platforms": ["linkedin", "x", "instagram"],
        "max_posts": 6,
    },
))

# 4. Build a hashtag pack
pack = smm.compose(SocialBrief(
    kind="hashtag_pack",
    payload={
        "topic": "small-batch handmade soap",
        "platform": "instagram",
        "locale": "Tampa, FL",
    },
))
# pack.payload -> {broad, niche, local, keyword_phrases}
```

## Handoff to FORGE

When `include_graphic_request=True` (caption) or when `repurpose` decides a post needs a visual, the returned `SocialPost.graphic_request` is shaped to drop into a `CreativeBrief`:

```python
from hogtron_agents.creative import Creative, CreativeBrief

forge = Creative()
for post in fanout.posts:
    if post.graphic_request:
        asset = forge.design(CreativeBrief(
            kind="canva_asset",
            payload=post.graphic_request.model_dump(),
        ))
        post.publish_intent.media_ref = asset.primary_url
        post.status = "ready_for_approval"
```

## Handoff to ANVIL (post-approval only)

Once a human has reviewed and approved a post, the caller maps it to an `OperationsBrief`. The SMM never does this itself:

```python
from hogtron_agents.operations import Operations, OperationsBrief

anvil = Operations()
if post.status == "approved" and post.publish_intent:
    anvil.do(OperationsBrief(
        kind="publish_pinterest",   # or whichever platform handler exists
        payload=post.publish_intent.model_dump(),
    ))
```

## What this package does NOT do

- **Publish.** Hard rule. Even with `status="approved"`, publication is ANVIL's call.
- **Generate visuals.** FORGE does that. The SMM emits `GraphicRequest` seeds.
- **Persist anything.** No DB. Caller decides storage. Matches the rest of the agent stack.
- **Pull analytics.** No "what worked last month" — that's a future kind (or a Research kind).
- **Schedule across timezones.** `scheduled_for` is a string suggestion; ANVIL owns timezone resolution.

## Adding a new kind

Same pattern as the rest of the agents repo:

1. Add the kind name to `SocialKind` in `briefs.py`.
2. Write `_kind.py` with `kind_name(brief: SocialBrief) -> SocialAsset`.
3. Register in `manager.py`'s `_handlers` dict + add a `_do_kind` shim.
4. Export anything new from `__init__.py`.

Candidate next kinds (not built yet):

- `comment_reply` — drafts reply candidates to DMs / comments
- `bio_optimization` — rewrites a profile bio for a specific platform + audience
- `analytics_summary` — translates raw platform analytics into a human readout
- `content_audit` — scores existing posts against pillars and flags gaps

## Brand voice — wired to the Obsidian vault

Every handler runs `build_voice_context_block(platform=...)` by default, which pulls live content from:

- `Content/Brand Voice.md` — "use these words" / "never use these words" / sentence patterns
- `Audience/Audience Language.md` — pain phrases / desire phrases / trigger words / words to avoid
- `Content/Hook Swipe File.md` — proven hooks (used as exemplars, never copied)
- `Content/What Works - <Platform>.md` — per-platform winning patterns
- `Audience/ICP Profile.md` — who they are, where they hang out, buying triggers

Override the vault path with `OBSIDIAN_VAULT=/some/path` env var, or pass a pre-built block via `brief.context["voice_context"]` to skip the vault read entirely.

Scaffold placeholders (`TBD`, `*(populate…)`, `*(empty)`) are stripped automatically — handlers see only real, populated content. The richer the vault gets, the sharper the agent gets.

## The compose → review → approve → ship loop

```
ORACLE → topic ──► HERALD compose ──► brand_review ──► human approve
                          │              │                 │
                          ▼              ▼                 ▼
                     graphic_request   verdict       FORGE renders
                          │                              │
                          ▼                              ▼
                       FORGE                   publish_intent → ANVIL
```

- `compose` produces a draft (status: `draft` or `needs_graphic`)
- `brand_review` scores the draft (verdict gates auto-progression)
- A human approves (status: `approved`)
- FORGE renders any pending `graphic_request` (status fills `publish_intent.media_ref`)
- ANVIL takes the `publish_intent` and publishes (status: `published`)

The SMM owns the first two steps. Everything past `approved` is downstream.
