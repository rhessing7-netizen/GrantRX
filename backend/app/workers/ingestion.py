"""Ingestion worker that bridges the FastAPI /ingest endpoint to the scraper pipeline."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def run_ingestion(target: str = "all") -> dict:
    """Synchronous wrapper used by the FastAPI /ingest endpoint.

    Returns a summary dict. The actual scraping is async; we run it on a
    fresh event loop because the worker may be called from a sync context.
    """
    from scrapers.runner import run_pipeline

    logger.info("Starting ingestion (target=%s)...", target)

    try:
        results = asyncio.run(run_pipeline(target, persist=True))
    except Exception as exc:  # noqa: BLE001
        logger.error("Ingestion failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    summary = {
        "status": "ok",
        "total": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "llm_fallback": sum(1 for r in results if r.status == "llm_fallback"),
        "errors": sum(1 for r in results if r.status == "error"),
    }
    logger.info("Ingestion complete: %s", summary)
    return summary
