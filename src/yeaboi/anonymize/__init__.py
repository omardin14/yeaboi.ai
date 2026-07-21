"""Anonymize mode — mask PII & company-specific data for public sharing.

A post-processing step, not a mode of its own: it takes the Markdown any mode's
Export button already produces and returns a privacy-masked copy safe to paste into a
README, website, or post. See ``engine.run_anonymize`` for the pipeline.
"""

from __future__ import annotations

from yeaboi.agent.state import AnonymizedOutput
from yeaboi.anonymize.engine import run_anonymize
from yeaboi.anonymize.export import build_anonymized_markdown, export_anonymized

__all__ = [
    "AnonymizedOutput",
    "build_anonymized_markdown",
    "export_anonymized",
    "run_anonymize",
]
