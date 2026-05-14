"""PayPal REST API — list inbound transactions for revenue tracking.

Ported from hogtron-dashboard/tools/paypal_sync.py (2026-05-13). Owned by
the Ledger department going forward; the dashboard's `routes/payments.py`
imports `list_transactions` from here.

Read-only against the PayPal API:
- OAuth2 token at /v1/oauth2/token
- Transaction Search at /v1/reporting/transactions

Credentials are passed in (don't read env directly — keeps the agent
package free of dashboard-specific config). The dashboard adapter in
hogtron-dashboard/tools/paypal_sync.py supplies them from config.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import requests


LIVE_BASE    = "https://api-m.paypal.com"
SANDBOX_BASE = "https://api-m.sandbox.paypal.com"


def _base_url(mode: str) -> str:
    return SANDBOX_BASE if mode == "sandbox" else LIVE_BASE


def get_access_token(client_id: str, client_secret: str,
                     mode: str = "live") -> str:
    """Trade client_id + client_secret for a short-lived bearer token."""
    if not (client_id and client_secret):
        raise ValueError(
            "PayPal API credentials missing. "
            "Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env."
        )
    resp = requests.post(
        f"{_base_url(mode)}/v1/oauth2/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        timeout=20,
    )
    if resp.status_code in (401, 403):
        raise ValueError(
            "PayPal rejected your API credentials — "
            "check PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
        )
    resp.raise_for_status()
    return resp.json()["access_token"]


def list_transactions(client_id: str, client_secret: str, *,
                      mode: str = "live", days: int = 30) -> list[dict]:
    """Return inbound transactions from the last `days` days, normalized.

    Each row: {
      txn_id, paid_at, amount, currency, payer_email, payer_name, note,
      status, raw
    }
    Only returns transactions where money came IN (positive value).
    """
    token = get_access_token(client_id, client_secret, mode=mode)

    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=min(days, 31))  # PayPal caps single requests to 31d

    url = f"{_base_url(mode)}/v1/reporting/transactions"
    params = {
        "start_date": start.strftime("%Y-%m-%dT%H:%M:%S-0000"),
        "end_date":   end.strftime("%Y-%m-%dT%H:%M:%S-0000"),
        "fields":     "all",
        "page_size":  100,
        "page":       1,
    }

    out: list[dict] = []
    while True:
        resp = requests.get(
            url, params=params,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code == 400:
            try:
                err = resp.json()
            except Exception:
                err = {"error": resp.text[:200]}
            raise RuntimeError(
                "PayPal returned 400 — your account may need 'Transaction "
                "Search' enabled in your developer app's Live API features. "
                "Detail: " + str(err)
            )
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("transaction_details", []) or []:
            info = t.get("transaction_info") or {}
            payer = t.get("payer_info") or {}
            amt   = info.get("transaction_amount") or {}
            value = float(amt.get("value") or 0)

            if value <= 0:
                continue  # skip refunds and outbound transfers

            out.append({
                "txn_id":      info.get("transaction_id"),
                "paid_at":     info.get("transaction_initiation_date"),
                "amount":      value,
                "currency":    amt.get("currency_code") or "USD",
                "payer_email": payer.get("email_address") or "",
                "payer_name":  ((payer.get("payer_name") or {}).get("alternate_full_name")
                                or (payer.get("payer_name") or {}).get("given_name", "")),
                "note":        info.get("transaction_note") or info.get("transaction_subject") or "",
                "status":      info.get("transaction_status"),
                "raw":         t,
            })

        page = data.get("page", 1)
        total_pages = data.get("total_pages", 1)
        if page >= total_pages:
            break
        params["page"] = page + 1

    return out


def filter_unmatched(transactions: list[dict],
                     existing_external_ids: set[str]) -> list[dict]:
    """Return only transactions we haven't already imported."""
    return [t for t in transactions
            if t.get("txn_id") and t["txn_id"] not in existing_external_ids]


def total_inbound(transactions: list[dict]) -> float:
    """Sum the `amount` field across a list of normalized transactions."""
    return round(sum(float(t.get("amount") or 0) for t in transactions), 2)
