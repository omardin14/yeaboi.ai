"""MCP tools: Anonymize (mask PII & company-specific data for public sharing)."""

from __future__ import annotations

import logging

# Context must be importable from module globals — FastMCP evaluates the
# stringified type hints (PEP 563) of tool functions against this namespace.
from mcp.server.fastmcp import Context

from yeaboi.mcp.runtime import run_engine

logger = logging.getLogger(__name__)


def _anonymize_text(
    text: str,
    instruction: str,
    extra_mask_terms: list | None,
    keep_terms: list | None,
    project_name: str,
    source_mode: str,
):
    from yeaboi.anonymize.engine import run_anonymize

    return run_anonymize(
        text,
        instruction=instruction,
        extra_mask_terms=tuple(extra_mask_terms or ()),
        keep_terms=tuple(keep_terms or ()),
        project_name=project_name,
        source_mode=source_mode,
    )


def register(app) -> None:
    """Attach the anonymize tools to the FastMCP app."""

    @app.tool()
    async def anonymize_text(
        ctx: Context,
        text: str,
        instruction: str = "",
        extra_mask_terms: list[str] | None = None,
        keep_terms: list[str] | None = None,
        project_name: str = "",
        source_mode: str = "",
    ) -> dict:
        """Mask PII & company-specific data in a block of generated output so it can be
        shared publicly (README, website, post). Redacts personal/team/project names, the
        company identity, internal tools, and URLs/emails/IDs, replacing them with neutral
        placeholders while keeping the text readable and structurally intact. A deterministic
        pass masks known company terms (from config) even without an LLM. instruction: free-text
        adjustment, e.g. 'also mask Acme' or "don't mask React — it's public". extra_mask_terms /
        keep_terms: terms to always / never mask. Returns the masked text plus the replacement map."""
        return await run_engine(
            ctx,
            _anonymize_text,
            text,
            instruction,
            extra_mask_terms,
            keep_terms,
            project_name,
            source_mode,
        )
