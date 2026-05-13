"""Render-video handler — Ken Burns vertical MP4 from a product mockup.

Ported from FactoryHQ/tools/video.py + agents/distributor.py compose().
Self-contained ffmpeg + PIL composition. No external service calls — this
is purely local compute, but it lives in Operations because the output
is *delivered* (uploaded to Pinterest/TikTok/Reels in later kinds).

Composition recipe (v1):
  1. Render the phrase as a transparent PNG overlay using PIL
  2. ffmpeg filter graph:
     - 1080x1920 navy background
     - mockup centered + slow Ken Burns zoom
     - phrase overlay anchored to bottom with brand stripe
     - 5 seconds, 30fps, h264 yuv420p

Output goes to a caller-specified path (or a default cache).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

from .briefs import OperationsBrief, OperationsResult


FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

_DEFAULT_CACHE = Path(os.environ.get(
    "HOGTRON_VIDEO_CACHE",
    str(Path.home() / ".hogtron" / "video_cache"),
))

# Brand constants (kept local for fewer cross-module dependencies; in sync
# with hogtron_agents._shared.brand)
_NAVY_HEX = "0x0a1628"
_NAVY_RGBA = (10, 22, 40, 200)
_CYAN_RGBA = (0x22, 0xd3, 0xee, 255)
_GOLD_RGBA = (0xfb, 0xbf, 0x24, 255)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """Try common cross-platform font paths before falling back to default."""
    for candidate in [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _render_text_overlay(phrase: str, footer_text: str,
                         width: int = 1080, height: int = 220) -> Path:
    """Generate a transparent PNG with the phrase + brand footer."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Translucent brand stripe
    draw.rectangle([(0, 0), (width, height)], fill=_NAVY_RGBA)
    # Top cyan accent line
    draw.rectangle([(0, 0), (width, 4)], fill=_CYAN_RGBA)

    # Phrase — auto-shrink if too wide
    font_size = 64
    font = _find_font(font_size)
    while font_size > 30:
        bbox = draw.textbbox((0, 0), phrase, font=font)
        if bbox[2] - bbox[0] <= width - 80:
            break
        font_size -= 4
        font = _find_font(font_size)

    bbox = draw.textbbox((0, 0), phrase, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(
        ((width - tw) / 2, 30),
        phrase,
        font=font,
        fill=(255, 255, 255, 255),
    )

    # Brand footer line
    small = _find_font(22)
    sub_bbox = draw.textbbox((0, 0), footer_text, font=small)
    sw = sub_bbox[2] - sub_bbox[0]
    draw.text(
        ((width - sw) / 2, height - 40),
        footer_text,
        font=small,
        fill=_GOLD_RGBA,
    )

    tmp = Path(tempfile.gettempdir()) / f"hogtron_overlay_{abs(hash(phrase))}.png"
    img.save(tmp, "PNG")
    return tmp


def render_video(brief: OperationsBrief) -> OperationsResult:
    """Compose a 1080x1920 vertical MP4 from a product mockup + phrase.

    brief.payload:
      mockup_path (required) — local image file (Printify mockup, etc.)
      phrase (required) — overlay text shown at bottom
      design_id (optional) — used in filename
      out_path (optional) — full output path; defaults to cache_dir/design_<id>_v1.mp4
      duration_sec (optional, default 5)
      footer_text (optional, default 'HOGTRON FACTORY  •  COTTONFORGEBOUTIQUE.ETSY.COM')
    brief.context:
      cache_dir (optional, falls back to ~/.hogtron/video_cache)
    """
    required = ("mockup_path", "phrase")
    missing = [k for k in required if not brief.payload.get(k)]
    if missing:
        raise ValueError(f"render_video brief.payload missing: {missing}")

    mockup_path = Path(brief.payload["mockup_path"])
    if not mockup_path.exists():
        return OperationsResult(
            kind="render_video", success=False,
            error=f"mockup not found: {mockup_path}",
        )

    phrase = brief.payload["phrase"]
    design_id = brief.payload.get("design_id") or "adhoc"
    duration_sec = int(brief.payload.get("duration_sec") or 5)
    footer = brief.payload.get(
        "footer_text",
        "HOGTRON FACTORY  •  COTTONFORGEBOUTIQUE.ETSY.COM",
    )

    out_path = brief.payload.get("out_path")
    if out_path is None:
        cache_dir = Path(brief.context.get("cache_dir") or _DEFAULT_CACHE)
        cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = cache_dir / f"design_{design_id}_v1.mp4"
    out_path = Path(out_path)

    overlay = _render_text_overlay(phrase, footer)

    fps = 30
    total_frames = duration_sec * fps
    W, H = 1080, 1920

    filter_complex = (
        f"[0:v]scale=900:900:force_original_aspect_ratio=decrease,"
        f"pad=900:900:(ow-iw)/2:(oh-ih)/2:color={_NAVY_HEX},"
        f"zoompan=z='min(zoom+0.0008,1.15)':d={total_frames}:s=900x900[zoom];"
        f"[1:v][zoom]overlay=(W-w)/2:(H-h)/2-180[bg];"
        f"[bg][2:v]overlay=0:H-h[out]"
    )

    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-t", str(duration_sec), "-framerate", str(fps),
        "-i", str(mockup_path),
        "-f", "lavfi", "-t", str(duration_sec),
        "-i", f"color=c={_NAVY_HEX}:s={W}x{H}:r={fps}",
        "-loop", "1", "-t", str(duration_sec),
        "-i", str(overlay),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-t", str(duration_sec),
        "-preset", "veryfast", "-crf", "20",
        "-movflags", "+faststart",
        str(out_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return OperationsResult(
            kind="render_video", success=False,
            error=f"ffmpeg failed: {result.stderr[-500:]}",
        )

    return OperationsResult(
        kind="render_video",
        success=True,
        external_id=None,
        external_url=None,
        payload={
            "path": str(out_path),
            "width": W,
            "height": H,
            "duration_sec": duration_sec,
        },
        metadata={
            "phrase": phrase,
            "design_id": design_id,
            "footer": footer,
        },
        cost_estimate_usd=0.0,  # local ffmpeg compute, no spend
    )
