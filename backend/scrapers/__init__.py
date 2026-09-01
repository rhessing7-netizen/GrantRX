"""GrantRx hybrid scholarship scraping pipeline.

Modules:
- scrapers.fetcher       : async HTML fetcher (httpx + Playwright fallback)
- scrapers.parsers       : deterministic BeautifulSoup parsers
- scrapers.llm_parser    : LLM fallback extractor (OpenAI gpt-4o-mini / LiteLLM)
- scrapers.runner        : CLI runner, dedup upsert, auto-archival, daily scheduler
"""

__all__ = ["run_pipeline", "run_daily"]
