"""Creative department head.

One agent. One entrypoint: design(brief). Dispatches by brief.kind to the
right internal toolchain. All kinds share brand constants, Claude client,
and telemetry.

The handlers are intentionally thin and registered in a dispatch table —
adding a new kind (e.g. "business_card") is a 2-line change.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import CreativeBrief, CreativeAsset, BriefKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from .._shared.entitlements import require_agent_enabled
from . import _shirt, _mockup, _autonomous

Handler = Callable[["Creative", CreativeBrief], CreativeAsset]


class Creative:
    NAME = "Creative"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[BriefKind, Handler] = {
            "shirt": _design_shirt,
            "pdf_page": _design_pdf_page,
            "mockup": _design_mockup,
            "proposal_cover": _design_proposal_cover,
            "canva_asset": _design_canva_asset,
        }

    def design(self, brief: CreativeBrief) -> CreativeAsset:
        require_agent_enabled(brief.context, "creative")
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Creative has no handler for kind={brief.kind!r}")
        task = f"design({brief.kind})"
        with working(self.telemetry, self.NAME, task):
            return handler(self, brief)

    def register(self, kind: BriefKind, handler: Handler) -> None:
        """Override or add a handler at runtime. Useful for tests and migration."""
        self._handlers[kind] = handler

    def run_autonomous(self, directive: str, *, anthropic_api_key: str,
                       model: str = "claude-sonnet-4-6", max_iterations: int = 8,
                       progress_callback=None, should_cancel=None):
        """Layer 2 — chain Creative kinds in response to a directive.

        Default model is Sonnet 4.6 — Opus is rarely needed for the
        single-tool-call patterns Creative typically runs. Override per-call
        when generating complex multi-step deliverables.
        """
        return _autonomous.run_autonomous(
            self, directive, anthropic_api_key=anthropic_api_key,
            model=model, max_iterations=max_iterations,
            progress_callback=progress_callback, should_cancel=should_cancel,
        )


# --- Handlers (stubs during pilot; ported from FactoryHQ in follow-up) ---

def _design_shirt(self: Creative, brief: CreativeBrief) -> CreativeAsset:
    """Shirt design: Claude art-direct -> Recraft render.
    Printify upload is Operations dept (still in FactoryHQ/agents/designer.py).
    """
    return _shirt.design_shirt(brief)


def _design_pdf_page(self: Creative, brief: CreativeBrief) -> CreativeAsset:
    """Port target: FactoryHQ/agents/pdf_designer.py (181 lines)."""
    raise NotImplementedError(
        "pdf_page handler pending migration from FactoryHQ/agents/pdf_designer.py"
    )


def _design_mockup(self: Creative, brief: CreativeBrief) -> CreativeAsset:
    """Two-phase mockup: Claude plans palette/sections → Claude renders full HTML."""
    return _mockup.design_mockup(brief)


def _design_proposal_cover(self: Creative, brief: CreativeBrief) -> CreativeAsset:
    """Port target: hogtron-dashboard proposal generator cover art."""
    raise NotImplementedError("proposal_cover handler pending migration")


def _design_canva_asset(self: Creative, brief: CreativeBrief) -> CreativeAsset:
    """Port target: hogtron-canva skill workflow via Canva MCP."""
    raise NotImplementedError("canva_asset handler pending Canva MCP wiring")
