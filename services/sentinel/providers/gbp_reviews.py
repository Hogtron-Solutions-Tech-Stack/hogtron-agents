"""GBPReviewsClient — fetch + reply to Google Business Profile reviews.

Mirrors the shape of GoogleCalendarProvider (Protocol + Mock + Real).
Lives in the service layer so the hogtron-agents library doesn't pull
google-api-python-client as a core dep.

Auth model (per-tenant):
  Each tenant has their own OAuth refresh token (their GBP, their
  consent). For now tokens live in env vars keyed by tenant id:
      GBP_OAUTH_REFRESH_TOKEN__<TENANT_ID_UPPER_SNAKE>
  This mirrors the per-tenant deploy story until we move tenant
  configs to Supabase. The shared client_id + client_secret come from
  a single OAuth client (the GBP API doesn't require per-tenant
  clients).

API surface used:
  - list_reviews(location_id): GET .../{location}/reviews
  - post_reply(review_name, body): PUT .../{review_name}/reply
  - delete_reply(review_name): DELETE .../{review_name}/reply

Endpoints match what the legacy Hogtron-Tools/review-bot Node.js
script hit. If/when Google fully retires those, this is the swap
point — the rest of the Sentinel review pipeline doesn't change.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional, Protocol

# Lazy import — only triggered when GoogleGBPReviewsClient is used.
# Tests + the Mock impl run without google libs installed.


@dataclass
class Review:
    """One Google review. `name` is the API resource path
    (accounts/.../locations/.../reviews/...) — needed for posting
    replies. `reply` is None if no reply has been posted yet."""
    name: str
    rating: int                       # 1-5
    body: str = ""
    author_name: str = ""
    author_photo_url: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reply: Optional[str] = None       # existing reply body, if any
    reply_updated_at: Optional[datetime] = None

    @property
    def review_id(self) -> str:
        """Last segment of `name` — the bare review id."""
        return self.name.rsplit("/", 1)[-1]

    @property
    def needs_reply(self) -> bool:
        return not self.reply


class GBPReviewsClient(Protocol):
    """GBP reviews I/O contract."""

    def list_reviews(
        self,
        location_id: str,
        *,
        only_unanswered: bool = True,
        max_results: int = 100,
    ) -> list[Review]:
        ...

    def post_reply(self, review_name: str, body: str) -> Review:
        """Returns the review with the new reply populated."""
        ...

    def delete_reply(self, review_name: str) -> None:
        ...


# --- Mock implementation ------------------------------------------------

@dataclass
class MockGBPReviewsClient:
    """In-memory GBP. Used for tests + the sidecar's mock mode so we can
    exercise the full review-responder pipeline without OAuth.

    Seed with mock reviews via seed_review(); post_reply() mutates the
    in-memory state so subsequent list_reviews() reflects it."""
    _reviews: dict[str, dict[str, Review]] = field(default_factory=dict)

    def seed_review(self, location_id: str, review: Review) -> Review:
        self._reviews.setdefault(location_id, {})[review.name] = review
        return review

    def list_reviews(
        self,
        location_id: str,
        *,
        only_unanswered: bool = True,
        max_results: int = 100,
    ) -> list[Review]:
        loc = self._reviews.get(location_id, {})
        out = list(loc.values())
        if only_unanswered:
            out = [r for r in out if r.needs_reply]
        out.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc),
                 reverse=True)
        return out[:max_results]

    def post_reply(self, review_name: str, body: str) -> Review:
        # Find which location holds this review
        for loc_id, loc in self._reviews.items():
            if review_name in loc:
                loc[review_name].reply = body
                loc[review_name].reply_updated_at = datetime.now(timezone.utc)
                return loc[review_name]
        raise KeyError(f"review {review_name!r} not found in mock store")

    def delete_reply(self, review_name: str) -> None:
        for loc_id, loc in self._reviews.items():
            if review_name in loc:
                loc[review_name].reply = None
                loc[review_name].reply_updated_at = None
                return
        raise KeyError(f"review {review_name!r} not found in mock store")


# --- Real Google implementation -----------------------------------------

# Star rating strings the v4 API returns
_RATING_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _review_from_api(item: dict) -> Review:
    rating_raw = item.get("starRating", "")
    if isinstance(rating_raw, int):
        rating = rating_raw
    else:
        rating = _RATING_MAP.get(str(rating_raw).upper(), 0)

    reply = (item.get("reviewReply") or {}).get("comment")
    reply_updated = _parse_dt((item.get("reviewReply") or {}).get("updateTime"))

    reviewer = item.get("reviewer") or {}
    return Review(
        name=item.get("name", ""),
        rating=rating,
        body=item.get("comment", "") or "",
        author_name=reviewer.get("displayName", "") or "",
        author_photo_url=reviewer.get("profilePhotoUrl", "") or "",
        created_at=_parse_dt(item.get("createTime")),
        updated_at=_parse_dt(item.get("updateTime")),
        reply=reply,
        reply_updated_at=reply_updated,
    )


@dataclass
class GoogleGBPReviewsClient:
    """Real Google Business Profile reviews client.

    Each instance is bound to one tenant's OAuth refresh token.
    Construct via from_env(tenant_id) at request time; don't share
    instances across tenants.

    NOTE: GBP v4 is being phased out by Google. When it goes fully
    dark, the endpoints below need to move to
    `mybusinessreviewsmanagement.googleapis.com/v1`. The rest of the
    Sentinel pipeline is unaffected — only this class changes."""
    client_id: str
    client_secret: str
    refresh_token: str
    account_id: str   # the "accounts/xxx" prefix

    SCOPES = ["https://www.googleapis.com/auth/business.manage"]
    TOKEN_URI = "https://oauth2.googleapis.com/token"
    # Reviews endpoint base. Legacy v4 — see note above.
    BASE = "https://mybusiness.googleapis.com/v4"

    @classmethod
    def from_tenant_id(cls, tenant_id: str) -> "GoogleGBPReviewsClient":
        """Pull tenant-specific creds from env. Until we move to
        Supabase, per-tenant OAuth tokens live in env vars keyed by
        the tenant slug:

            GBP_OAUTH_CLIENT_ID
            GBP_OAUTH_CLIENT_SECRET
            GBP_OAUTH_REFRESH_TOKEN__<TENANT_ID_UPPER_SNAKE>
            GBP_ACCOUNT_ID__<TENANT_ID_UPPER_SNAKE>
        """
        key = tenant_id.upper().replace("-", "_")
        token = os.environ.get(f"GBP_OAUTH_REFRESH_TOKEN__{key}")
        account = os.environ.get(f"GBP_ACCOUNT_ID__{key}", "")
        if not token:
            raise RuntimeError(
                f"GBP_OAUTH_REFRESH_TOKEN__{key} not set — mint one with "
                f"`python -m services.sentinel.gbp_oauth_setup {tenant_id}`"
            )
        client_id = os.environ.get("GBP_OAUTH_CLIENT_ID", "")
        client_secret = os.environ.get("GBP_OAUTH_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            raise RuntimeError(
                "GBP_OAUTH_CLIENT_ID + GBP_OAUTH_CLIENT_SECRET must be set"
            )
        return cls(client_id=client_id, client_secret=client_secret,
                   refresh_token=token, account_id=account)

    def _client(self):
        """Build a fresh API client. Token refresh handled by
        google-auth library on each call."""
        # Lazy import so the library doesn't require google libs to
        # import this module.
        from google.oauth2.credentials import Credentials  # type: ignore

        return Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri=self.TOKEN_URI,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=self.SCOPES,
        )

    def _request(self, method: str, url: str, **kwargs) -> dict:
        """Authed request. google-auth handles refresh + 401 retry."""
        import requests  # already a transitive dep
        creds = self._client()
        # Force a refresh so the header has a fresh access token
        from google.auth.transport.requests import Request as GoogleReq  # type: ignore
        if not creds.token or creds.expired:
            creds.refresh(GoogleReq())
        headers = {
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
            **(kwargs.pop("headers", None) or {}),
        }
        resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
        if not resp.ok:
            raise RuntimeError(
                f"GBP {method} {url} -> {resp.status_code}: {resp.text[:300]}"
            )
        if resp.text.strip():
            return resp.json()
        return {}

    def list_reviews(
        self,
        location_id: str,
        *,
        only_unanswered: bool = True,
        max_results: int = 100,
    ) -> list[Review]:
        url = f"{self.BASE}/{self._location_path(location_id)}/reviews"
        out: list[Review] = []
        page_token: Optional[str] = None
        while True:
            params = {"pageSize": min(50, max_results - len(out))}
            if page_token:
                params["pageToken"] = page_token
            data = self._request("GET", url, params=params)
            for item in data.get("reviews", []):
                review = _review_from_api(item)
                if only_unanswered and not review.needs_reply:
                    continue
                out.append(review)
                if len(out) >= max_results:
                    return out
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    def post_reply(self, review_name: str, body: str) -> Review:
        url = f"{self.BASE}/{review_name}/reply"
        resp = self._request("PUT", url, json={"comment": body})
        # API returns the reply object only; fetch the review back to
        # get the updated state. Cheap because we know exactly which one.
        return Review(
            name=review_name,
            rating=0,
            body="",
            reply=resp.get("comment", body),
            reply_updated_at=_parse_dt(resp.get("updateTime")) or datetime.now(timezone.utc),
        )

    def delete_reply(self, review_name: str) -> None:
        url = f"{self.BASE}/{review_name}/reply"
        self._request("DELETE", url)

    def _location_path(self, location_id: str) -> str:
        """Normalise a location reference to the full
        accounts/.../locations/... path. Accepts either:
          - bare id "12345"
          - "locations/12345"
          - full "accounts/.../locations/12345"
        """
        if "/" in location_id and location_id.startswith("accounts/"):
            return location_id
        # Strip prefixes the caller may or may not include
        loc = re.sub(r"^locations/", "", location_id)
        if not self.account_id:
            raise RuntimeError(
                "GBP_ACCOUNT_ID__<tenant> required when passing a bare location id"
            )
        prefix = self.account_id
        if not prefix.startswith("accounts/"):
            prefix = f"accounts/{prefix}"
        return f"{prefix}/locations/{loc}"
