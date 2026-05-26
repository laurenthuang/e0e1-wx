"""小程序路由搜索过滤的后台计算工具。"""

from __future__ import annotations

import asyncio


def filter_route_pages(pages: list[dict], keyword: str) -> list[dict]:
    """按关键字过滤路由列表，返回可安全传回 UI 的字典副本。"""
    normalized_keyword = str(keyword or "").strip().casefold()
    normalized_pages = [dict(page) for page in pages if isinstance(page, dict)]
    if not normalized_keyword:
        return normalized_pages
    return [
        page
        for page in normalized_pages
        if normalized_keyword in str(page.get("route") or "").casefold()
    ]


async def filter_route_pages_async(pages: list[dict], keyword: str) -> list[dict]:
    """在线程中执行路由过滤，避免 UI 主线程做数据处理。"""
    return await asyncio.to_thread(filter_route_pages, pages, keyword)
