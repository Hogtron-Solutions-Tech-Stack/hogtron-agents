"""Printify upload handler — upload art + create draft product.

Ported from FactoryHQ/agents/designer.py upload() (Phase 3) minus the DB
glue. Two external calls: upload_image, then create_product. Returns the
new product's image_id, product_id, and primary mockup URL.

Stateless: caller supplies the art file + product copy (title/description/
tags), gets back the external IDs. Caller persists the IDs.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

import requests

from .briefs import OperationsBrief, OperationsResult


PRINTIFY_API_BASE = "https://api.printify.com/v1"


def _headers(api_key: str, content_type: str = "application/json") -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type,
        "User-Agent": "hogtron-agents/0.1",
    }


def _upload_image(file_path: Path, file_name: str, api_key: str) -> dict:
    """Upload a local image to Printify's image library. Returns the image dict."""
    body = {
        "file_name": file_name,
        "contents": base64.b64encode(file_path.read_bytes()).decode("ascii"),
    }
    resp = requests.post(
        f"{PRINTIFY_API_BASE}/uploads/images.json",
        headers=_headers(api_key),
        json=body,
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Printify upload {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _create_product(
    *,
    shop_id: str,
    title: str,
    description: str,
    image_id: str,
    tags: list[str],
    image_y: float,
    blueprint_id: int,
    print_provider_id: int,
    variant_ids: list[int],
    api_key: str,
) -> dict:
    """Create a Printify draft product on the given blueprint + provider."""
    variants = [{"id": vid, "price": 2499, "is_enabled": True} for vid in variant_ids]
    print_areas = [{
        "variant_ids": variant_ids,
        "placeholders": [{
            "position": "front",
            "images": [{
                "id": image_id,
                "x": 0.5,
                "y": image_y,
                "scale": 1.0,
                "angle": 0,
            }],
        }],
    }]
    body = {
        "title": title,
        "description": description,
        "blueprint_id": blueprint_id,
        "print_provider_id": print_provider_id,
        "tags": tags,
        "variants": variants,
        "print_areas": print_areas,
    }
    resp = requests.post(
        f"{PRINTIFY_API_BASE}/shops/{shop_id}/products.json",
        headers=_headers(api_key),
        json=body,
        timeout=120,
    )
    if not resp.ok:
        raise RuntimeError(f"Printify create_product {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _primary_mockup_url(product: dict) -> Optional[str]:
    """Pull the first 'is_default' mockup URL from a Printify product response."""
    images = product.get("images") or []
    for img in images:
        if img.get("is_default"):
            return img.get("src")
    return images[0].get("src") if images else None


def printify_upload(brief: OperationsBrief) -> OperationsResult:
    """Upload art + create a Printify draft product.

    brief.payload:
      art_local_path (required) — local PNG to upload
      file_name (required) — what to name it in Printify's library
      shop_id (required) — Printify shop id
      title (required) — product title
      description (required) — product description
      tags (optional, default [])
      placement_y (optional, default 0.35) — vertical position on shirt
      blueprint_id (optional, default 384 = Bella+Canvas 3001)
      print_provider_id (optional, default 29 = Monster Digital)
      variant_ids (required) — sizes/colors to enable
    brief.context:
      printify_api_key (optional, falls back to env PRINTIFY_API_KEY)
    """
    required = ("art_local_path", "file_name", "shop_id", "title", "description", "variant_ids")
    missing = [k for k in required if not brief.payload.get(k)]
    if missing:
        raise ValueError(f"printify_upload brief.payload missing: {missing}")

    api_key = (
        brief.context.get("printify_api_key")
        or os.environ.get("PRINTIFY_API_KEY")
    )
    if not api_key:
        return OperationsResult(
            kind="printify_upload", success=False,
            error="PRINTIFY_API_KEY not set",
        )

    file_path = Path(brief.payload["art_local_path"])
    if not file_path.exists():
        return OperationsResult(
            kind="printify_upload", success=False,
            error=f"art_local_path does not exist: {file_path}",
        )

    try:
        up = _upload_image(file_path, brief.payload["file_name"], api_key)
        image_id = up.get("id")
        if not image_id:
            return OperationsResult(
                kind="printify_upload", success=False,
                error=f"Printify upload returned no image id: {up}",
            )

        product = _create_product(
            shop_id=str(brief.payload["shop_id"]),
            title=brief.payload["title"][:140],
            description=brief.payload["description"],
            image_id=image_id,
            tags=brief.payload.get("tags") or [],
            image_y=float(brief.payload.get("placement_y", 0.35)),
            blueprint_id=int(brief.payload.get("blueprint_id", 384)),
            print_provider_id=int(brief.payload.get("print_provider_id", 29)),
            variant_ids=[int(v) for v in brief.payload["variant_ids"]],
            api_key=api_key,
        )
    except Exception as e:
        return OperationsResult(
            kind="printify_upload", success=False,
            error=str(e)[:500],
        )

    product_id = product.get("id")
    mockup = _primary_mockup_url(product)

    return OperationsResult(
        kind="printify_upload",
        success=True,
        external_id=str(product_id),
        external_url=mockup,
        payload={
            "image_id": image_id,
            "product_id": str(product_id),
            "mockup_url": mockup,
            "shop_id": brief.payload["shop_id"],
        },
        metadata={
            "file_name": brief.payload["file_name"],
            "blueprint_id": int(brief.payload.get("blueprint_id", 384)),
            "n_variants": len(brief.payload["variant_ids"]),
        },
        cost_estimate_usd=0.0,  # Printify drafts are free; cost lands on Etsy publish
    )
