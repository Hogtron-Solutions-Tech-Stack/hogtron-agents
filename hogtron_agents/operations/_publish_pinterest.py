"""Publish-to-Pinterest handler — create a pin on a board.

Ported from FactoryHQ/agents/pinterester.py + tools/pinterest.py (Pinterest API
v5 create-pin call). The Claude copy generation lives in
hogtron_agents.marketing._social_post — this handler just posts the result.

Pinterest API v5 spec:
  POST /v5/pins
  {
    board_id: ..., title: ..., description: ..., link: ...,
    media_source: { source_type: "image_url", url: ... },
    alt_text: ...
  }
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from .briefs import OperationsBrief, OperationsResult


PINTEREST_API_BASE = "https://api.pinterest.com/v5"


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "hogtron-agents/0.1",
    }


def _pin_public_url(pin: dict) -> Optional[str]:
    """Pinterest's response includes the id; pin permalink follows /pin/<id>/."""
    pid = pin.get("id")
    if not pid:
        return None
    return f"https://www.pinterest.com/pin/{pid}/"


def publish_pinterest(brief: OperationsBrief) -> OperationsResult:
    """Create a Pinterest pin linking back to an external destination.

    brief.payload:
      board_id (required) — destination Pinterest board id
      title (required, max 100)
      description (required, max 500)
      link (required) — destination URL (typically the Etsy listing)
      image_url (required) — pin image URL (Printify mockup, etc.)
      alt_text (optional, max 200)
    brief.context:
      pinterest_access_token (optional, falls back to env PINTEREST_ACCESS_TOKEN)
    """
    required = ("board_id", "title", "description", "link", "image_url")
    missing = [k for k in required if not brief.payload.get(k)]
    if missing:
        raise ValueError(f"publish_pinterest brief.payload missing: {missing}")

    token = (
        brief.context.get("pinterest_access_token")
        or os.environ.get("PINTEREST_ACCESS_TOKEN")
    )
    if not token:
        return OperationsResult(
            kind="publish_pinterest", success=False,
            error="PINTEREST_ACCESS_TOKEN not set",
        )

    body = {
        "board_id": brief.payload["board_id"],
        "title": brief.payload["title"][:100],
        "description": brief.payload["description"][:500],
        "link": brief.payload["link"],
        "media_source": {
            "source_type": "image_url",
            "url": brief.payload["image_url"],
        },
    }
    if brief.payload.get("alt_text"):
        body["alt_text"] = brief.payload["alt_text"][:200]

    try:
        resp = requests.post(
            f"{PINTEREST_API_BASE}/pins",
            headers=_headers(token),
            json=body,
            timeout=60,
        )
    except requests.RequestException as e:
        return OperationsResult(
            kind="publish_pinterest", success=False,
            error=f"network: {e}",
        )

    if not resp.ok:
        return OperationsResult(
            kind="publish_pinterest", success=False,
            error=f"Pinterest {resp.status_code}: {resp.text[:300]}",
        )

    pin = resp.json()
    pin_id = pin.get("id")
    pin_url = _pin_public_url(pin)

    return OperationsResult(
        kind="publish_pinterest",
        success=True,
        external_id=pin_id,
        external_url=pin_url,
        payload={
            "pin_id": pin_id,
            "pin_url": pin_url,
            "board_id": brief.payload["board_id"],
            "link": brief.payload["link"],
        },
        cost_estimate_usd=0.0,  # Pinterest API is free
    )
