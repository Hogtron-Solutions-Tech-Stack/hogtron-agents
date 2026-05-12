"""Recraft image generation client. Stateless; reads RECRAFT_API_KEY from env
unless explicitly passed.

Ported from FactoryHQ/tools/recraft.py — original lived in the Factory repo
and imported FactoryHQ's `config` module. This version is decoupled so
hogtron-dashboard, FactoryHQ, and future callers can all share it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://external.api.recraft.ai/v1"

DEFAULT_STYLE = "digital_illustration"
DEFAULT_SIZE = "1024x1024"
DEFAULT_MODEL = "recraftv3"


def _headers(api_key: Optional[str]) -> dict:
    key = api_key or os.environ.get("RECRAFT_API_KEY")
    if not key:
        raise RuntimeError(
            "RECRAFT_API_KEY not set. Pass api_key= or set the env var."
        )
    return {
        "Authorization": f"Bearer {key}",
        "User-Agent": "hogtron-agents/0.1",
    }


def generate(
    prompt: str,
    *,
    api_key: Optional[str] = None,
    style: str = DEFAULT_STYLE,
    substyle: Optional[str] = None,
    size: str = DEFAULT_SIZE,
    model: str = DEFAULT_MODEL,
    n: int = 1,
) -> dict:
    """Call Recraft /v1/images/generations.
    Returns {url, model, style, substyle, raw}.
    """
    payload = {"prompt": prompt, "style": style, "size": size, "model": model, "n": n}
    if substyle:
        payload["substyle"] = substyle

    resp = requests.post(
        f"{API_BASE}/images/generations",
        json=payload,
        headers=_headers(api_key),
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Recraft {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    images = data.get("data") or []
    if not images:
        raise RuntimeError(f"Recraft returned no images: {data}")
    return {
        "url": images[0].get("url") or images[0].get("image_url"),
        "model": model,
        "style": style,
        "substyle": substyle,
        "raw": data,
    }


def download(url: str, dest: Path) -> Path:
    """Stream-download a generated image. Returns the local path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                f.write(chunk)
    return dest
