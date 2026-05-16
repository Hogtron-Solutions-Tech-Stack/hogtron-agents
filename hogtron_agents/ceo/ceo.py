"""CEO class — the top-level orchestration entry point.

Composes the 5 department instances + provides run_autonomous() that
dispatches across them in response to company-level directives.

Constructor takes the dept instances rather than constructing them so
callers can inject their own providers (TMProvider for Research,
telemetry sinks, etc.) — same pattern as Layer 1.
"""
from __future__ import annotations

from typing import Optional

from .._shared.telemetry import TelemetrySink, NullSink
from . import _autonomous


class CEO:
    NAME = "CEO"

    def __init__(
        self,
        *,
        research,
        creative,
        marketing,
        sales,
        operations,
        telemetry: Optional[TelemetrySink] = None,
    ):
        self.research = research
        self.creative = creative
        self.marketing = marketing
        self.sales = sales
        self.operations = operations
        self.telemetry = telemetry or NullSink()

    def run_autonomous(
        self,
        directive: str,
        *,
        anthropic_api_key: str,
        model: str = "claude-sonnet-4-6",
        max_iterations: int = 8,
        dept_max_iterations: int = 10,
        progress_callback=None,
        should_cancel=None,
    ):
        """Dispatch a company-level directive across departments.

        Example:
            ceo = CEO(research=..., creative=..., marketing=...,
                      sales=..., operations=...)
            result = ceo.run_autonomous(
                "Find 2 IP-clear shirt phrases for graduation, then "
                "design each. HOLD publishing.",
                anthropic_api_key="...",
            )
            print(result.summary)        # journal-ready
            print(f"total: ${result.cost_usd + result.ops_cost_usd:.2f}")
            for d in result.dept_calls:
                print(f"  {d.department}: {d.iterations} iter, ${d.cost_usd:.4f}")

        Returns CEOResult. See _autonomous.py for the full shape.

        Cost note: each tool call here triggers a nested department agent
        loop, so total spend = CEO tokens + sum(dept tokens) + sum(ops
        real-world spend). Conservative max_iterations recommended.
        """
        return _autonomous.run_autonomous(
            self, directive,
            anthropic_api_key=anthropic_api_key,
            model=model,
            max_iterations=max_iterations,
            dept_max_iterations=dept_max_iterations,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
