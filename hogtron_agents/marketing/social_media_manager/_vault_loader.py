"""Vault loader — read Obsidian markdown files into a compact context block.

Reads from the user's Obsidian vault (default:
C:\\Users\\atron\\Obsidian Vault) to surface the *concrete* brand-voice,
audience-language, hook, and platform-pattern signals that should override
the defaults in `_voice.py`.

Graceful by design: every file may be a scaffold with mostly "TBD"
placeholders. The loader strips those, extracts only the populated sections,
and produces a short context block. If a file is missing or empty, the
loader returns "" for that section — handlers fall back to defaults.

Usage:
    block = build_voice_context_block(platform="instagram")
    # pass into brief.context["voice_context"]
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional


DEFAULT_VAULT_PATH = r"C:\Users\atron\Obsidian Vault"


def _vault_path() -> Path:
    """Resolve vault root, allowing override via OBSIDIAN_VAULT env var."""
    return Path(os.environ.get("OBSIDIAN_VAULT", DEFAULT_VAULT_PATH))


def _read(rel_path: str) -> str:
    p = _vault_path() / rel_path
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


# Lines that contain these markers are dropped from extracted content —
# they're scaffold placeholders, not real data.
_SCAFFOLD_MARKERS = (
    "tbd", "*(populate", "*(empty", "*(add", "scaffold", "fill via",
)


def _strip_scaffold(text: str) -> list[str]:
    """Return lines that look like real content, not scaffold placeholders."""
    keep = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if any(m in lower for m in _SCAFFOLD_MARKERS):
            continue
        keep.append(stripped)
    return keep


def _section(md: str, heading: str) -> str:
    """Extract a section between '## heading' and the next '## '."""
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)"
    m = re.search(pattern, md, re.MULTILINE | re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


# --- Public loaders ------------------------------------------------------

def load_brand_voice() -> str:
    """Read Content/Brand Voice.md, return a populated-only summary."""
    md = _read(r"Content\Brand Voice.md")
    if not md:
        return ""
    parts = []
    for section in ("Use these words", "Never use these words",
                    "Sentence patterns that work", "Sentence patterns to avoid"):
        body = _section(md, section)
        lines = _strip_scaffold(body)
        if lines:
            parts.append(f"  {section}:")
            parts.extend(f"    {line}" for line in lines[:10])
    return ("BRAND VOICE (from vault):\n" + "\n".join(parts)) if parts else ""


def load_audience_language() -> str:
    """Read Audience/Audience Language.md — extract real phrases only."""
    md = _read(r"Audience\Audience Language.md")
    if not md:
        return ""
    parts = []
    for section in ("Pain phrases (how they describe the problem)",
                    "Desire phrases (how they describe the outcome they want)",
                    "Trigger words (the specific words that get them to engage)",
                    "Words/phrases to AVOID"):
        body = _section(md, section)
        # Audience Language uses tables; pull non-scaffold table rows
        lines = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("|") and "Quote" not in line and "---" not in line:
                cells = [c.strip() for c in line.strip("|").split("|")]
                if cells and cells[0] and not any(m in cells[0].lower() for m in _SCAFFOLD_MARKERS):
                    lines.append(cells[0])
            elif line.startswith("- ") and not any(m in line.lower() for m in _SCAFFOLD_MARKERS):
                lines.append(line.lstrip("- ").strip())
        if lines:
            parts.append(f"  {section.split('(')[0].strip()}:")
            parts.extend(f"    - {ln}" for ln in lines[:8])
    return ("AUDIENCE LANGUAGE (from vault):\n" + "\n".join(parts)) if parts else ""


def load_hook_swipes() -> str:
    """Read Content/Hook Swipe File.md — top hooks with real source."""
    md = _read(r"Content\Hook Swipe File.md")
    if not md:
        return ""
    hooks = []
    body = _section(md, "Top hooks by performance")
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("|") and "Hook" not in line and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and cells[0] and not any(m in cells[0].lower() for m in _SCAFFOLD_MARKERS):
                hooks.append(cells[0])
    if not hooks:
        return ""
    return "PROVEN HOOKS (from vault — use as exemplars, do not copy):\n" + \
           "\n".join(f"  - {h}" for h in hooks[:8])


def load_what_works(platform: str) -> str:
    """Per-platform performance patterns. Returns '' if file missing/empty."""
    name_map = {
        "instagram": "What Works - Instagram.md",
        "linkedin": "What Works - LinkedIn.md",
        "youtube_community": "What Works - YouTube.md",
    }
    fname = name_map.get(platform)
    if not fname:
        return ""
    md = _read(rf"Content\{fname}")
    if not md:
        return ""
    parts = []
    for section in ("Winning hook patterns", "Winning formats", "Caption patterns"):
        body = _section(md, section)
        lines = _strip_scaffold(body)
        if lines:
            parts.append(f"  {section}:")
            parts.extend(f"    {ln}" for ln in lines[:6])
    return (f"WHAT WORKS ON {platform.upper()} (from vault):\n" + "\n".join(parts)) if parts else ""


def load_icp() -> str:
    """Read Audience/ICP Profile.md — pain/triggers/where-they-hang-out."""
    md = _read(r"Audience\ICP Profile.md")
    if not md:
        return ""
    # ICP file uses nested ## structure; just keep its primary block lines that
    # aren't scaffold placeholders.
    body = _section(md, "Primary ICP — Hogtron Solutions") or md
    lines = _strip_scaffold(body)
    # Cut links/headings that snuck through
    lines = [ln for ln in lines if not ln.startswith("#") and not ln.startswith("[[")]
    if not lines:
        return ""
    return "ICP CONTEXT (from vault):\n" + "\n".join(f"  {ln}" for ln in lines[:20])


# --- Composite -----------------------------------------------------------

def build_voice_context_block(
    platform: Optional[str] = None,
    include: tuple[str, ...] = ("brand_voice", "audience_language", "hooks", "icp", "what_works"),
) -> str:
    """Build the full vault-derived context block, skipping empties.

    Pass `platform` to include the matching What Works file. Pass `include`
    to limit to specific sources (handy when a handler doesn't need the ICP,
    e.g. hashtag_pack).
    """
    blocks: list[str] = []
    if "brand_voice" in include:
        b = load_brand_voice()
        if b:
            blocks.append(b)
    if "audience_language" in include:
        b = load_audience_language()
        if b:
            blocks.append(b)
    if "hooks" in include:
        b = load_hook_swipes()
        if b:
            blocks.append(b)
    if "icp" in include:
        b = load_icp()
        if b:
            blocks.append(b)
    if "what_works" in include and platform:
        b = load_what_works(platform)
        if b:
            blocks.append(b)
    return "\n\n".join(blocks)
