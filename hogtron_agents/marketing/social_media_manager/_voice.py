"""Shared voice constants — hook formulas, banned terms, CTA verbs, platform structures.

Single source of truth imported by every handler's SYSTEM_PROMPT. Pulled from:
  - marketing:content-creation skill (hook + headline formulas, platform best
    practices, CTA principles)
  - C:\\Users\\atron\\Obsidian Vault\\Content\\Brand Voice.md (banned terms)
  - C:\\Users\\atron\\Obsidian Vault\\Audience\\Audience Language.md (banned terms)

When the vault files get populated with real high-performer data, this module
becomes the *defaults* — runtime context from the vault loader overrides anything
here. Don't put anything brittle here.
"""
from __future__ import annotations

# --- Hook formulas (named so callers can request a specific pattern) -----

HOOK_FORMULAS: dict[str, str] = {
    "surprising_stat":     "Open with a specific number that contradicts a common belief.",
    "contrarian":          "State the opposite of conventional wisdom and back it up.",
    "question":            "Ask a question your audience can't help but answer in their head.",
    "scenario":            "Paint a 'imagine if' or 'last week, this happened' scene.",
    "bold_claim":          "Make a definitive statement that feels almost too confident.",
    "story_opening":       "Drop the reader mid-scene with concrete characters and stakes.",
    "how_to":              "Promise a specific result, name the common obstacle you'll avoid.",
    "listicle":            "[Number] [adjective] ways to [achieve specific result].",
    "why_x_is_wrong":      "Name a belief the audience holds, prove it wrong, offer the fix.",
    "what_x_taught_us":    "Frame learnings from a high-volume or high-stakes experience.",
    "do_this_not_that":    "Two-part construction: the cliché vs. the better move.",
}


# --- Words/phrases the brand never uses ---------------------------------
# Curated from Brand Voice.md + Audience Language.md "Never use" sections.
# These are *hard* bans — any handler that produces a draft containing one of
# these should regenerate or flag it for review.

BANNED_TERMS: list[str] = [
    "synergy",
    "leverage",          # as in "leverage our X" — verb form only; the noun is fine
    "drive results",
    "best-in-class",
    "disrupt",
    "revolutionize",
    "game-changer",
    "game changer",
    "in today's fast-paced world",
    "in this digital age",
    "elevate your",
    "unlock the power",
    "take it to the next level",
    "circle back",
    "move the needle",
]

# Filler/AI-tell words that should be flagged but not auto-banned (sometimes
# they're appropriate). brand_review surfaces these; handlers don't fail on them.
SOFT_FLAGS: list[str] = [
    "actually",          # filler
    "literally",         # filler
    "very",              # weakens the sentence
    "really",            # weakens the sentence
    "just",              # weakens the sentence
]


# --- CTA action verbs (specific, ranked by clarity) ----------------------
CTA_VERBS: list[str] = [
    "Get", "Start", "Download", "Join", "Try", "See", "Read",
    "Watch", "Reply", "Save", "Tag", "Drop", "Comment", "Share",
    "Book", "Claim", "Subscribe", "Follow",
]


# --- Platform structure templates ---------------------------------------
# Hook → Body → CTA → Hashtags (skill: marketing:content-creation)
# Per-platform overrides below.

PLATFORM_STRUCTURE: dict[str, dict] = {
    "instagram": {
        "char_limit": 2200,
        "sweet_spot": "125-150 chars before truncation; full caption rewards saves",
        "hashtag_count": "3-8 (mid-niche beats broad)",
        "structure": "Hook line → 2-4 line break-separated story beats → CTA → hashtags",
        "format_strengths": ["reel", "carousel", "single-image"],
        "emoji_policy": "use sparingly (max 2); never in opening hook",
    },
    "facebook": {
        "char_limit": 2000,
        "sweet_spot": "under 80 chars for link posts; longer ok for native stories",
        "hashtag_count": "0-3 (FB barely uses them)",
        "structure": "Conversational hook → short narrative → question CTA",
        "format_strengths": ["photo+poll", "single-image", "short-video", "text-only"],
        "emoji_policy": "fine, max 2",
    },
    "linkedin": {
        "char_limit": 3000,
        "sweet_spot": "1,300 chars before 'see more' truncation",
        "hashtag_count": "2-4 max",
        "structure": "POV/story hook → 3-5 short paragraphs (1-3 sentences) → soft CTA or question",
        "format_strengths": ["text-only", "single-image", "carousel"],
        "emoji_policy": "avoid in opening; sparing use elsewhere",
    },
    "x": {
        "char_limit": 280,
        "sweet_spot": "one punchy line; thread for more",
        "hashtag_count": "1-2 max",
        "structure": "Hook = whole post OR Hook → thread continuation",
        "format_strengths": ["text-only", "single-image", "short-video"],
        "emoji_policy": "minimal; one max",
    },
    "tiktok": {
        "char_limit": 2200,
        "sweet_spot": "first 3 words are the spoken-aloud hook",
        "hashtag_count": "4-6",
        "structure": "Visual hook in first 3s → payoff → CTA in spoken voice",
        "format_strengths": ["short-video", "reel"],
        "emoji_policy": "fine for energy; max 3",
    },
    "pinterest": {
        "char_limit": 500,
        "sweet_spot": "keyword-rich; users SEARCH here",
        "hashtag_count": "4-6 (Pinterest does use them)",
        "structure": "Title is keyword phrase → description has 2-3 keyword sentences + hashtags",
        "format_strengths": ["single-image", "short-video"],
        "emoji_policy": "none (renders inconsistently)",
    },
    "youtube_community": {
        "char_limit": 1500,
        "sweet_spot": "polls and questions outperform announcements",
        "hashtag_count": "0",
        "structure": "Direct question or update → context → ask for response",
        "format_strengths": ["photo+poll", "text-only", "single-image"],
        "emoji_policy": "fine",
    },
}


# --- Voice block builders -----------------------------------------------

def voice_guardrails_block() -> str:
    """The hard rules every handler should bake into its system prompt."""
    banned = ", ".join(f'"{t}"' for t in BANNED_TERMS)
    return f"""HARD VOICE RULES (non-negotiable)
- Never use: {banned}
- No "In today's fast-paced world…" or any variant of generic AI-opener
- No fake urgency ("Limited time!", "Don't miss out!"), no superlatives ("the
  best ever"), no clickbait punctuation (!!!), no ALL-CAPS for emphasis
- No competitor brand names, no "as seen on TV" claims
- Specific > vague. A real number, a real name, a real outcome beats
  adjectives every time."""


def hook_formula_block(formulas: list[str] | None = None) -> str:
    """List the available hook formulas; pass a subset to constrain."""
    keys = formulas or list(HOOK_FORMULAS.keys())
    lines = [f"  - {k}: {HOOK_FORMULAS[k]}" for k in keys if k in HOOK_FORMULAS]
    return "HOOK FORMULAS (use a NAMED pattern per variant — do not paraphrase)\n" + "\n".join(lines)


def platform_block(platform: str) -> str:
    """Render the platform's structure block."""
    p = PLATFORM_STRUCTURE.get(platform)
    if not p:
        return f"PLATFORM: {platform} (no structure template — use general best practices)"
    return (
        f"PLATFORM: {platform}\n"
        f"  - Char limit: {p['char_limit']}; sweet spot: {p['sweet_spot']}\n"
        f"  - Hashtags: {p['hashtag_count']}\n"
        f"  - Structure: {p['structure']}\n"
        f"  - Best formats: {', '.join(p['format_strengths'])}\n"
        f"  - Emojis: {p['emoji_policy']}"
    )


def cta_block() -> str:
    return (
        "CTA RULES\n"
        f"  - Lead with an action verb: {', '.join(CTA_VERBS[:10])}…\n"
        "  - Be specific about what happens next ('Reply with your top metric'\n"
        "    not 'Let me know'). One primary CTA per post."
    )
