"""Minimal telemetry interface. Callers can inject their own logger/DB writer.

FactoryHQ has agents/_telemetry.py that writes to the agents table.
hogtron-dashboard logs to stdout + tool_runs table.
Each caller wires its own implementation; the department only needs the protocol.
"""
from __future__ import annotations

from typing import Protocol, Optional
from contextlib import contextmanager


class TelemetrySink(Protocol):
    def log(self, agent: str, event: str, detail: Optional[str] = None) -> None: ...
    def set_status(self, agent: str, status: str, task: Optional[str] = None) -> None: ...


class NullSink:
    """No-op default. Departments work without telemetry wired."""
    def log(self, agent: str, event: str, detail: Optional[str] = None) -> None:
        pass
    def set_status(self, agent: str, status: str, task: Optional[str] = None) -> None:
        pass


@contextmanager
def working(sink: TelemetrySink, agent: str, task: str):
    sink.set_status(agent, "working", task)
    try:
        yield
        sink.set_status(agent, "idle", None)
    except Exception as e:
        sink.set_status(agent, "error", f"{task}: {e}")
        raise
