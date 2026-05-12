"""GEO audit handler — wraps the deployed GEO Auditor service.

The auditor itself (scraping, AI scoring) lives at the geo-auditor-aryw
Render service. This handler is just the typed thin client.

Ported from hogtron-dashboard/tools/geo_audit.py.
"""
from __future__ import annotations

import os
from typing import Optional

import requests

from .briefs import ResearchBrief, ResearchFinding

DEFAULT_AUDITOR_URL = "https://geo-auditor-aryw.onrender.com"


def geo_audit(brief: ResearchBrief) -> ResearchFinding:
    """Run GEO audit on a URL via the deployed service.

    brief.payload:
      url (required)
    brief.context:
      geo_auditor_url (optional, falls back to env GEO_AUDITOR_URL, then default)
    """
    url = (brief.payload.get("url") or "").strip()
    if not url:
        raise ValueError("geo_audit brief.payload must include 'url'")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    base = (
        brief.context.get("geo_auditor_url")
        or os.environ.get("GEO_AUDITOR_URL")
        or DEFAULT_AUDITOR_URL
    )
    endpoint = f"{base.rstrip('/')}/api/audit"

    try:
        resp = requests.post(endpoint, json={"url": url}, timeout=120)
    except requests.RequestException as e:
        return ResearchFinding(
            kind="geo_audit",
            status="error",
            reason=f"network error: {e}",
            payload={"url": url},
        )

    if resp.status_code >= 400:
        try:
            err = resp.json().get("error") or resp.text
        except Exception:
            err = resp.text
        return ResearchFinding(
            kind="geo_audit",
            status="error",
            reason=f"auditor returned {resp.status_code}: {err[:200]}",
            payload={"url": url},
        )

    data = resp.json()
    audit = data.get("audit", {}) or {}
    return ResearchFinding(
        kind="geo_audit",
        status="ok",
        payload=data,
        metadata={
            "url": url,
            "overall_score": audit.get("overall_score"),
            "overall_grade": audit.get("overall_grade"),
        },
    )
