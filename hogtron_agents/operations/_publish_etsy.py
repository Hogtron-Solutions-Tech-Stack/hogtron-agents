"""Publish-to-Etsy handler — push a Printify draft product to its linked Etsy shop.

Ported from FactoryHQ/agents/marketer.py publish(). Single Printify API call
to publish_product; Printify forwards to Etsy and back-fills the external
listing URL asynchronously.

Cost note: $0.20 per published Etsy listing + 6.5% transaction fee on sales.
Layer 3 caps will count these.
"""
from __future__ import annotations

import os

import requests

from .briefs import OperationsBrief, OperationsResult


PRINTIFY_API_BASE = "https://api.printify.com/v1"

# Per-listing fee Etsy charges to publish, in USD. Used for cost_estimate.
ETSY_LISTING_FEE_USD = 0.20


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "hogtron-agents/0.1",
    }


def publish_etsy(brief: OperationsBrief) -> OperationsResult:
    """Push an existing Printify draft to its linked Etsy shop.

    brief.payload:
      product_id (required) — Printify product id to publish
      shop_id (optional, falls back to env PRINTIFY_SHOP_ID)
      title / description / images / variants / tags (optional bool flags, default True)
    brief.context:
      printify_api_key (optional, falls back to env PRINTIFY_API_KEY)
    """
    product_id = brief.payload.get("product_id")
    if not product_id:
        raise ValueError("publish_etsy brief.payload must include 'product_id'")

    shop_id = brief.payload.get("shop_id") or os.environ.get("PRINTIFY_SHOP_ID")
    if not shop_id:
        return OperationsResult(
            kind="publish_etsy", success=False,
            error="shop_id not in payload and PRINTIFY_SHOP_ID not in env",
        )

    api_key = (
        brief.context.get("printify_api_key")
        or os.environ.get("PRINTIFY_API_KEY")
    )
    if not api_key:
        return OperationsResult(
            kind="publish_etsy", success=False,
            error="PRINTIFY_API_KEY not set",
        )

    body = {
        "title": brief.payload.get("title", True),
        "description": brief.payload.get("description", True),
        "images": brief.payload.get("images", True),
        "variants": brief.payload.get("variants", True),
        "tags": brief.payload.get("tags", True),
        "keyFeatures": True,
        "shipping_template": True,
    }
    url = f"{PRINTIFY_API_BASE}/shops/{shop_id}/products/{product_id}/publish.json"

    try:
        resp = requests.post(url, headers=_headers(api_key), json=body, timeout=60)
    except requests.RequestException as e:
        return OperationsResult(
            kind="publish_etsy", success=False,
            error=f"network: {e}",
        )

    if not resp.ok:
        return OperationsResult(
            kind="publish_etsy", success=False,
            error=f"Printify publish {resp.status_code}: {resp.text[:300]}",
        )

    # Printify returns 200 OK with no body on success. The external Etsy URL
    # is populated asynchronously — caller polls get_product later to hydrate.
    return OperationsResult(
        kind="publish_etsy",
        success=True,
        external_id=str(product_id),
        external_url=None,  # hydrated later via get_product().external.handle
        payload={
            "shop_id": str(shop_id),
            "product_id": str(product_id),
            "note": "Etsy URL hydrates asynchronously via Printify; poll get_product to retrieve.",
        },
        cost_estimate_usd=ETSY_LISTING_FEE_USD,
    )
