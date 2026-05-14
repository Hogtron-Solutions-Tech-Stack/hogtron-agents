"""Railway usage — pull per-service spend via the GraphQL API.

Endpoint: https://backboard.railway.app/graphql/v2
Auth: `Authorization: Bearer <RAILWAY_TOKEN>` (Team Token or Project Token)

Railway's billing data lives behind the `me { teams }` and `usage` queries.
We keep this minimal — total month-to-date USD per service. Phase 2 can
add per-day buckets if we ever need a trend chart.

The caller passes in the token + (optional) team id. Returns plain dicts so
LedgerAsset.payload can carry them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import requests


GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"


def _query(token: str, query: str, variables: dict | None = None,
           timeout: int = 20) -> dict[str, Any]:
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise ValueError(
            "Railway rejected the API token — check RAILWAY_TOKEN scope "
            "(Team Token recommended for usage queries)."
        )
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Railway GraphQL error: {body['errors']}")
    return body.get("data") or {}


def list_projects(token: str) -> list[dict]:
    """Return projects visible to the token: [{id, name, team_id}, ...]."""
    data = _query(token, """
        query Projects {
          projects { edges { node { id name team { id } } } }
        }
    """)
    edges = ((data.get("projects") or {}).get("edges")) or []
    out = []
    for e in edges:
        n = e.get("node") or {}
        out.append({
            "id":      n.get("id"),
            "name":    n.get("name"),
            "team_id": ((n.get("team") or {}).get("id")),
        })
    return out


def month_to_date_usage(token: str, *,
                        team_id: Optional[str] = None) -> dict[str, Any]:
    """Pull month-to-date usage in USD, bucketed by service.

    Railway's `usage` query returns measurements across multiple metrics
    (CPU/memory/network/storage). We normalize into a USD estimate per
    service. Schema specifics shift periodically — when the shape changes,
    update the query + parser here.

    Returns:
      {
        period: 'YYYY-MM',
        total_usd: float,
        by_service: [{project_id, service_id, service_name, usd}, ...],
        pulled_at: ISO timestamp,
        raw: <underlying response>,  # for debugging / future fields
      }
    """
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0,
                         microsecond=0).isoformat()
    end = now.isoformat()

    variables: dict[str, Any] = {
        "measurements": ["ESTIMATED_USAGE_USD"],
        "startDate": start,
        "endDate":   end,
        "groupBy":   ["SERVICE_ID"],
    }
    if team_id:
        variables["teamId"] = team_id

    data = _query(token, """
        query Usage($measurements: [MetricMeasurement!]!,
                    $startDate: DateTime!, $endDate: DateTime!,
                    $groupBy: [MetricTag!]!, $teamId: String) {
          usage(
            measurements: $measurements,
            startDate: $startDate,
            endDate: $endDate,
            groupBy: $groupBy,
            teamId: $teamId
          ) {
            measurement
            value
            tags { serviceId projectId }
          }
        }
    """, variables=variables)

    rows = data.get("usage") or []
    by_service: list[dict] = []
    total = 0.0
    for r in rows:
        value = float(r.get("value") or 0)
        tags = r.get("tags") or {}
        by_service.append({
            "project_id":   tags.get("projectId"),
            "service_id":   tags.get("serviceId"),
            "service_name": tags.get("serviceId"),  # name resolution TBD; falls back to id
            "usd":          round(value, 4),
        })
        total += value

    return {
        "period":     now.strftime("%Y-%m"),
        "total_usd":  round(total, 4),
        "by_service": by_service,
        "pulled_at":  now.isoformat(),
        "raw":        rows,
    }
