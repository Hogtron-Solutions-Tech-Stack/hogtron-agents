"""Aggregator audit report handler — builds the restaurant audit deliverable.

Ported from hogtron-dashboard/tools/aggregator_audit/generator.py
(`generate_audit`). Pure business logic: no LLM, no IO. Given a restaurant
profile + per-platform presence status, computes:

  - Per-platform display dicts (status, color, blurb, merchant signup link)
  - Revenue projection at low/mid/high tiers (with diminishing returns)
  - Competitive intel summary
  - Ranked HogTron service recommendations with pricing

Caller (dashboard route, future Sales agent loop) wraps this with a
restaurant lookup + platform_presence detection (Research department) + a
Jinja template render.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .briefs import SalesBrief, SalesAsset


# --- Platform registry --------------------------------------------------

PLATFORMS = ["doordash", "ubereats", "grubhub", "slice"]

PLATFORM_META = {
    "doordash": {
        "name":            "DoorDash",
        "color":           "#ff3008",
        "merchant_signup": "https://merchants.doordash.com/",
        "blurb":           "The largest U.S. food-delivery platform; 60% of the market in most metros.",
        "pizza_only":      False,
    },
    "ubereats": {
        "name":            "Uber Eats",
        "color":           "#06c167",
        "merchant_signup": "https://merchants.ubereats.com/",
        "blurb":           "Strong international + younger demographic; ~25% U.S. market share.",
        "pizza_only":      False,
    },
    "grubhub": {
        "name":            "Grubhub",
        "color":           "#f63440",
        "merchant_signup": "https://get.grubhub.com/",
        "blurb":           "Older platform with deep roots in the Northeast — Lehigh Valley adoption is high.",
        "pizza_only":      False,
    },
    "slice": {
        "name":            "Slice",
        "color":           "#ff9100",
        "merchant_signup": "https://slicelife.com/business",
        "blurb":           "Pizza-only marketplace; lower commission than DoorDash/UberEats. Worth listing for any pizzeria.",
        "pizza_only":      True,
    },
}

DEFAULT_HOGTRON_SETUP_FEE = 750
DEFAULT_HOGTRON_OPTIMIZATION_MONTHLY = 199

# Median-restaurant revenue lift benchmarks per platform per month, USD.
# Drawn from aggregated industry studies — restaurants joining a single
# platform report ~$2k/mo incremental revenue at the median.
_PER_PLATFORM_REVENUE_LIFT = {"low": 900, "mid": 2200, "high": 4500}

# Fudge factor — each additional platform adds diminishing returns
_DIMINISHING = [1.0, 0.85, 0.65, 0.45]


def _is_pizza_cuisine(cuisine: Optional[str]) -> bool:
    if not cuisine:
        return False
    c = cuisine.lower()
    return "pizza" in c or "pizzeria" in c or "italian" in c


def _platforms_for_cuisine(cuisine: Optional[str]) -> list[str]:
    is_pizza = _is_pizza_cuisine(cuisine)
    return [p for p in PLATFORMS if not PLATFORM_META[p]["pizza_only"] or is_pizza]


def aggregator_audit_report(brief: SalesBrief) -> SalesAsset:
    """Build a restaurant aggregator audit report deliverable.

    brief.payload:
      restaurant (required) — dict with at least {name, address, city, state, zip,
        phone, website, cuisine}
      platform_status (required) — {platform_slug: {listed, url, rating, review_count, notes}}
      competitor_count (optional, default 12)
      competitors_on_aggregators (optional, default 9)
      competitors_on_three_or_more (optional, default 5)
      median_competitor_platform_count (optional, default 3)
      hogtron_setup_fee (optional, default 750)
      hogtron_monthly_optimization (optional, default 199)
      prepared_by (optional, default 'Sean Bilger')
      prepared_for_meeting_date (optional)
    """
    restaurant = brief.payload.get("restaurant")
    if not restaurant:
        raise ValueError("aggregator_audit_report brief.payload must include 'restaurant'")
    platform_status = brief.payload.get("platform_status") or {}

    competitor_count = int(brief.payload.get("competitor_count", 12))
    competitors_on_aggregators = int(brief.payload.get("competitors_on_aggregators", 9))
    competitors_on_three_or_more = int(brief.payload.get("competitors_on_three_or_more", 5))
    median_competitor_platform_count = int(brief.payload.get("median_competitor_platform_count", 3))
    setup_fee = int(brief.payload.get("hogtron_setup_fee", DEFAULT_HOGTRON_SETUP_FEE))
    monthly = int(brief.payload.get("hogtron_monthly_optimization", DEFAULT_HOGTRON_OPTIMIZATION_MONTHLY))
    prepared_by = brief.payload.get("prepared_by") or "Sean Bilger"
    meeting_date = brief.payload.get("prepared_for_meeting_date")

    cuisine = (restaurant.get("cuisine") or "").strip()
    relevant = _platforms_for_cuisine(cuisine)

    per_platform = []
    listed_count = 0
    missing_platforms = []
    needs_optimization = []

    for slug in relevant:
        meta = PLATFORM_META[slug]
        status = (platform_status or {}).get(slug, {}) or {}
        listed = status.get("listed")

        if listed is True:
            listed_count += 1
            try:
                rating_f = float(status.get("rating")) if status.get("rating") is not None else None
            except (TypeError, ValueError):
                rating_f = None
            performance = "ok"
            if rating_f is not None and rating_f < 4.3:
                performance = "below_avg"
                needs_optimization.append(slug)
            per_platform.append({
                "slug": slug, "name": meta["name"], "color": meta["color"],
                "blurb": meta["blurb"], "merchant_signup": meta["merchant_signup"],
                "status": "listed",
                "url": status.get("url"), "rating": rating_f,
                "review_count": status.get("review_count"),
                "notes": status.get("notes"), "performance": performance,
            })
        elif listed is False:
            missing_platforms.append(slug)
            per_platform.append({
                "slug": slug, "name": meta["name"], "color": meta["color"],
                "blurb": meta["blurb"], "merchant_signup": meta["merchant_signup"],
                "status": "missing", "notes": status.get("notes"),
            })
        else:
            per_platform.append({
                "slug": slug, "name": meta["name"], "color": meta["color"],
                "blurb": meta["blurb"], "merchant_signup": meta["merchant_signup"],
                "status": "unknown",
            })

    n_missing = len(missing_platforms)
    n_optimization = len(needs_optimization)

    def _projection(tier: str) -> int:
        lift = _PER_PLATFORM_REVENUE_LIFT[tier]
        new_revenue = sum(
            lift * _DIMINISHING[min(i, len(_DIMINISHING) - 1)]
            for i in range(n_missing)
        )
        opt_lift = n_optimization * (lift * 0.25)
        return int(round(new_revenue + opt_lift))

    monthly_low = _projection("low")
    monthly_mid = _projection("mid")
    monthly_high = _projection("high")

    projection = {
        "low":  {"monthly": monthly_low,  "annual": monthly_low * 12},
        "mid":  {"monthly": monthly_mid,  "annual": monthly_mid * 12},
        "high": {"monthly": monthly_high, "annual": monthly_high * 12},
        "n_missing": n_missing, "n_optimization": n_optimization,
    }

    comp_intel = {
        "competitor_count": competitor_count,
        "competitors_on_aggregators": competitors_on_aggregators,
        "competitors_on_three_or_more": competitors_on_three_or_more,
        "median_competitor_platform_count": median_competitor_platform_count,
        "you_are_on": listed_count,
        "you_vs_median": listed_count - median_competitor_platform_count,
    }

    recommendations = []
    priority = 1
    for slug in missing_platforms:
        meta = PLATFORM_META[slug]
        recommendations.append({
            "priority": priority,
            "title": f"Join {meta['name']}",
            "service": f"HogTron Aggregator Setup — {meta['name']}",
            "price_setup": setup_fee,
            "price_monthly": None,
            "rationale": f"{meta['blurb']} Estimated incremental lift: ${_PER_PLATFORM_REVENUE_LIFT['mid']:,}/mo at the realistic tier.",
        })
        priority += 1

    if needs_optimization:
        names = ", ".join(PLATFORM_META[s]["name"] for s in needs_optimization)
        recommendations.append({
            "priority": priority,
            "title": f"Optimize {names} listing{'s' if len(needs_optimization) > 1 else ''}",
            "service": "HogTron Aggregator Optimization",
            "price_setup": None,
            "price_monthly": monthly,
            "rationale": (
                "Underperforming listings drag down search ranking on the platform. We refresh photos, "
                "rewrite descriptions, audit menu pricing for platform fees, and run optimization "
                "promos for the first 30 days."
            ),
        })

    fully_optimized = [p for p in per_platform if p["status"] == "listed" and p.get("performance") == "ok"]
    if fully_optimized and not needs_optimization:
        recommendations.append({
            "priority": priority + 1,
            "title": "Maintain your existing listings",
            "service": "HogTron Listing Monitoring (light touch)",
            "price_setup": None,
            "price_monthly": 49,
            "rationale": (
                "Aggregator listings drift over time — menu prices change, hours shift, photos go stale. "
                "We monitor monthly and flag updates needed."
            ),
        })

    report = {
        "restaurant": restaurant,
        "per_platform": per_platform,
        "summary": {
            "listed_count": listed_count,
            "total_relevant": len(relevant),
            "missing_count": n_missing,
            "needs_optimization": n_optimization,
            "biggest_opportunity": missing_platforms[0] if missing_platforms else None,
        },
        "competitive_intel": comp_intel,
        "projection": projection,
        "recommendations": recommendations,
        "meta": {
            "prepared_by": prepared_by,
            "prepared_at": datetime.utcnow().strftime("%B %d, %Y"),
            "prepared_for_meeting_date": meeting_date,
            "platforms_checked": [PLATFORM_META[s]["name"] for s in relevant],
        },
    }

    biggest = report["summary"]["biggest_opportunity"]
    summary = (
        f"{restaurant.get('name', 'Unknown')}: on {listed_count}/{len(relevant)} platforms"
        + (f", biggest gap = {PLATFORM_META[biggest]['name']}" if biggest else "")
        + f", projected mid-tier lift ${monthly_mid:,}/mo"
    )

    return SalesAsset(
        kind="aggregator_audit_report",
        summary=summary,
        payload=report,
        metadata={
            "n_listed": listed_count,
            "n_missing": n_missing,
            "n_optimization": n_optimization,
            "projection_mid_monthly": monthly_mid,
        },
    )
