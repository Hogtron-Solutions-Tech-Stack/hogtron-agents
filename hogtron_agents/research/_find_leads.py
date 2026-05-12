"""Find-leads handler — Google Places primary, OpenStreetMap fallback.

Ported from hogtron-dashboard/tools/lead_scraper.py. V1 scope:
  - Google Places Text Search (New API) when GOOGLE_PLACES_API_KEY is set
  - OSM Overpass fallback otherwise (free, no key, thinner data)

Skipped in v1 (will land later as Operations or extended Research):
  - Foursquare (provider chain extension)
  - Apify Google Maps (paid, slow, email-bundled)
  - Email enrichment from scraped websites (per-lead extra hop)

Stateless: caller supplies industry + location, gets back lead records.
"""
from __future__ import annotations

import os
import time
from typing import Optional
from urllib.parse import quote_plus

import requests

from .briefs import ResearchBrief, ResearchFinding


# --- Google Places (New API) -------------------------------------------

_GOOGLE_FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.addressComponents", "places.nationalPhoneNumber",
    "places.websiteUri", "places.rating", "places.userRatingCount",
    "places.types", "places.primaryType", "nextPageToken",
])


def _strip_county_suffix(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.replace(" County", "").strip()


def _scrape_google(industry: str, location_phrase: str, limit: int,
                   api_key: str) -> list[dict]:
    query = f"{industry} in {location_phrase}".strip() if industry else f"businesses in {location_phrase}"
    url = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _GOOGLE_FIELD_MASK,
    }
    leads = []
    page_token = None
    for _ in range(20):
        body = {"textQuery": query, "pageSize": 20}
        if page_token:
            body["pageToken"] = page_token
        resp = requests.post(url, json=body, headers=headers, timeout=20)
        if resp.status_code in (401, 403):
            raise ValueError("Google Places rejected the API key — check Places API (New) is enabled.")
        resp.raise_for_status()
        data = resp.json()

        for p in data.get("places", []) or []:
            phone = p.get("nationalPhoneNumber")
            website = p.get("websiteUri")
            if not phone and not website:
                continue
            comps = {c["types"][0]: c for c in (p.get("addressComponents") or []) if c.get("types")}
            primary_type = p.get("primaryType") or ((p.get("types") or [None])[0])
            leads.append({
                "business_name": (p.get("displayName") or {}).get("text") or "(unknown)",
                "industry": industry or (primary_type.replace("_", " ") if primary_type else None),
                "address": p.get("formattedAddress"),
                "city": (comps.get("locality") or {}).get("longText"),
                "state": (comps.get("administrative_area_level_1") or {}).get("shortText"),
                "zip": (comps.get("postal_code") or {}).get("longText"),
                "county": _strip_county_suffix((comps.get("administrative_area_level_2") or {}).get("longText")),
                "phone": phone,
                "website": website,
                "rating": p.get("rating"),
                "review_count": p.get("userRatingCount"),
                "google_place_id": p.get("id"),
                "source": "google",
            })
            if len(leads) >= limit:
                break
        if len(leads) >= limit:
            break
        page_token = data.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.5)
    return leads


# --- OSM Overpass fallback ---------------------------------------------

# Loose industry -> OSM tag map. Caller can pass a literal OSM filter via
# brief.payload['osm_filter'] to override.
_INDUSTRY_TO_OSM: dict[str, tuple[str, Optional[str]]] = {
    "pizzeria": ("amenity", "restaurant"),
    "restaurant": ("amenity", "restaurant"),
    "plumber": ("craft", "plumber"),
    "electrician": ("craft", "electrician"),
    "salon": ("shop", "hairdresser"),
    "barbershop": ("shop", "hairdresser"),
    "auto repair": ("shop", "car_repair"),
    "hvac": ("craft", "hvac"),
}


def _osm_geocode(location_phrase: str) -> Optional[tuple[float, float, float, float]]:
    """Nominatim geocode -> (min_lat, min_lon, max_lat, max_lon) bbox."""
    url = f"https://nominatim.openstreetmap.org/search?q={quote_plus(location_phrase)}&format=json&limit=1"
    resp = requests.get(url, headers={"User-Agent": "hogtron-agents/0.1"}, timeout=15)
    resp.raise_for_status()
    rows = resp.json() or []
    if not rows:
        return None
    bb = rows[0].get("boundingbox") or []
    if len(bb) != 4:
        return None
    # Nominatim returns [min_lat, max_lat, min_lon, max_lon] as strings
    return (float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3]))


def _industry_to_osm_filter(industry: str) -> tuple[str, Optional[str]]:
    """Return (key, value) for OSM filter. Falls through to ('shop', None) if
    industry isn't mapped — broader filter, more noise."""
    key = (industry or "").lower().strip()
    return _INDUSTRY_TO_OSM.get(key, ("shop", None))


def _scrape_osm(industry: str, location_phrase: str, limit: int) -> list[dict]:
    bbox = _osm_geocode(location_phrase)
    if bbox is None:
        return []
    min_lat, min_lon, max_lat, max_lon = bbox

    key, value = _industry_to_osm_filter(industry)
    selector = f'["{key}"]' if value is None else f'["{key}"="{value}"]'
    query = (
        f"[out:json][timeout:25];"
        f"("
        f"  node{selector}({min_lat},{min_lon},{max_lat},{max_lon});"
        f"  way{selector}({min_lat},{min_lon},{max_lat},{max_lon});"
        f");"
        f"out center {limit};"
    )
    resp = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": query},
        headers={"User-Agent": "hogtron-agents/0.1"},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json() or {}

    leads = []
    for el in data.get("elements", []) or []:
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        phone = tags.get("phone") or tags.get("contact:phone")
        website = tags.get("website") or tags.get("contact:website")
        if not phone and not website:
            continue
        addr_parts = []
        for tk in ("addr:housenumber", "addr:street", "addr:city", "addr:state", "addr:postcode"):
            v = tags.get(tk)
            if v:
                addr_parts.append(v)
        leads.append({
            "business_name": name,
            "industry": industry or tags.get(key) or None,
            "address": " ".join(addr_parts) or None,
            "city": tags.get("addr:city"),
            "state": tags.get("addr:state"),
            "zip": tags.get("addr:postcode"),
            "phone": phone,
            "website": website,
            "rating": None,
            "review_count": None,
            "osm_id": el.get("id"),
            "source": "osm",
        })
        if len(leads) >= limit:
            break
    return leads


# --- Location-phrase helper --------------------------------------------

def _location_phrase(payload: dict) -> str:
    """Convert payload geo fields into a human location phrase for queries."""
    zip_ = (payload.get("zip") or "").strip()
    city = (payload.get("city") or "").strip()
    state = (payload.get("state") or "").strip()
    county = (payload.get("county") or "").strip()
    if zip_:
        return zip_
    if city and state:
        return f"{city}, {state}"
    if county and state:
        return f"{county} County, {state}"
    return ""


# --- Public handler -----------------------------------------------------

def find_leads(brief: ResearchBrief) -> ResearchFinding:
    """Find local businesses by industry + location.

    brief.payload:
      industry (str, required)
      zip      (str, optional)
      city     (str, optional)
      state    (str, optional)
      county   (str, optional)
      limit    (int, default 20)
    brief.context:
      google_places_api_key (optional, falls back to env GOOGLE_PLACES_API_KEY)

    Provider chain: Google Places (if key) → OSM Overpass (free, thinner data).
    """
    industry = (brief.payload.get("industry") or "").strip()
    if not industry:
        raise ValueError("find_leads brief.payload must include 'industry'")
    location_phrase = _location_phrase(brief.payload)
    if not location_phrase:
        raise ValueError("find_leads requires zip OR city+state OR county+state in payload")
    limit = int(brief.payload.get("limit") or 20)

    google_key = (
        brief.context.get("google_places_api_key")
        or os.environ.get("GOOGLE_PLACES_API_KEY")
    )

    source = None
    leads: list[dict] = []
    errors: list[str] = []

    if google_key:
        try:
            leads = _scrape_google(industry, location_phrase, limit, google_key)
            source = "google"
        except Exception as e:
            errors.append(f"google: {e}")

    if not leads:
        try:
            leads = _scrape_osm(industry, location_phrase, limit)
            source = source or "osm"
        except Exception as e:
            errors.append(f"osm: {e}")

    return ResearchFinding(
        kind="find_leads",
        status="ok" if leads else "error" if errors else "ok",
        payload={"leads": leads, "errors": errors},
        metadata={
            "source": source,
            "n_leads": len(leads),
            "industry": industry,
            "location": location_phrase,
        },
        reason=(
            f"{len(leads)} leads via {source}"
            if leads else
            f"no leads; errors: {errors}" if errors else "no leads"
        ),
    )
