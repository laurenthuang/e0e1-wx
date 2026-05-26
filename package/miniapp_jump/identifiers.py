"""从正则匹配结果中提取可用于跨小程序跳转的微信 AppID。"""

from __future__ import annotations

import re


WECHAT_APPID_PATTERN = re.compile(r"\bwx[0-9a-fA-F]{16}\b")


def extract_wechat_appids_from_text(text: str) -> list[str]:
    """从任意文本中提取微信小程序 AppID。"""
    return [match.group(0).lower() for match in WECHAT_APPID_PATTERN.finditer(str(text or ""))]


def extract_wechat_appids_from_match_results(results: list[dict]) -> list[str]:
    """从正则匹配明细中按首次出现顺序提取并去重 AppID。"""
    appids: list[str] = []
    seen: set[str] = set()
    for result in results:
        if not isinstance(result, dict):
            continue
        for field in ("match_text", "line_text"):
            for appid in extract_wechat_appids_from_text(str(result.get(field) or "")):
                if appid in seen:
                    continue
                seen.add(appid)
                appids.append(appid)
    return appids


def extract_wechat_appids_from_match_summary(summary: dict) -> list[str]:
    """从匹配汇总对象中提取可跳转 AppID。"""
    if not isinstance(summary, dict):
        return []
    results = summary.get("results")
    if isinstance(results, list):
        return extract_wechat_appids_from_match_results(results)
    preview_results = summary.get("preview_results")
    if isinstance(preview_results, list):
        return extract_wechat_appids_from_match_results(preview_results)
    return []
