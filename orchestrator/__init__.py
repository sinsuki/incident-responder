"""Orchestrator for one incident scenario.

The report is built from the forensics, archaeologist, and runbook claims.
ORCHESTRATOR_LLM may rewrite the sentences. The verifier checks them again.
ground_truth.json is not read.
"""

from orchestrator.pipeline import assemble, respond

__all__ = ["assemble", "respond"]
__version__ = "0.1.0"
