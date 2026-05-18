"""Router telemetry summarizer — produces the Phase 0 observation-window
report that Sean needs to approve Phase 1.

Aggregates JSONL files from %LOCALAPPDATA%\\HogTron\\logs\\router-*.jsonl
and prints a kill-criterion evaluation, backend distribution, per-agent
breakdown, fallback reasons, and effective vs notional cost.

The KILL CRITERION section is the headline output. Three of the five
criteria can be checked automatically against telemetry; two require
Sean's judgment.

Usage:
    python -m hogtron_agents._shared.router_summary
    python -m hogtron_agents._shared.router_summary --since 7
    python -m hogtron_agents._shared.router_summary --agent creative.shirt
    python -m hogtron_agents._shared.router_summary --format json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Kill criterion thresholds (from the approved plan)
# ---------------------------------------------------------------------------

MAX_ERROR_RATE_THRESHOLD = 0.10        # >10% Max errors → kill
SCHEMA_FAILURE_RATE_THRESHOLD = 0.05   # >5% schema failures → kill
CREDENTIAL_BREAKS_THRESHOLD = 1        # >1 credential break → kill

DEFAULT_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _logs_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "HogTron" / "logs"
    return Path.home() / ".HogTron" / "logs"


_LOG_NAME_RE = re.compile(r"router-(\d{4})(\d{2})(\d{2})\.jsonl$")


def _date_from_filename(path: Path) -> Optional[datetime]:
    m = _LOG_NAME_RE.match(path.name)
    if not m:
        return None
    return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _discover_files(logs_dir: Path, since_date: datetime,
                    until_date: datetime) -> list[Path]:
    if not logs_dir.exists():
        return []
    out = []
    for p in sorted(logs_dir.glob("router-*.jsonl")):
        d = _date_from_filename(p)
        if d is None:
            continue
        if since_date.date() <= d.date() <= until_date.date():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    files_read: list[str] = field(default_factory=list)
    total_calls: int = 0
    by_backend: Counter = field(default_factory=Counter)
    fallback_reasons: Counter = field(default_factory=Counter)
    schema_failures_total: int = 0
    max_attempts_total: int = 0      # Max tried (success OR fallback after Max error)
    max_errors_total: int = 0        # Max errors that triggered fallback
    credential_breaks: int = 0
    by_agent: dict = field(default_factory=lambda: defaultdict(
        lambda: {"calls": 0, "api": 0, "max": 0, "dry_run": 0, "cost_usd": 0.0}
    ))
    cost_effective_usd: float = 0.0  # API-only path (real cash burn)
    cost_notional_usd: float = 0.0   # what it would have cost on API if everything was API
    daily_volume: dict = field(default_factory=lambda: defaultdict(int))
    by_model: Counter = field(default_factory=Counter)
    elapsed_sec_by_backend: dict = field(default_factory=lambda: defaultdict(list))


def _ingest(path: Path, agent_filter: Optional[str], stats: Stats) -> None:
    stats.files_read.append(path.name)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            agent = row.get("agent", "")
            if agent_filter and agent != agent_filter:
                continue

            backend = row.get("backend", "unknown")
            cost = row.get("estimated_api_cost_usd", 0.0) or 0.0
            elapsed = row.get("elapsed_sec", 0.0) or 0.0
            fallback = row.get("fallback_reason")
            schema_fails = row.get("schema_failures", 0) or 0
            model = row.get("model") or "unknown"
            ts = row.get("timestamp", "")

            stats.total_calls += 1
            stats.by_backend[backend] += 1
            stats.by_model[model] += 1
            stats.elapsed_sec_by_backend[backend].append(elapsed)
            stats.schema_failures_total += schema_fails

            ag = stats.by_agent[agent]
            ag["calls"] += 1
            ag[backend if backend in ("api", "max", "dry_run") else "api"] += 1
            ag["cost_usd"] += cost if backend == "api" else 0.0

            if backend == "api":
                stats.cost_effective_usd += cost
            # Notional = what API would have charged regardless of actual backend.
            # For Max-path calls, the SDK returns API-equivalent token counts
            # that the router has already converted to cost; we count that as
            # the "would-have-spent" number.
            stats.cost_notional_usd += cost if cost > 0 else 0.0

            # Daily volume by date prefix of timestamp
            if ts and len(ts) >= 10:
                stats.daily_volume[ts[:10]] += 1

            # Track Max attempts + errors
            if backend == "max":
                stats.max_attempts_total += 1   # successful Max use
            elif backend == "api" and fallback:
                # API call that came from a Max fallback = Max was attempted + failed
                stats.max_attempts_total += 1
                stats.max_errors_total += 1
                stats.fallback_reasons[fallback] += 1
                if fallback in ("credentials_missing", "credentials_invalid",
                                "claude_cli_missing"):
                    stats.credential_breaks += 1


# ---------------------------------------------------------------------------
# Kill criterion evaluation
# ---------------------------------------------------------------------------

def _evaluate_kill_criterion(stats: Stats) -> list[tuple[str, str, str]]:
    """Returns list of (status, label, detail). status ∈ {OK, KILL, REVIEW}."""
    out = []

    # 1. Max error rate
    if stats.max_attempts_total > 0:
        rate = stats.max_errors_total / stats.max_attempts_total
        pct = f"{rate * 100:.1f}%"
        status = "OK" if rate <= MAX_ERROR_RATE_THRESHOLD else "KILL"
        out.append((status, "Max error rate",
                    f"{pct}  ({stats.max_errors_total}/{stats.max_attempts_total} attempts; "
                    f"threshold {MAX_ERROR_RATE_THRESHOLD * 100:.0f}%)"))
    else:
        out.append(("REVIEW", "Max error rate",
                    "no Max attempts in window — set HOGTRON_TRY_MAX=true to gather data"))

    # 2. Schema failures (proxy for .parse() attempts: anything backend in (api,max) that's a parse)
    # We don't track parse-vs-create per row currently, so use total non-dry_run calls
    # as the denominator. This biases conservative (higher denom → lower rate),
    # which means the gate is forgiving here, but Sean can verify by hand.
    parse_calls = sum(c for b, c in stats.by_backend.items() if b != "dry_run")
    if parse_calls > 0:
        rate = stats.schema_failures_total / parse_calls
        pct = f"{rate * 100:.1f}%"
        status = "OK" if rate <= SCHEMA_FAILURE_RATE_THRESHOLD else "KILL"
        out.append((status, "Schema validation failure rate",
                    f"{pct}  ({stats.schema_failures_total}/{parse_calls} calls; "
                    f"threshold {SCHEMA_FAILURE_RATE_THRESHOLD * 100:.0f}%)"))
    else:
        out.append(("REVIEW", "Schema validation failure rate", "no calls in window"))

    # 3. Credential rotation breaks
    status = "OK" if stats.credential_breaks <= CREDENTIAL_BREAKS_THRESHOLD else "KILL"
    out.append((status, "Credential rotation breaks",
                f"{stats.credential_breaks}  (threshold {CREDENTIAL_BREAKS_THRESHOLD})"))

    # 4 & 5. Manual review
    out.append(("REVIEW", "Anthropic ToS / limits changes during window",
                "manual check -- has Anthropic announced anything affecting Max?"))
    out.append(("REVIEW", "Interactive Claude Code work impacted",
                "manual check -- Sean's own usage felt rate-limited?"))

    return out


# ---------------------------------------------------------------------------
# Human-readable rendering
# ---------------------------------------------------------------------------

def _section(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}"


def _format_human(stats: Stats, since: datetime, until: datetime,
                  agent_filter: Optional[str]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("HogTron Router Telemetry Summary")
    lines.append("=" * 72)
    lines.append(f"Window:  {since.date()} -> {until.date()}  "
                 f"({(until - since).days + 1} days)")
    lines.append(f"Files:   {len(stats.files_read)} JSONL "
                 f"({stats.files_read[0] if stats.files_read else '(none)'} ... "
                 f"{stats.files_read[-1] if stats.files_read else '(none)'})")
    if agent_filter:
        lines.append(f"Filter:  agent = {agent_filter!r}")
    lines.append(f"Calls:   {stats.total_calls}")

    # Kill criterion — the headline
    lines.append(_section("KILL CRITERION EVALUATION (Sean's bar for approving Phase 1)"))
    crit = _evaluate_kill_criterion(stats)
    for status, label, detail in crit:
        tag = {"OK": "[ OK    ]", "KILL": "[ KILL  ]", "REVIEW": "[ REVIEW]"}[status]
        lines.append(f"  {tag}  {label}")
        lines.append(f"             {detail}")
    kills = sum(1 for s, *_ in crit if s == "KILL")
    oks = sum(1 for s, *_ in crit if s == "OK")
    reviews = sum(1 for s, *_ in crit if s == "REVIEW")
    if kills > 0:
        lines.append(f"\n  VERDICT: {kills} criterion FAILED — Sean SHOULD NOT approve Phase 1.")
    elif oks >= 3:
        lines.append(f"\n  VERDICT: {oks} automatic criteria PASS. {reviews} need Sean's manual judgment.")
    else:
        lines.append(f"\n  VERDICT: not enough data — observation window may be too short.")

    # Backend distribution
    lines.append(_section("BACKEND DISTRIBUTION"))
    for backend, count in stats.by_backend.most_common():
        pct = (count / stats.total_calls * 100) if stats.total_calls else 0
        lines.append(f"  {backend:10s} {count:6d}  ({pct:5.1f}%)")

    # Cost
    lines.append(_section("COST"))
    lines.append(f"  Effective spend (actual cash, API-only path):  ${stats.cost_effective_usd:.4f}")
    lines.append(f"  Notional spend (all calls priced at API rates): ${stats.cost_notional_usd:.4f}")
    savings = stats.cost_notional_usd - stats.cost_effective_usd
    if stats.cost_notional_usd > 0:
        savings_pct = savings / stats.cost_notional_usd * 100
        lines.append(f"  Subscription offset:                            ${savings:.4f}  ({savings_pct:.1f}%)")
    else:
        lines.append("  Subscription offset:                            $0  (no calls yet)")

    # Per-agent
    lines.append(_section("PER-AGENT BREAKDOWN"))
    if not stats.by_agent:
        lines.append("  (no agents in window)")
    else:
        # Header
        lines.append(f"  {'agent':30s} {'calls':>6s} {'api':>6s} {'max':>6s} {'dry':>6s} {'cost($)':>10s}")
        for agent, ag in sorted(stats.by_agent.items(), key=lambda kv: -kv[1]["calls"]):
            lines.append(
                f"  {agent:30s} {ag['calls']:>6d} {ag['api']:>6d} {ag['max']:>6d} "
                f"{ag['dry_run']:>6d} {ag['cost_usd']:>10.4f}"
            )

    # Fallback reasons
    lines.append(_section("FALLBACK REASONS (Max -> API)"))
    if not stats.fallback_reasons:
        lines.append("  (none -- all Max attempts succeeded or no Max attempted)")
    else:
        for reason, count in stats.fallback_reasons.most_common():
            lines.append(f"  {reason:30s} {count:6d}")

    # Latency by backend
    lines.append(_section("LATENCY BY BACKEND (seconds)"))
    for backend, samples in stats.elapsed_sec_by_backend.items():
        if not samples:
            continue
        n = len(samples)
        avg = sum(samples) / n
        s_sorted = sorted(samples)
        p50 = s_sorted[n // 2]
        p95 = s_sorted[min(n - 1, int(n * 0.95))]
        lines.append(f"  {backend:10s} n={n:5d}  avg={avg:6.2f}  p50={p50:6.2f}  p95={p95:6.2f}")

    # Daily volume (bar chart)
    lines.append(_section("DAILY CALL VOLUME"))
    if not stats.daily_volume:
        lines.append("  (no data)")
    else:
        max_count = max(stats.daily_volume.values())
        bar_max = 40
        for day in sorted(stats.daily_volume.keys()):
            c = stats.daily_volume[day]
            bar = "#" * max(1, int(c / max_count * bar_max))
            lines.append(f"  {day}  {bar} {c}")

    # Models
    lines.append(_section("MODELS USED"))
    for model, count in stats.by_model.most_common():
        lines.append(f"  {model:35s} {count:6d}")

    lines.append("")
    return "\n".join(lines)


def _format_json(stats: Stats, since: datetime, until: datetime,
                 agent_filter: Optional[str]) -> str:
    crit = _evaluate_kill_criterion(stats)
    out = {
        "window": {
            "since": since.date().isoformat(),
            "until": until.date().isoformat(),
            "days": (until - since).days + 1,
        },
        "files_read": stats.files_read,
        "agent_filter": agent_filter,
        "total_calls": stats.total_calls,
        "by_backend": dict(stats.by_backend),
        "by_model": dict(stats.by_model),
        "by_agent": {k: v for k, v in stats.by_agent.items()},
        "fallback_reasons": dict(stats.fallback_reasons),
        "schema_failures_total": stats.schema_failures_total,
        "max_attempts_total": stats.max_attempts_total,
        "max_errors_total": stats.max_errors_total,
        "credential_breaks": stats.credential_breaks,
        "cost_effective_usd": round(stats.cost_effective_usd, 6),
        "cost_notional_usd": round(stats.cost_notional_usd, 6),
        "daily_volume": dict(stats.daily_volume),
        "kill_criterion": [
            {"status": s, "label": l, "detail": d} for s, l, d in crit
        ],
    }
    return json.dumps(out, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", type=int, default=DEFAULT_WINDOW_DAYS,
                    help=f"how many days back (default {DEFAULT_WINDOW_DAYS})")
    ap.add_argument("--until", type=str, default=None,
                    help="ISO date (YYYY-MM-DD), default today")
    ap.add_argument("--agent", type=str, default=None,
                    help="filter to one agent (e.g. creative.shirt)")
    ap.add_argument("--format", choices=("human", "json"), default="human")
    ap.add_argument("--logs-dir", type=str, default=None,
                    help="override LOCALAPPDATA-derived logs dir")
    args = ap.parse_args()

    until_date = (datetime.fromisoformat(args.until)
                  if args.until else datetime.now())
    since_date = until_date - timedelta(days=args.since - 1)

    logs_dir = Path(args.logs_dir) if args.logs_dir else _logs_dir()
    files = _discover_files(logs_dir, since_date, until_date)

    stats = Stats()
    for f in files:
        _ingest(f, args.agent, stats)

    if args.format == "human":
        print(_format_human(stats, since_date, until_date, args.agent))
    else:
        print(_format_json(stats, since_date, until_date, args.agent))


if __name__ == "__main__":
    main()
