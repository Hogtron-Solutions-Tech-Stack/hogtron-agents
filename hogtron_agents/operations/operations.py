"""Operations department head.

One agent. One entrypoint: do(brief). Dispatches by kind. Every kind here
hits an external system — pay attention to the autonomy ladder when wiring
Layer 2/3 callers. See ../docs/architecture.md.
"""
from __future__ import annotations

from typing import Callable, Optional

from .briefs import OperationsBrief, OperationsResult, OperationsKind
from .._shared.telemetry import TelemetrySink, NullSink, working
from . import _printify_upload, _publish_etsy, _publish_pinterest, _render_video, _autonomous

Handler = Callable[["Operations", OperationsBrief], OperationsResult]


class Operations:
    NAME = "Operations"

    def __init__(self, telemetry: Optional[TelemetrySink] = None):
        self.telemetry = telemetry or NullSink()
        self._handlers: dict[OperationsKind, Handler] = {
            "printify_upload": _do_printify_upload,
            "publish_etsy": _do_publish_etsy,
            "publish_shopify": _do_publish_shopify,
            "publish_pinterest": _do_publish_pinterest,
            "render_video": _do_render_video,
            "deploy_mockup": _do_deploy_mockup,
            "deploy_proposal": _do_deploy_proposal,
        }

    def do(self, brief: OperationsBrief) -> OperationsResult:
        handler = self._handlers.get(brief.kind)
        if handler is None:
            raise ValueError(f"Operations has no handler for kind={brief.kind!r}")
        with working(self.telemetry, self.NAME, f"do({brief.kind})"):
            return handler(self, brief)

    def register(self, kind: OperationsKind, handler: Handler) -> None:
        self._handlers[kind] = handler

    def run_autonomous(self, directive: str, *, anthropic_api_key: str,
                       model: str = "claude-sonnet-4-6", max_iterations: int = 10,
                       progress_callback=None, should_cancel=None,
                       autonomy_rung: int = 0):
        """Layer 2 — chain Operations kinds in response to a directive.

        Default Sonnet 4.6 — Operations runs at autonomy rung 0 by default,
        so the model just needs to faithfully follow the SYSTEM_PROMPT's
        HOLD rules. Sonnet handles that reliably and saves vs Opus.

        WARNING: every Operations kind has real-world side effects. The
        system prompt biases toward the autonomy ladder (rung 0: hold
        publish_* until human approval), but a directive can override.
        Layer 3 callers should typically use dry_run flows until rung 2+."""
        return _autonomous.run_autonomous(
            self, directive, anthropic_api_key=anthropic_api_key,
            model=model, max_iterations=max_iterations,
            progress_callback=progress_callback, should_cancel=should_cancel,
            autonomy_rung=autonomy_rung,
        )


# --- Handlers -----------------------------------------------------------

def _do_printify_upload(self: Operations, brief: OperationsBrief) -> OperationsResult:
    return _printify_upload.printify_upload(brief)


def _do_publish_etsy(self: Operations, brief: OperationsBrief) -> OperationsResult:
    return _publish_etsy.publish_etsy(brief)


def _do_publish_shopify(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Net-new: push Printify draft to Shopify channel. Shopify account
    added 2026-05-12 — wire once Printify->Shopify connection is configured."""
    raise NotImplementedError("publish_shopify not yet implemented — net-new kind")


def _do_publish_pinterest(self: Operations, brief: OperationsBrief) -> OperationsResult:
    return _publish_pinterest.publish_pinterest(brief)


def _do_render_video(self: Operations, brief: OperationsBrief) -> OperationsResult:
    return _render_video.render_video(brief)


def _do_deploy_mockup(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: hogtron-dashboard mockup deploy (Railway one-click).
    DO NOT change existing client mockup URLs — they're frozen per
    reference_infra_rules.md."""
    raise NotImplementedError(
        "deploy_mockup pending migration from hogtron-dashboard mockup deploy"
    )


def _do_deploy_proposal(self: Operations, brief: OperationsBrief) -> OperationsResult:
    """Port target: hogtron-dashboard proposal share URL publishing."""
    raise NotImplementedError(
        "deploy_proposal pending migration from hogtron-dashboard proposals"
    )
