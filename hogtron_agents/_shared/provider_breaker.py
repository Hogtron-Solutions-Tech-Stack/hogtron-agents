"""Circuit breaker for the Anthropic API path.

When the Anthropic API reports the credit balance is exhausted, we don't want
every subsequent agent call to eat a dead Anthropic round-trip (plus the SDK's
own backoff retries) before falling back to xAI / Gemini. This records a short
cooldown so the router skips Anthropic and goes straight to the fallback
providers until the window elapses — or until a successful Anthropic call
clears it.

State is file-backed and cross-process safe, reusing quota_gate's locking.

Public API:
    anthropic_in_cooldown() -> bool
    record_anthropic_exhausted(reason: str = "") -> None
    clear_anthropic_cooldown() -> None
    snapshot() -> dict
    reset() -> None   # tests only
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .quota_gate import _locked_file  # reuse cross-platform file locking


def _state_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "HogTron" / "api_breaker.json"
    return Path.home() / ".HogTron" / "api_breaker.json"


def _cooldown_sec() -> int:
    """How long to skip Anthropic after a credit-exhaustion error. Tunable so
    ops can shorten it right after topping up credits."""
    try:
        return int(os.environ.get("HOGTRON_API_COOLDOWN_SEC", "900"))
    except ValueError:
        return 900


@dataclass
class _State:
    cooldown_until_iso: Optional[str] = None
    last_reason: Optional[str] = None
    last_tripped_iso: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load(f) -> _State:
    f.seek(0)
    raw = f.read()
    if not raw.strip():
        return _State()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _State()
    valid = {fld.name for fld in fields(_State)}
    return _State(**{k: v for k, v in data.items() if k in valid})


def _save(f, state: _State) -> None:
    f.seek(0)
    f.truncate()
    f.write(json.dumps(asdict(state), indent=2, sort_keys=True))
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError:
        pass


def anthropic_in_cooldown() -> bool:
    """True if a recent credit-exhaustion error means we should skip Anthropic."""
    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load(f)
        until = _parse_iso(state.cooldown_until_iso)
        return bool(until and until > now)


def record_anthropic_exhausted(reason: str = "") -> None:
    """Trip the breaker — skip Anthropic for the cooldown window."""
    now = _utcnow()
    with _locked_file(_state_path()) as f:
        state = _load(f)
        state.cooldown_until_iso = (now + timedelta(seconds=_cooldown_sec())).isoformat()
        state.last_reason = reason or state.last_reason
        state.last_tripped_iso = now.isoformat()
        _save(f, state)


def clear_anthropic_cooldown() -> None:
    """Reset the breaker — called after a successful Anthropic call."""
    with _locked_file(_state_path()) as f:
        state = _load(f)
        if state.cooldown_until_iso is None:
            return  # nothing to clear; avoid a needless write
        _save(f, _State())


def snapshot() -> dict:
    with _locked_file(_state_path()) as f:
        return asdict(_load(f))


def reset() -> None:
    with _locked_file(_state_path()) as f:
        _save(f, _State())


if __name__ == "__main__":
    import sys as _sys

    cmd = _sys.argv[1] if len(_sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(snapshot(), indent=2, sort_keys=True))
    elif cmd == "reset":
        reset()
        print("api breaker reset")
    elif cmd == "in-cooldown":
        print("yes" if anthropic_in_cooldown() else "no")
    else:
        print(f"unknown command: {cmd}")
        _sys.exit(1)
