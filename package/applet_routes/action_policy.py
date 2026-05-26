"""小程序路由动作策略，统一处理 tabBar 路由跳转降级。"""

from __future__ import annotations

from dataclasses import dataclass


ROUTE_ACTION_TEXT = {
    "switch_tab": "切换标签页",
    "navigate_to": "打开新页面",
    "redirect_to": "替换当前页",
    "relaunch": "重启到页面",
    "navigate_back": "返回上一页",
}

_TABBAR_DOWNGRADE_ACTIONS = {
    "navigate_to": "switch_tab",
    "redirect_to": "switch_tab",
}


@dataclass(frozen=True)
class RouteActionResolution:
    """描述一次路由动作请求最终应执行的真实动作。"""

    requested_action: str
    actual_action: str
    route: str
    is_tabbar: bool
    downgraded: bool


def normalize_route(route: str) -> str:
    """标准化路由字符串，统一去掉前导斜杠。"""
    return str(route or "").strip().lstrip("/")


def is_tabbar_route(route: str, pages: list[dict]) -> bool:
    """根据当前路由快照判断目标页面是否属于 tabBar。"""
    target_route = normalize_route(route)
    for page in pages or []:
        if not isinstance(page, dict):
            continue
        if normalize_route(str(page.get("route") or "")) != target_route:
            continue
        return bool(page.get("is_tabbar"))
    return False


def resolve_route_action(requested_action: str, route: str, *, is_tabbar: bool) -> RouteActionResolution:
    """根据目标页面类型解析实际应执行的路由动作。"""
    normalized_action = str(requested_action or "").strip()
    actual_action = _TABBAR_DOWNGRADE_ACTIONS.get(normalized_action, normalized_action) if is_tabbar else normalized_action
    return RouteActionResolution(
        requested_action=normalized_action,
        actual_action=actual_action,
        route=normalize_route(route),
        is_tabbar=bool(is_tabbar),
        downgraded=actual_action != normalized_action,
    )


def route_action_text(action: str) -> str:
    """返回动作对应的中文文案。"""
    normalized_action = str(action or "").strip()
    return ROUTE_ACTION_TEXT.get(normalized_action, normalized_action or "-")


def build_route_action_message(resolution: RouteActionResolution, *, ok: bool) -> str:
    """根据真实动作与是否降级生成用户可见状态文案。"""
    actual_text = route_action_text(resolution.actual_action)
    if ok and resolution.downgraded:
        return "目标为 tabBar，已自动切换为标签页"
    return f"{actual_text}完成" if ok else f"{actual_text}失败"


def should_fallback_to_relaunch(resolution: RouteActionResolution, result: dict) -> bool:
    """判断打开动作失败后是否应自动回退为重启到页面。"""
    if resolution.requested_action != "navigate_to":
        return False
    return not bool((result or {}).get("ok"))


def build_relaunch_fallback_message() -> str:
    """生成打开失败后自动重启的提示文案。"""
    return "打开失败，已自动改用重启到页面"
