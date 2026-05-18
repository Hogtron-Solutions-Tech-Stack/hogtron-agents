"""Quota gate — Max subscription budget guard.

File-backed state, cross-process safe via msvcrt locking (Windows) or
fcntl (POSIX dev machines). Soft target prevents the router from hammering
the Max quota and stealing capacity from interactive Claude Code work.

The router consults this gate BEFORE attempting Max. On Max errors, it
records the failure here so subsequent calls back off.

Per the Sean-approved plan: this is a SOFT guard, not a guarantee.
Anthropic adjusts limits unannounced; we tune from real telemetry in
Phase 3.

Public API:
    should_try_subscription() -> bool
    record_call(used_subscription: bool, failed: bool = False) -> None
    record_quota_exhausted(retry_after_sec: Optional[int] = None) -> None
    record_credential_failure() -> None
    state_snapshot() -> dict
    reset() -> None   # tests only
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _state_path() -> Path:
    """%LOCALAPPDATA%\\HogTron\\quota_state.json on Windows;
    ~/.HogTron/quota_state.json on POSIX (dev only)."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "HogTron" / "quota_state.json"
    return Path.home() / ".HogTron" / "quota_state.json"


WINDOW_SECONDS = 5 * 3600  # Anthropic's published 5h rolling window
MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_QUOTA_COOLDOWN_SEC = 3600        # 1h after rate-limit
DEFAULT_CREDENTIAL_COOLDOWN_SEC = 14400  # 4h after credential failure (manual fix usually needed)


def _soft_target() -> int:
    """Default 150 per plan; env override for tuning."""
    try:
        return int(os.environ.get("HOGTRON_MAX_SUBSCRIPTION_SOFT_TARGET", "150"))
    except ValueError:
        return 150


# ---------------------------------------------------------------------------
# Cross-platform file locking
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import msvcrt

    @contextmanager
    def _locked_file(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        f = open(path, "r+", encoding="utf-8")
        try:
            # Lock the first byte — sufficient for our needs and required by
            # msvcrt.locking which can't lock an empty range.
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            yield f
        finally:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass  # already unlocked or file truncated; don't mask the real error
            f.close()
else:
    import fcntl

    @contextmanager
    def _locked_file(path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        f = open(path, "r+", encoding="utf-8")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield f
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class _State:
    window_start_iso: Optional[str] = None
    calls_in_window: int = 0
    cooldown_until_iso: Optional[str] = None
    last_quota_error_iso: Optional[str] = None
    last_credential_failure_iso: Optional[str] = None
    consecutive_failures: int = 0


def _load_state(f) -> _State:
    f.seek(0)
    raw = f.read()
    if not raw.strip():
        return _State()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Corrupt file — start fresh rather than fail closed. The gate exists
        # to PROTECT subscription usage; failing closed would block the
        # opportunistic path forever on a single bad write.
        return _State()
    valid_keys = {fld.name for fld in fields(_State)}
    return _State(**{k: v for k, v in data.items() if k in valid_keys})


def _save_state(f, state: _State) -> None:
    f.seek(0)
    f.truncate()
    f.write(json.dumps(asdict(state), indent=2, sort_keys=True))
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError:
        pass  # fsync isn't critical for a soft guard


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _maybe_rotate_window(state: _State, now: datetime) -> _State:
    """Reset the call counter when the 5h window has elapsed."""
    start = _parse_iso(state.window_start_iso)
    if start is None or (now - start).total_seconds() >= WINDOW_SECONDS:
        state.window_start_iso = now.isoformat()
        state.calls_in_window = 0
    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def should_try_subscription() -> bool:
    """True if the router should try Max for the next call.

    Returns False if:
      - HOGTRON_TRY_MAX env var is not "true" (default: API canonical)
      - HOGTRON_FORCE_BACKEND=api
      - Cooldown is currently active
      - Calls in the current 5h window >= soft target (default 150)
      - Consecutive failures >= MAX_CONSECUTIVE_FAILURES
    """
    if os.environ.get("HOGTRON_TRY_MAX", "false").strip().lower() != "true":
        return False
    if os.environ.get("HOGTRON_FORCE_BACKEND", "").strip().lower() == "api":
        return False

    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load_state(f)
        state = _maybe_rotate_window(state, now)

        cooldown_until = _parse_iso(state.cooldown_until_iso)
        if cooldown_until and cooldown_until > now:
            _save_state(f, state)
            return False

        if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            _save_state(f, state)
            return False

        if state.calls_in_window >= _soft_target():
            _save_state(f, state)
            return False

        _save_state(f, state)
        return True


def record_call(used_subscription: bool, failed: bool = False) -> None:
    """Update counters after a Max call completes (or fails)."""
    if not used_subscription:
        return  # we only count subscription calls toward the window budget

    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load_state(f)
        state = _maybe_rotate_window(state, now)
        state.calls_in_window += 1
        if failed:
            state.consecutive_failures += 1
        else:
            state.consecutive_failures = 0
        _save_state(f, state)


def record_quota_exhausted(retry_after_sec: Optional[int] = None) -> None:
    """Trip the cooldown after a rate-limit / quota error from Max."""
    sec = retry_after_sec if retry_after_sec is not None else DEFAULT_QUOTA_COOLDOWN_SEC
    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load_state(f)
        state = _maybe_rotate_window(state, now)
        state.cooldown_until_iso = (now + timedelta(seconds=sec)).isoformat()
        state.last_quota_error_iso = now.isoformat()
        state.consecutive_failures += 1
        _save_state(f, state)


def record_credential_failure() -> None:
    """Longer cooldown — credential issues usually require manual intervention."""
    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load_state(f)
        state.cooldown_until_iso = (
            now + timedelta(seconds=DEFAULT_CREDENTIAL_COOLDOWN_SEC)
        ).isoformat()
        state.last_credential_failure_iso = now.isoformat()
        state.consecutive_failures += 1
        _save_state(f, state)


def state_snapshot() -> dict:
    """Read-only view of current state — for telemetry, alerting, debugging."""
    with _locked_file(_state_path()) as f:
        return asdict(_load_state(f))


def reset() -> None:
    """Clear all state. Phase 0 verification + tests only."""
    with _locked_file(_state_path()) as f:
        _save_state(f, _State())


# ---------------------------------------------------------------------------
# CLI for manual inspection during Phase 0
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    cmd = _sys.argv[1] if len(_sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(state_snapshot(), indent=2, sort_keys=True))
    elif cmd == "reset":
        reset()
        print("quota state reset")
    elif cmd == "should-try":
        print("yes" if should_try_subscription() else "no")
    else:
        print(f"unknown command: {cmd}")
        print("usage: python -m hogtron_agents._shared.quota_gate [status|reset|should-try]")
        _sys.exit(1)
