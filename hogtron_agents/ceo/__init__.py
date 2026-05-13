"""CEO loop — Layer 3 of the agentic architecture.

One outer agent loop with Sean + Anthony's voice in the system prompt.
Tools = the 5 departments' run_autonomous() methods. The CEO loop takes
company-level directives ("plan next week's listings", "finish the
Discinsanity proposal") and fans out across departments, consolidating
findings into a single response + journal-ready summary.
"""
from .ceo import CEO
from ._autonomous import CEOResult

__all__ = ["CEO", "CEOResult"]
