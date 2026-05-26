"""小程序路由模块导出入口，按需加载页面、worker 与服务实现。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from package.applet_routes.action_policy import RouteActionResolution
    from package.applet_routes.bridge import RealRouteEngineBridge
    from package.applet_routes.navigator import MiniProgramRouteNavigator
    from package.applet_routes.page import RoutePage
    from package.applet_routes.service import RouteService
    from package.applet_routes.worker import AsyncRouteWorker

__all__ = [
    "AsyncRouteWorker",
    "MiniProgramRouteNavigator",
    "RealRouteEngineBridge",
    "RouteActionResolution",
    "RoutePage",
    "RouteService",
    "build_route_action_message",
    "copy_route_state",
    "default_route_state",
    "is_tabbar_route",
    "resolve_route_action",
    "route_action_text",
    "route_worker_main",
]


def __getattr__(name: str):
    """按需导入路由子模块，避免主窗口启动时预加载调试 worker。"""
    if name in {
        "RouteActionResolution",
        "build_route_action_message",
        "is_tabbar_route",
        "resolve_route_action",
        "route_action_text",
    }:
        from package.applet_routes import action_policy

        return getattr(action_policy, name)
    if name == "RealRouteEngineBridge":
        from package.applet_routes.bridge import RealRouteEngineBridge

        return RealRouteEngineBridge
    if name == "MiniProgramRouteNavigator":
        from package.applet_routes.navigator import MiniProgramRouteNavigator

        return MiniProgramRouteNavigator
    if name == "RoutePage":
        from package.applet_routes.page import RoutePage

        return RoutePage
    if name == "RouteService":
        from package.applet_routes.service import RouteService

        return RouteService
    if name in {"copy_route_state", "default_route_state"}:
        from package.applet_routes import state

        return getattr(state, name)
    if name in {"AsyncRouteWorker", "route_worker_main"}:
        from package.applet_routes import worker

        return getattr(worker, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
