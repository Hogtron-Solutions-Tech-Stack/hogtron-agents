"""Sentinel sidecar Slack notifier.

Best-effort notifications for inbound leads + review approval queue.
Failures never propagate (Sentinel must keep working if Slack is down).

The shape of each notification is a dict; this module renders them to
Slack messages and posts them. Each different `kind` of notification
gets its own dedicated formatter so the messages read naturally.

Routing:
  capacity_audit / contact_form / generic lead  →  SLACK_LEADS_INBOUND_CHANNEL
  review_response_draft_pending_approval         →  SLACK_REVIEW_APPROVAL_CHANNEL
  review_response_post_failed                    →  SLACK_REVIEW_APPROVAL_CHANNEL
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

import requests


_API = "https://slack.com/api/chat.postMessage"


def make_notifier(*, bot_token: str,
                  leads_channel: str = "leads-inbound",
                  review_channel: str = "review-approvals") -> Callable[[dict], None]:
    """Return a notify_fn(payload) callable the handlers can invoke."""

    def _post(channel: str, text: str) -> bool:
        if not bot_token:
            print(f"[slack stub] would post to #{channel}: {text[:200]}")
            return False
        try:
            r = requests.post(
                _API,
                headers={
                    "Authorization": f"Bearer {bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"channel": channel.lstrip("#"), "text": text,
                      "unfurl_links": False},
                timeout=4,
            )
            data = r.json() if r.text else {}
            if not data.get("ok"):
                print(f"[slack] post to #{channel} failed: {data.get('error', 'unknown')}")
                return False
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[slack] post to #{channel} errored: {e}")
            return False

    def notify(payload: dict) -> None:
        kind = payload.get("kind", "")
        try:
            if kind == "capacity_audit":
                _post(leads_channel, _format_capacity_audit(payload))
            elif kind == "contact_form":
                _post(leads_channel, _format_contact_form(payload))
            elif kind == "review_response_draft_pending_approval":
                _post(review_channel, _format_review_draft(payload))
            elif kind == "review_response_post_failed":
                _post(review_channel, _format_review_post_failed(payload))
            else:
                # Unknown kind — generic fallback
                _post(leads_channel, f"Sentinel event: {kind}\n```{payload}```")
        except Exception as e:  # noqa: BLE001
            print(f"[notifier] format/post failed for kind={kind}: {e}")

    return notify


def null_notifier(payload: dict) -> None:
    """No-op notifier used when no SLACK_BOT_TOKEN is configured.
    Still prints to stdout so operators see events in Railway logs."""
    kind = payload.get("kind", "?")
    print(f"[notify:NULL] kind={kind} payload_keys={list(payload.keys())}")


# --- Formatters --------------------------------------------------------

def _format_capacity_audit(p: dict) -> str:
    lead = p.get("lead") or {}
    score = p.get("score") or {}
    lines = [
        f"📋 *New capacity audit lead* — {p.get('tenant', 'unknown tenant')}",
        f"Business: *{lead.get('business', '?')}*",
        f"From: {lead.get('name', '?')} <{lead.get('email', '?')}>",
        f"URL: {lead.get('url', '?')}",
    ]
    if lead.get("phone"):
        lines.append(f"Phone: {lead['phone']}")
    seo = p.get("voice_audit_seo")
    geo = p.get("voice_audit_geo")
    if seo is not None or geo is not None:
        lines.append(f"Audit scores: SEO {seo if seo is not None else '?'}  /  GEO {geo if geo is not None else '?'}")
    if score.get("score"):
        lines.append(f"Sentinel score: *{score['score']}* — {score.get('reason', '')}")
    return "\n".join(lines)


def _format_contact_form(p: dict) -> str:
    lead = p.get("lead") or {}
    lines = [
        f"💬 *New contact inquiry* — {p.get('tenant', 'unknown tenant')}",
        f"From: *{lead.get('name', '?')}* <{lead.get('email', '?')}>",
    ]
    if lead.get("service"):
        lines.append(f"Interested in: {lead['service']}")
    msg = lead.get("message", "")
    if msg:
        msg_snip = msg.strip().replace("\n", " ")
        if len(msg_snip) > 300:
            msg_snip = msg_snip[:300] + "…"
        lines.append(f">>> {msg_snip}")
    return "\n".join(lines)


def _format_review_draft(p: dict) -> str:
    rating = p.get("review_rating", "?")
    star = "⭐" * int(rating) if isinstance(rating, int) else f"{rating}★"
    lines = [
        f"📝 *Review reply awaiting approval* — {p.get('tenant', 'unknown')}  {star}",
        f"Review id: `{p.get('review_id', '?')}`  (queue reason: `{p.get('queue_reason', '?')}`)",
    ]
    if p.get("review_author"):
        lines.append(f"Reviewer: {p['review_author']}")
    rb = (p.get("review_body") or "").strip().replace("\n", " ")
    if rb:
        if len(rb) > 300:
            rb = rb[:300] + "…"
        lines.append(f"_Review:_ {rb}")
    if p.get("draft_body"):
        lines.append(f"*Draft reply* (tone: {p.get('tone', '?')}, flags: {p.get('flags', [])}):")
        lines.append(f"```{p['draft_body']}```")
    return "\n".join(lines)


def _format_review_post_failed(p: dict) -> str:
    return (
        f"❌ *Review post failed* — {p.get('tenant', 'unknown')}\n"
        f"Review id: `{p.get('review_id', '?')}` ({p.get('review_rating', '?')}★)\n"
        f"Error: `{p.get('error', '?')}`\n"
        f"Draft (so a human can re-post manually):\n"
        f"```{p.get('draft_body', '')}```"
    )
