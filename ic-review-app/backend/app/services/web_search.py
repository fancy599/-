"""联网搜索（默认 Tavily 兼容接口），用于"通用内控设计体检"兜底时补充外部监管要求依据。

未配置 web_search_api_key 时 search() 返回空列表，调用方据此降级为纯大模型审查。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def search(query: str, max_results: int | None = None) -> list[dict[str, Any]]:
    """返回 [{title, url, content}]；未配置或失败时返回 []。"""
    settings = get_settings()
    if not settings.web_search_configured:
        return []
    n = max_results or settings.web_search_max_results
    try:
        resp = httpx.post(
            f"{settings.web_search_base_url.rstrip('/')}/search",
            json={
                "api_key": settings.web_search_api_key,
                "query": query,
                "max_results": n,
                "search_depth": "basic",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in (data.get("results") or [])
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("联网搜索失败，已忽略：%s", e)
        return []


def format_for_prompt(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = []
    for r in results[:5]:
        content = (r.get("content") or "")[:500]
        lines.append(f"- {r.get('title', '')}（{r.get('url', '')}）：{content}")
    return "\n".join(lines)
