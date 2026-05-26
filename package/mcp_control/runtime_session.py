"""摘要：实现 SKILL.md 所需 MCP 分组工具的异步会话、采集、分析与报告逻辑。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from package.config.defaults import DEFAULT_DEVTOOLS_CDP_PORT
from package.mcp_control.cdp_client import JsonDict, LocalCdpClient
from package.mcp_control.crypto_helpers import (
    auto_detect_encoding,
    decode_payload,
    decrypt_payload,
    detect_ecb_pattern,
    identify_crypto_pattern,
    json_text,
)

DEFAULT_WS_URL = f"ws://127.0.0.1:{DEFAULT_DEVTOOLS_CDP_PORT}"
SENSITIVE_FIELD_RE = re.compile(r"phone|mobile|email|idcard|identity|realName|address|bank|openid|unionid|session_key|token|cookie|authorization|password|secret", re.I)
AUTH_FIELD_RE = re.compile(r"authorization|token|session|cookie|openid|unionid|userId|memberId|uid|sign|signature|timestamp|nonce|enc", re.I)
ID_FIELD_RE = re.compile(r"(^|\.|_|-)(userId|uid|memberId|accountId|orderId|couponId|addressId|invoiceId|recordId|bookId|id)$", re.I)
PAYMENT_RE = re.compile(r"pay|payment|order|trade|refund|wallet|coupon|积分|支付|订单|退款|提现", re.I)
UPLOAD_RE = re.compile(r"upload|file|image|avatar|oss|cos|photo|media|上传|头像|图片", re.I)
DEBUG_ADMIN_RE = re.compile(r"debug|test|admin|manage|internal|dev|staging|mock|后台|管理", re.I)
SIGN_RE = re.compile(r"sign|signature|timestamp|nonce|enc|authen-sign", re.I)
ROUTE_NAVIGATOR_JS_PATH = Path("package/applet_routes/nav_inject.js")
LOGIN_ROUTE_RE = re.compile(r"login|auth|passport|signin|register|bind", re.I)
SENSITIVE_STORAGE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("oss_cos_s3_credentials", re.compile(r"accessKeyId|secretAccessKey|securityToken|bucket|oss|cos|s3", re.I)),
    ("database_middleware", re.compile(r"mysql|redis|jdbc|mongodb|mongo|postgres|pgsql|sqlserver|rabbitmq|kafka", re.I)),
    ("third_party_service", re.compile(r"appSecret|apiKey|privateKey|clientSecret|client_id|appId.*secret|secret.*appId", re.I)),
    ("payment_credentials", re.compile(r"mchId|mchKey|paySecret|wxPayKey|payKey|paymentSecret", re.I)),
    ("sms_push_credentials", re.compile(r"smsKey|smsSecret|pushSecret|twilioKey|jpush|umeng|aliyunSms", re.I)),
    ("jwt_session", re.compile(r"refreshToken|sessionKey|session_key|jwt|bearer|idToken|accessToken|privateKey", re.I)),
    ("hardcoded_password", re.compile(r"password|passwd|pwd", re.I)),
    ("internal_config", re.compile(r"serverUrl|baseUrl|internalHost|adminPassword|intranet|internal|localhost|127\.0\.0\.1|10\.|172\.16|192\.168", re.I)),
)
UPLOAD_SURFACE_RE = re.compile(r"upload|chooseImage|chooseMedia|avatar|file|media|photo|image|上传|头像|选择图片|图片|文件", re.I)


def now_iso() -> str:
    """返回当前本地时间 ISO 字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def safe_json_loads(value: Any) -> Any:
    """尽量把字符串解析为 JSON，失败时返回原值。"""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def compact_text(value: Any, limit: int = 2000) -> str:
    """把任意值压缩成限定长度的预览文本。"""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def parse_url_query(url: str) -> dict[str, Any]:
    """解析 URL 查询参数为普通字典。"""
    return {key: values[-1] if values else "" for key, values in parse_qs(urlparse(str(url or "")).query).items()}


class IgnoreOptionalCdpError:
    """忽略兼容性 CDP 命令失败，避免可选 domain 影响主流程。"""

    def __enter__(self) -> None:
        """进入忽略异常上下文。"""
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        """退出时吞掉异常。"""
        return True


class McpRuntimeSession:
    """保存一个 MCP HTTP 服务进程内的 CDP 连接、采集缓存和分析状态。"""

    def __init__(self) -> None:
        """初始化 CDP 客户端、请求/脚本缓存和后台任务状态。"""
        self.cdp = LocalCdpClient(disconnect_grace_seconds=1.8)
        self.requests: dict[str, JsonDict] = {}
        self.request_order: deque[str] = deque(maxlen=1500)
        self.scripts: dict[str, JsonDict] = {}
        self.contexts: dict[int, JsonDict] = {}
        self.console_events: deque[JsonDict] = deque(maxlen=500)
        self.websocket_events: deque[JsonDict] = deque(maxlen=500)
        self.selected_appservice_context_id: int | None = None
        self.selected_target_id: str | None = None
        self.jobs: dict[str, JsonDict] = {}
        self._network_registered = False
        self._debugger_registered = False
        self._console_registered = False

    async def connection_ops(self, action: str, **kwargs: Any) -> str:
        """执行连接类 MCP 操作并返回 JSON 文本。"""
        action = str(action or "status")
        if action == "status":
            return json_text(await self.status())
        if action == "connect_wmpf":
            return json_text(await self.connect_wmpf(str(kwargs.get("ws_url") or kwargs.get("wsUrl") or DEFAULT_WS_URL)))
        if action == "select_appservice_context":
            return json_text(await self.select_appservice_context())
        if action == "list_targets":
            return json_text(await self.list_targets())
        if action == "switch_target":
            return json_text(await self.switch_target(str(kwargs.get("target_id") or kwargs.get("targetId") or "")))
        if action == "cdp_call":
            return json_text(await self.cdp_call(str(kwargs.get("method") or ""), kwargs.get("params") or {}, kwargs.get("sessionId") or kwargs.get("session_id")))
        if action == "cdp_call_target":
            return json_text(await self.cdp_call_target(str(kwargs.get("target_id") or kwargs.get("targetId") or ""), str(kwargs.get("method") or ""), kwargs.get("params") or {}))
        return json_text({"ok": False, "error": f"未知 connection_ops action: {action}"})

    async def network_ops(self, action: str, **kwargs: Any) -> str:
        """执行网络采集、Hook 和接口资产类 MCP 操作。"""
        action = str(action or "")
        if action == "network_enable":
            await self.ensure_network_enabled()
            return json_text({"ok": True, "message": "Network domain 已启用"})
        if action == "hook_wx_request":
            return json_text(await self.hook_wx_request())
        if action == "hook_upload_apis":
            return json_text(await self.hook_upload_apis())
        if action == "install_early_hooks":
            return json_text(await self.install_early_hooks())
        if action == "hook_fetch_and_xhr":
            return json_text(await self.hook_fetch_and_xhr())
        if action == "fetch_from_page":
            return json_text(
                await self.fetch_from_page(
                    str(kwargs.get("url") or ""),
                    method=str(kwargs.get("method") or "GET"),
                    headers=kwargs.get("headers"),
                    body=kwargs.get("body"),
                    await_promise=bool(kwargs.get("await_promise", True)),
                )
            )
        if action == "upload_formdata_from_page":
            return json_text(
                await self.upload_formdata_from_page(
                    str(kwargs.get("url") or ""),
                    method=str(kwargs.get("method") or "POST"),
                    headers=kwargs.get("headers"),
                    fields=kwargs.get("fields"),
                    files=kwargs.get("files"),
                    await_promise=bool(kwargs.get("await_promise", True)),
                )
            )
        if action == "get_all_requests":
            return json_text(await self.get_all_requests(limit=int(kwargs.get("limit") or 200), keyword=kwargs.get("keyword"), domain=kwargs.get("domain"), path_prefix=kwargs.get("pathPrefix") or kwargs.get("path_prefix")))
        if action == "get_request_detail":
            return json_text(await self.get_request_detail(str(kwargs.get("request_id") or kwargs.get("requestId") or kwargs.get("id") or "")))
        if action == "get_recent_requests":
            return json_text(await self.get_recent_requests(int(kwargs.get("limit") or 50), domain=kwargs.get("domain"), path_prefix=kwargs.get("pathPrefix") or kwargs.get("path_prefix"), keyword=kwargs.get("keyword"), compact=bool(kwargs.get("compact", True))))
        if action == "get_response_body":
            return json_text(await self.get_response_body(str(kwargs.get("request_id") or kwargs.get("requestId") or "")))
        if action == "get_recent_console":
            return json_text(await self.get_recent_console(int(kwargs.get("limit") or 50)))
        if action == "get_hooked_requests":
            return json_text({"ok": True, "requests": (await self.get_hooked_requests())[-max(1, int(kwargs.get("limit") or 50)): ]})
        if action == "search_runtime_keywords":
            keywords = kwargs.get("keywords") or kwargs.get("query") or kwargs.get("keyword") or []
            if isinstance(keywords, str):
                keywords = [keywords]
            return json_text(await self.search_runtime_keywords(list(keywords)))
        if action == "trace_request_callstack":
            return json_text(await self.trace_request_callstack(str(kwargs.get("request_id") or kwargs.get("requestId") or "")))
        if action == "inspect_wx_config":
            return json_text(await self.inspect_wx_config())
        return json_text({"ok": False, "error": f"未知 network_ops action: {action}"})

    async def runtime_ops(self, action: str, **kwargs: Any) -> str:
        """执行运行时求值、快照和状态检查类 MCP 操作。"""
        action = str(action or "")
        if action == "runtime_eval":
            return json_text(await self.runtime_eval(str(kwargs.get("expression") or ""), await_promise=bool(kwargs.get("await_promise", True)), context_id=kwargs.get("context_id") or kwargs.get("contextId")))
        if action == "runtime_eval_appservice":
            return json_text(await self.runtime_eval(str(kwargs.get("expression") or ""), await_promise=bool(kwargs.get("await_promise", True)), context_id=self.selected_appservice_context_id))
        if action == "dump_runtime_snapshot":
            return json_text(await self.dump_runtime_snapshot())
        if action == "scan_sensitive_storage":
            return json_text(await self.scan_sensitive_storage())
        if action == "inspect_upload_surface":
            return json_text(await self.inspect_upload_surface())
        if action == "get_basic_page_info":
            return json_text(await self.get_basic_page_info())
        if action == "get_document_html":
            return json_text(await self.get_document_html(int(kwargs.get("maxLength") or kwargs.get("max_length") or 20_000)))
        if action == "query_selector_text":
            return json_text(await self.query_selector_text(str(kwargs.get("selector") or ""), int(kwargs.get("maxLength") or kwargs.get("max_length") or 10_000)))
        if action == "inspect_window_keys":
            return json_text(await self.inspect_window_keys(kwargs.get("pattern"), int(kwargs.get("limit") or 200)))
        if action == "search_global_string":
            return json_text(await self.search_global_string(str(kwargs.get("keyword") or ""), int(kwargs.get("maxLength") or kwargs.get("max_length") or 20_000)))
        if action == "inspect_vuex_store":
            return json_text(await self.inspect_vuex_store())
        if action == "patch_vuex_state":
            return json_text(await self.patch_vuex_state(str(kwargs.get("path") or ""), kwargs.get("value"), bool(kwargs.get("dryRun", True)), bool(kwargs.get("requireConfirm", False))))
        if action == "restore_vuex_state":
            return json_text(await self.restore_vuex_state(bool(kwargs.get("dryRun", True)), bool(kwargs.get("requireConfirm", False))))
        if action == "list_interactive_elements":
            return json_text(await self.list_interactive_elements())
        if action == "safe_click_and_observe":
            return json_text(await self.safe_click_and_observe(str(kwargs.get("selector") or ""), bool(kwargs.get("requireConfirm", False))))
        if action == "input_text_and_observe":
            return json_text(await self.input_text_and_observe(str(kwargs.get("selector") or ""), str(kwargs.get("text") or "")))
        return json_text({"ok": False, "error": f"未知 runtime_ops action: {action}"})

    async def route_ops(self, action: str, **kwargs: Any) -> str:
        """执行小程序路由、守卫和跳转类 MCP 操作。"""
        action = str(action or "")
        if action == "inspect_routes":
            return json_text(await self.inspect_routes())
        if action == "enable_redirect_guard":
            return json_text(await self.set_redirect_guard(True))
        if action == "disable_redirect_guard":
            return json_text(await self.set_redirect_guard(False))
        if action in {"navigate_route", "navigate_route_with_guard"}:
            wait_arg = kwargs.get("wait_ms")
            return json_text(
                await self.navigate_route(
                    str(kwargs.get("route") or ""),
                    is_tabbar=bool(kwargs.get("is_tabbar", False)),
                    guard=action == "navigate_route_with_guard",
                    wait_ms=int(wait_arg if wait_arg is not None else 1200),
                )
            )
        return json_text({"ok": False, "error": f"未知 route_ops action: {action}"})

    async def ensure_route_navigator(self) -> JsonDict:
        """注入共享路由导航脚本到当前页面/window Runtime。"""
        script = await asyncio.to_thread(ROUTE_NAVIGATOR_JS_PATH.read_text, encoding="utf-8")
        injected = await self.runtime_eval(script)
        if not injected.get("ok"):
            return {"ok": False, "stage": "inject", "error": injected}
        probe = await self.runtime_eval("(()=>({ok:!!(window.__routeNavigator), type:typeof window.__routeNavigator}))()")
        value = probe.get("value") if isinstance(probe, dict) else None
        if isinstance(value, dict) and value.get("ok"):
            return {"ok": True, "navigator": value}
        return {"ok": False, "stage": "probe", "error": probe}

    async def inspect_routes(self) -> JsonDict:
        """读取小程序路由配置、当前路由和防跳转守卫状态。"""
        ready = await self.ensure_route_navigator()
        if not ready.get("ok"):
            return ready
        result = await self.runtime_eval("window.__routeNavigator.fetchConfigJson()", await_promise=True)
        if not result.get("ok"):
            return {"ok": False, "stage": "fetch", "error": result}
        payload = safe_json_loads(result.get("value"))
        if not isinstance(payload, dict):
            return {"ok": False, "stage": "parse", "raw": result.get("value")}
        return {
            "ok": True,
            "pages": payload.get("pages") or [],
            "tabbar_pages": payload.get("tabBarPages") or [],
            "current_route": str(payload.get("currentRoute") or ""),
            "guard_enabled": bool(payload.get("guardEnabled")),
            "blocked_redirects_count": int(payload.get("blockedRedirectsCount") or 0),
        }

    async def set_redirect_guard(self, enabled: bool) -> JsonDict:
        """开启或关闭小程序路由防跳转守卫。"""
        ready = await self.ensure_route_navigator()
        if not ready.get("ok"):
            return ready
        method = "enableRedirectGuardJson" if enabled else "disableRedirectGuardJson"
        result = await self.runtime_eval(f"window.__routeNavigator.{method}()", await_promise=True)
        payload = safe_json_loads(result.get("value")) if result.get("ok") else result
        return {"ok": bool(result.get("ok")), "enabled": bool(enabled), "result": payload}

    async def navigate_route(
        self,
        route: str,
        *,
        is_tabbar: bool = False,
        guard: bool = False,
        wait_ms: int = 1200,
    ) -> JsonDict:
        """执行路由跳转，可选防跳转守卫，并返回最终路由观测。"""
        target = self.normalize_miniapp_route(route)
        if not target:
            return {"ok": False, "error": "route 不能为空"}
        before = await self.inspect_routes()
        if not before.get("ok"):
            return before
        if guard:
            guard_result = await self.set_redirect_guard(True)
            if not guard_result.get("ok"):
                return guard_result
            before = await self.inspect_routes()
        method = "switchTabJson" if is_tabbar else "reLaunchJson"
        jump = await self.runtime_eval(
            f"window.__routeNavigator.{method}({json.dumps(target, ensure_ascii=False)})",
            await_promise=True,
        )
        jump_value = safe_json_loads(jump.get("value")) if jump.get("ok") else jump
        delay = min(max(int(wait_ms or 0), 0), 10_000) / 1000
        if delay:
            await asyncio.sleep(delay)
        after = await self.inspect_routes()
        before_blocked = int(before.get("blocked_redirects_count") or 0)
        after_blocked = int(after.get("blocked_redirects_count") or 0) if after.get("ok") else before_blocked
        final_route = str(after.get("current_route") or "") if after.get("ok") else ""
        guard_enabled = bool(after.get("guard_enabled")) if after.get("ok") else bool(guard)
        rehook = await self.rehook_after_route_navigation() if after.get("ok") else {"ok": False, "skipped": True, "reason": "route inspect failed"}
        upload_indicators = await self.inspect_upload_surface() if after.get("ok") else {"ok": False, "skipped": True, "reason": "route inspect failed"}
        return {
            "ok": bool(jump.get("ok")) and bool(after.get("ok")),
            "action": method,
            "target_route": target,
            "is_tabbar": bool(is_tabbar),
            "guard_requested": bool(guard),
            "before": before,
            "jump": jump_value,
            "after": after,
            "final_route": final_route,
            "blocked_redirects_delta": after_blocked - before_blocked,
            "rehook": rehook,
            "uploadIndicators": upload_indicators,
            "bouncedToLogin": self.detect_route_bounce(
                target,
                final_route,
                guard_enabled=guard_enabled,
                before_blocked=before_blocked,
                after_blocked=after_blocked,
            ),
        }

    def detect_route_bounce(
        self,
        target_route: str,
        final_route: str,
        *,
        guard_enabled: bool,
        before_blocked: int,
        after_blocked: int,
    ) -> bool:
        """判断目标页是否在跳转后弹回登录或其他非目标页。"""
        target = self.normalize_miniapp_route(target_route)
        final = self.normalize_miniapp_route(final_route)
        if not final:
            return False
        if LOGIN_ROUTE_RE.search(final):
            return True
        if target and final != target:
            guard_blocked = bool(guard_enabled) and int(after_blocked) > int(before_blocked)
            return not guard_blocked
        return False

    @staticmethod
    def normalize_miniapp_route(route: str) -> str:
        """标准化小程序路由，去掉前导斜杠和空白。"""
        return str(route or "").strip().lstrip("/")

    async def debugger_ops(self, action: str, **kwargs: Any) -> str:
        """执行源码、断点、调用栈和 WebSocket 类 MCP 操作。"""
        action = str(action or "")
        if action == "list_scripts":
            return json_text(await self.list_scripts(str(kwargs.get("url_filter") or kwargs.get("urlFilter") or "")))
        if action == "get_script_source":
            return json_text(await self.get_script_source(script_id=kwargs.get("script_id") or kwargs.get("scriptId"), url=kwargs.get("url"), offset=kwargs.get("offset"), length=int(kwargs.get("length") or 2000), start_line=kwargs.get("start_line") or kwargs.get("startLine"), end_line=kwargs.get("end_line") or kwargs.get("endLine")))
        if action == "save_script_source":
            return json_text(await self.save_script_source(str(kwargs.get("file_path") or kwargs.get("filePath") or ""), script_id=kwargs.get("script_id") or kwargs.get("scriptId"), url=kwargs.get("url")))
        if action == "search_in_sources":
            return json_text(await self.search_in_sources(str(kwargs.get("query") or ""), case_sensitive=bool(kwargs.get("case_sensitive", False)), is_regex=bool(kwargs.get("is_regex", False)), max_results=int(kwargs.get("max_results") or 50), url_filter=kwargs.get("url_filter") or kwargs.get("urlFilter")))
        if action == "evaluate_script":
            return json_text(await self.runtime_eval(str(kwargs.get("expression") or ""), await_promise=bool(kwargs.get("await_promise", True)), context_id=kwargs.get("context_id") or kwargs.get("contextId")))
        if action == "break_on_xhr":
            return json_text(await self.break_on_xhr(str(kwargs.get("url") or kwargs.get("pattern") or "")))
        if action == "set_breakpoint_on_text":
            return json_text(await self.set_breakpoint_on_text(str(kwargs.get("text") or kwargs.get("query") or "")))
        if action == "get_paused_info":
            return json_text(await self.get_paused_info())
        if action == "resume_execution":
            return json_text(await self.resume_execution())
        if action == "step":
            return json_text(await self.step(str(kwargs.get("kind") or kwargs.get("type") or "over")))
        if action == "get_websocket_messages":
            return json_text(await self.get_websocket_messages())
        return json_text({"ok": False, "error": f"未知 debugger_ops action: {action}"})

    async def analysis_ops(self, action: str, **kwargs: Any) -> str:
        """执行接口资产、风险线索、重放计划和报告导出类 MCP 操作。"""
        action = str(action or "")
        requests = (await self.get_all_requests(limit=int(kwargs.get("limit") or 500))).get("requests", [])
        if action == "get_api_inventory":
            return json_text(self.build_api_inventory(requests))
        if action == "analyze_auth_surface":
            return json_text(self.analyze_auth_surface(requests))
        if action == "find_idor_candidates":
            return json_text(self.find_idor_candidates(requests))
        if action == "find_sensitive_data_exposure":
            return json_text(self.find_sensitive_data_exposure(requests))
        if action == "find_payment_and_order_surfaces":
            return json_text(self.find_by_regex(requests, PAYMENT_RE, "payment_order"))
        if action == "find_upload_surfaces":
            return json_text(self.find_by_regex(requests, UPLOAD_RE, "upload"))
        if action == "find_debug_admin_surfaces":
            return json_text(self.find_by_regex(requests, DEBUG_ADMIN_RE, "debug_admin"))
        if action == "find_sign_related_requests":
            return json_text(self.find_by_regex(requests, SIGN_RE, "sign_related"))
        if action == "build_replay_plan":
            return json_text(await self.build_replay_plan(str(kwargs.get("request_id") or kwargs.get("requestId") or "")))
        if action == "compare_two_requests":
            return json_text(await self.compare_two_requests(str(kwargs.get("request_id_a") or kwargs.get("requestIdA") or ""), str(kwargs.get("request_id_b") or kwargs.get("requestIdB") or "")))
        if action == "passive_param_fuzz_suggestions":
            return json_text(self.passive_param_fuzz_suggestions(requests))
        if action == "generate_security_notes":
            return json_text(self.generate_security_notes(requests))
        if action == "generate_api_table_markdown":
            return self.generate_api_table_markdown(requests)
        if action == "export_session":
            return json_text(await self.export_session(requests))
        return json_text({"ok": False, "error": f"未知 analysis_ops action: {action}"})

    async def decrypt_ops(self, action: str, **kwargs: Any) -> str:
        """执行编码识别、解码、解密和运行时加密函数发现。"""
        action = str(action or "")
        value = str(kwargs.get("value") or "")
        if action == "auto_detect_encoding":
            return json_text(auto_detect_encoding(value))
        if action in {"decode_payload", "decode_base64"}:
            encoding = "base64" if action == "decode_base64" else str(kwargs.get("input_encoding") or kwargs.get("encoding") or "auto")
            return json_text(decode_payload(value, encoding))
        if action == "decrypt_payload":
            return json_text(decrypt_payload(value, algorithm=str(kwargs.get("algorithm") or "aes"), key=str(kwargs.get("key") or ""), mode=str(kwargs.get("mode") or "cbc"), iv=str(kwargs.get("iv") or ""), input_encoding=str(kwargs.get("input_encoding") or "base64"), key_encoding=str(kwargs.get("key_encoding") or "utf-8"), iv_encoding=str(kwargs.get("iv_encoding") or "utf-8")))
        if action == "run_decrypt_pipeline":
            return json_text(await self.run_decrypt_pipeline(value, kwargs.get("steps") or []))
        if action == "detect_ecb_pattern":
            return json_text(detect_ecb_pattern(value, str(kwargs.get("input_encoding") or "base64")))
        if action == "discover_runtime_crypto_functions":
            return json_text(await self.discover_runtime_crypto_functions())
        if action == "call_runtime_crypto_function":
            return json_text(await self.call_runtime_crypto_function(str(kwargs.get("function_name") or kwargs.get("functionName") or ""), kwargs.get("args") or []))
        return json_text({"ok": False, "error": f"未知 decrypt_ops action: {action}"})

    async def reverse_ops(self, action: str, **kwargs: Any) -> str:
        """执行逆向案例匹配、加密模式识别和策略建议。"""
        action = str(action or "detect_reverse_strategy")
        text = str(kwargs.get("text") or kwargs.get("source") or "")
        if action == "identify_crypto_pattern":
            return json_text(identify_crypto_pattern(text))
        if action == "match_reverse_cases":
            return json_text(self.match_reverse_cases(text))
        if action == "detect_reverse_strategy":
            return json_text(self.detect_reverse_strategy(text))
        return json_text({"ok": False, "error": f"未知 reverse_ops action: {action}"})

    async def replay_ops(self, action: str, **kwargs: Any) -> str:
        """执行安全重放任务管理；默认只生成计划，不自动发送写请求。"""
        action = str(action or "")
        if action == "start_auto_replay":
            request_id = str(kwargs.get("request_id") or kwargs.get("requestId") or "")
            plan = await self.build_replay_plan(request_id)
            job_id = f"replay-{int(time.time() * 1000)}"
            self.jobs[job_id] = {"id": job_id, "type": "replay", "status": "planned", "plan": plan, "createdAt": now_iso()}
            return json_text(self.jobs[job_id])
        if action == "get_replay_job":
            return json_text(self.jobs.get(str(kwargs.get("job_id") or kwargs.get("jobId") or ""), {"ok": False, "error": "job not found"}))
        return json_text({"ok": False, "error": f"未知 replay_ops action: {action}"})

    async def pentest_ops(self, action: str, **kwargs: Any) -> str:
        """执行主动扫描任务管理；当前仅记录授权扫描计划并保持任务隔离。"""
        action = str(action or "")
        if action == "start_pentest_scan":
            job_id = f"pentest-{int(time.time() * 1000)}"
            self.jobs[job_id] = {"id": job_id, "type": "pentest", "status": "queued", "scope": kwargs.get("scope") or "current-session", "createdAt": now_iso(), "note": "主动验证请在授权环境按生成计划逐项执行"}
            return json_text(self.jobs[job_id])
        if action == "get_pentest_job":
            return json_text(self.jobs.get(str(kwargs.get("job_id") or kwargs.get("jobId") or ""), {"ok": False, "error": "job not found"}))
        if action == "list_pentest_jobs":
            return json_text([job for job in self.jobs.values() if job.get("type") == "pentest"])
        return json_text({"ok": False, "error": f"未知 pentest_ops action: {action}"})

    async def status(self) -> JsonDict:
        """汇总 MCP、CDP、缓存和上下文状态。"""
        return {"ok": True, "cdp": self.cdp.status(), "selectedAppserviceContextId": self.selected_appservice_context_id, "requestCount": len(self.requests), "scriptCount": len(self.scripts), "contextCount": len(self.contexts)}

    async def connect_wmpf(self, ws_url: str = DEFAULT_WS_URL) -> JsonDict:
        """连接本机 WMPF/CDP，并注册 Network/Runtime/Debugger 事件。"""
        result = await self.cdp.connect(ws_url)
        await self.ensure_runtime_enabled()
        await self.ensure_network_enabled()
        await self.ensure_debugger_enabled()
        return {"ok": True, **result, "status": await self.status()}

    async def ensure_runtime_enabled(self) -> None:
        """启用 Runtime domain 并注册上下文、控制台事件。"""
        if not self._console_registered:
            self.cdp.on("Runtime.executionContextCreated", self._on_execution_context_created)
            self.cdp.on("Runtime.consoleAPICalled", self._on_console_event)
            self.cdp.on("Runtime.exceptionThrown", self._on_console_event)
            self._console_registered = True
        with IgnoreOptionalCdpError():
            await self.cdp.send("Runtime.enable", timeout_ms=5000)

    async def ensure_network_enabled(self) -> None:
        """启用 Network domain 并注册网络/WebSocket 事件。"""
        if not self._network_registered:
            for method in ("Network.requestWillBeSent", "Network.requestWillBeSentExtraInfo", "Network.responseReceived", "Network.responseReceivedExtraInfo", "Network.loadingFinished", "Network.loadingFailed", "Network.webSocketCreated", "Network.webSocketFrameSent", "Network.webSocketFrameReceived", "Network.webSocketClosed"):
                self.cdp.on(method, self._on_network_event)
            self._network_registered = True
        await self.cdp.send("Network.enable", timeout_ms=5000)

    async def ensure_debugger_enabled(self) -> None:
        """启用 Debugger domain 并注册脚本事件。"""
        if not self._debugger_registered:
            self.cdp.on("Debugger.scriptParsed", self._on_script_parsed)
            self.cdp.on("Debugger.paused", self._on_console_event)
            self._debugger_registered = True
        with IgnoreOptionalCdpError():
            await self.cdp.send("Debugger.enable", timeout_ms=5000)

    async def list_targets(self) -> JsonDict:
        """列出 CDP Target 信息。"""
        response = await self.cdp.send("Target.getTargets", timeout_ms=8000)
        return {"ok": True, "targets": response.get("result", {}).get("targetInfos", [])}

    async def switch_target(self, target_id: str) -> JsonDict:
        """记录目标 targetId，供后续人工定位使用。"""
        if not target_id:
            return {"ok": False, "error": "target_id 不能为空"}
        self.selected_target_id = target_id
        return {"ok": True, "selectedTargetId": target_id}

    async def select_appservice_context(self) -> JsonDict:
        """自动选择最像 appservice 的 Runtime context。"""
        await self.ensure_runtime_enabled()
        probes = []
        for context_id in list(self.contexts.keys()):
            probe = await self.runtime_eval("(()=>({hasWx:typeof wx!=='undefined',hasRequire:typeof require!=='undefined',hasPages:typeof getCurrentPages!=='undefined'}))()", context_id=context_id)
            value = probe.get("value") if isinstance(probe, dict) else None
            score = (4 if isinstance(value, dict) and value.get("hasWx") else 0) + (3 if isinstance(value, dict) and value.get("hasRequire") else 0) + (3 if isinstance(value, dict) and value.get("hasPages") else 0)
            probes.append({"contextId": context_id, "score": score, "probe": value})
        if probes:
            probes.sort(key=lambda item: int(item.get("score") or 0), reverse=True)
            self.selected_appservice_context_id = int(probes[0]["contextId"])
            return {"ok": True, "selectedContextId": self.selected_appservice_context_id, "probes": probes}
        return {"ok": False, "error": "未发现 Runtime context，请先打开/重启小程序并重试", "probes": []}

    async def runtime_eval(self, expression: str, *, await_promise: bool = True, context_id: Any = None) -> JsonDict:
        """执行 Runtime.evaluate 并清理 CDP 结果结构。"""
        params: JsonDict = {"expression": expression, "returnByValue": True, "awaitPromise": bool(await_promise)}
        if context_id not in {None, ""}:
            params["contextId"] = int(context_id)
        response = await self.cdp.send("Runtime.evaluate", params, timeout_ms=15000)
        result_root = response.get("result", {})
        result = result_root.get("result", {})
        if result_root.get("exceptionDetails"):
            return {"ok": False, "exception": result_root.get("exceptionDetails"), "raw": response}
        return {"ok": True, "type": result.get("type"), "value": result.get("value"), "description": result.get("description")}

    async def hook_wx_request(self) -> JsonDict:
        """在 appservice 中注入非破坏性 wx.request Hook。"""
        if self.selected_appservice_context_id is None:
            await self.select_appservice_context()
        script = r"""
(()=>{const g=globalThis;if(g.__MCP_WX_REQUEST_HOOKED__)return {hooked:true,reused:true,count:(g.__MCP_WX_REQUESTS__||[]).length};
g.__MCP_WX_REQUESTS__=[];const wxObj=g.wx;if(!wxObj||typeof wxObj.request!=='function')return {hooked:false,error:'wx.request not found'};
const raw=wxObj.request;wxObj.request=function(opts){const id='wx-'+Date.now()+'-'+Math.random().toString(16).slice(2);const rec={id,source:'wx',url:opts&&opts.url||'',method:(opts&&opts.method||'GET').toUpperCase(),requestHeaders:opts&&opts.header||{},requestBodyPreview:opts&&opts.data,callStack:(new Error()).stack,timestamp:new Date().toISOString()};g.__MCP_WX_REQUESTS__.push(rec);const next=Object.assign({},opts||{});const ok=next.success,fail=next.fail,done=next.complete;next.success=function(res){rec.statusCode=res&&res.statusCode;rec.responseHeaders=res&&res.header||{};rec.responseBodyPreview=res&&res.data;rec.finishedAt=new Date().toISOString();if(typeof ok==='function')return ok.apply(this,arguments)};next.fail=function(err){rec.error=String(err&&err.errMsg||err);rec.finishedAt=new Date().toISOString();if(typeof fail==='function')return fail.apply(this,arguments)};next.complete=function(res){rec.completed=true;if(typeof done==='function')return done.apply(this,arguments)};return raw.call(this,next)};g.__MCP_WX_REQUEST_HOOKED__=true;return {hooked:true,reused:false};})()
"""
        return await self.runtime_eval(script, context_id=self.selected_appservice_context_id)

    async def hook_upload_apis(self) -> JsonDict:
        """在 appservice 中尽早注入 wx.uploadFile/chooseImage/chooseMedia Hook。"""
        if self.selected_appservice_context_id is None:
            selected = await self.select_appservice_context()
            if not selected.get("ok"):
                return {"ok": False, "stage": "select_appservice_context", "error": selected}
        script = r"""
(()=>{const g=globalThis;if(g.__MCP_UPLOAD_HOOKED__)return {hooked:true,reused:true,count:(g.__MCP_UPLOAD_REQUESTS__||[]).length};
g.__MCP_UPLOAD_REQUESTS__=g.__MCP_UPLOAD_REQUESTS__||[];const wxObj=g.wx;if(!wxObj)return {hooked:false,error:'wx not found'};
const mk=(kind)=>kind+'-'+Date.now()+'-'+Math.random().toString(16).slice(2);
const copy=(obj)=>{try{return Object.assign({},obj||{})}catch(e){return {}}};
const hooks={};
if(typeof wxObj.uploadFile==='function'){const raw=wxObj.uploadFile;wxObj.uploadFile=function(opts){const id=mk('upload');const rec={id,source:'upload',api:'wx.uploadFile',url:opts&&opts.url||'',method:'POST',filePath:opts&&opts.filePath,name:opts&&opts.name,requestHeaders:opts&&opts.header||{},requestBodyPreview:opts&&opts.formData,callStack:(new Error()).stack,timestamp:new Date().toISOString()};g.__MCP_UPLOAD_REQUESTS__.push(rec);const next=Object.assign({},opts||{});const ok=next.success,fail=next.fail,done=next.complete;next.success=function(res){rec.statusCode=res&&res.statusCode;rec.responseHeaders=res&&res.header||{};rec.responseBodyPreview=res&&res.data;rec.finishedAt=new Date().toISOString();if(typeof ok==='function')return ok.apply(this,arguments)};next.fail=function(err){rec.error=String(err&&err.errMsg||err);rec.finishedAt=new Date().toISOString();if(typeof fail==='function')return fail.apply(this,arguments)};next.complete=function(res){rec.completed=true;if(typeof done==='function')return done.apply(this,arguments)};return raw.call(this,next)};hooks.uploadFile=true}
if(typeof wxObj.chooseImage==='function'){const raw=wxObj.chooseImage;wxObj.chooseImage=function(opts){const id=mk('chooseImage');const rec={id,source:'chooseImage',api:'wx.chooseImage',method:'LOCAL',options:copy(opts),callStack:(new Error()).stack,timestamp:new Date().toISOString()};g.__MCP_UPLOAD_REQUESTS__.push(rec);const next=Object.assign({},opts||{});const ok=next.success,fail=next.fail,done=next.complete;next.success=function(res){rec.tempFilePaths=res&&res.tempFilePaths;rec.tempFiles=res&&res.tempFiles;rec.finishedAt=new Date().toISOString();if(typeof ok==='function')return ok.apply(this,arguments)};next.fail=function(err){rec.error=String(err&&err.errMsg||err);rec.finishedAt=new Date().toISOString();if(typeof fail==='function')return fail.apply(this,arguments)};next.complete=function(res){rec.completed=true;if(typeof done==='function')return done.apply(this,arguments)};return raw.call(this,next)};hooks.chooseImage=true}
if(typeof wxObj.chooseMedia==='function'){const raw=wxObj.chooseMedia;wxObj.chooseMedia=function(opts){const id=mk('chooseMedia');const rec={id,source:'chooseMedia',api:'wx.chooseMedia',method:'LOCAL',options:copy(opts),callStack:(new Error()).stack,timestamp:new Date().toISOString()};g.__MCP_UPLOAD_REQUESTS__.push(rec);const next=Object.assign({},opts||{});const ok=next.success,fail=next.fail,done=next.complete;next.success=function(res){rec.tempFiles=res&&res.tempFiles;rec.type=res&&res.type;rec.finishedAt=new Date().toISOString();if(typeof ok==='function')return ok.apply(this,arguments)};next.fail=function(err){rec.error=String(err&&err.errMsg||err);rec.finishedAt=new Date().toISOString();if(typeof fail==='function')return fail.apply(this,arguments)};next.complete=function(res){rec.completed=true;if(typeof done==='function')return done.apply(this,arguments)};return raw.call(this,next)};hooks.chooseMedia=true}
g.__MCP_UPLOAD_HOOKED__=true;return {hooked:Object.keys(hooks).length>0,reused:false,hooks,count:g.__MCP_UPLOAD_REQUESTS__.length};})()
"""
        return await self.runtime_eval(script, context_id=self.selected_appservice_context_id)

    async def install_early_hooks(self) -> JsonDict:
        """Phase 0 一次性安装最早期 Hook，必须早于任何路由导航。"""
        result: JsonDict = {"ok": True, "phase": "early_hooks", "steps": {}}
        try:
            result["steps"]["select_appservice_context"] = await self.select_appservice_context()
        except Exception as exc:  # pragma: no cover - 防止局部能力缺失影响 page-frame hook
            result["steps"]["select_appservice_context"] = {"ok": False, "error": str(exc)}
        for name, func in [
            ("hook_wx_request", self.hook_wx_request),
            ("hook_upload_apis", self.hook_upload_apis),
            ("hook_fetch_and_xhr", self.hook_fetch_and_xhr),
        ]:
            try:
                result["steps"][name] = await func()
            except Exception as exc:  # pragma: no cover - Runtime 现场异常需返回给 Agent
                result["steps"][name] = {"ok": False, "error": str(exc)}
        result["ok"] = any(bool(step.get("ok")) for step in result["steps"].values() if isinstance(step, dict))
        return result

    async def rehook_after_route_navigation(self) -> JsonDict:
        """路由跳转后重新选择 appservice context，并重注入会随 context 失效的 Hook。"""
        output: JsonDict = {"ok": True, "hooks": {}}
        selected = await self.select_appservice_context()
        output["select_appservice_context"] = selected
        output["selectedContextId"] = selected.get("selectedContextId")
        if not selected.get("ok"):
            output["ok"] = False
            return output
        output["hooks"]["wx"] = await self.hook_wx_request()
        output["hooks"]["upload"] = await self.hook_upload_apis()
        output["ok"] = any(bool(hook.get("ok")) for hook in output["hooks"].values() if isinstance(hook, dict))
        return output

    async def hook_fetch_and_xhr(self) -> JsonDict:
        """注入非破坏性 fetch/XHR Hook，记录请求、响应和调用栈。"""
        script = r"""
(()=>{const g=globalThis;if(g.__MCP_FETCH_XHR_HOOKED__)return {hooked:true,reused:true,count:(g.__MCP_FETCH_XHR_REQUESTS__||[]).length};g.__MCP_FETCH_XHR_REQUESTS__=[];
if(typeof fetch==='function'){const rawFetch=fetch;g.fetch=async function(input,init){const id='fetch-'+Date.now()+'-'+Math.random().toString(16).slice(2);const url=typeof input==='string'?input:(input&&input.url)||'';const rec={id,source:'fetch',url,method:(init&&init.method||'GET').toUpperCase(),requestHeaders:init&&init.headers||{},requestBodyPreview:init&&init.body,callStack:(new Error()).stack,timestamp:new Date().toISOString()};g.__MCP_FETCH_XHR_REQUESTS__.push(rec);try{const resp=await rawFetch.apply(this,arguments);rec.statusCode=resp.status;rec.responseHeaders=Object.fromEntries(resp.headers.entries());const clone=resp.clone();clone.text().then(t=>{rec.responseBodyPreview=t.slice(0,2000);rec.finishedAt=new Date().toISOString();}).catch(e=>{rec.error=String(e)});return resp}catch(e){rec.error=String(e);rec.finishedAt=new Date().toISOString();throw e}}}
if(typeof XMLHttpRequest!=='undefined'){const open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send,set=XMLHttpRequest.prototype.setRequestHeader;XMLHttpRequest.prototype.open=function(method,url){this.__mcp={id:'xhr-'+Date.now()+'-'+Math.random().toString(16).slice(2),source:'xhr',method:String(method||'GET').toUpperCase(),url:String(url||''),requestHeaders:{},callStack:(new Error()).stack,timestamp:new Date().toISOString()};return open.apply(this,arguments)};XMLHttpRequest.prototype.setRequestHeader=function(k,v){if(this.__mcp)this.__mcp.requestHeaders[k]=v;return set.apply(this,arguments)};XMLHttpRequest.prototype.send=function(body){const rec=this.__mcp||{id:'xhr-'+Date.now(),source:'xhr'};rec.requestBodyPreview=body;g.__MCP_FETCH_XHR_REQUESTS__.push(rec);this.addEventListener('loadend',function(){rec.statusCode=this.status;rec.responseBodyPreview=String(this.responseText||'').slice(0,2000);rec.finishedAt=new Date().toISOString();});return send.apply(this,arguments)}}
g.__MCP_FETCH_XHR_HOOKED__=true;return {hooked:true};})()
"""
        return await self.runtime_eval(script)

    async def fetch_from_page(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Any = None,
        body: Any = None,
        await_promise: bool = True,
    ) -> JsonDict:
        """在 page-frame 上下文使用 fetch 发送请求，绕过 wx.request 合法域名白名单限制。"""
        target = str(url or "").strip()
        if not target:
            return {"ok": False, "error": "url 不能为空"}
        method_name = str(method or "GET").upper()
        header_obj = headers if isinstance(headers, dict) else {}
        init: JsonDict = {"method": method_name, "headers": header_obj}
        if body is not None:
            init["body"] = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        expr = f"""
(async()=>{{
  const url={json.dumps(target, ensure_ascii=False)};
  const init={json.dumps(init, ensure_ascii=False)};
  try {{
    const resp=await fetch(url, init);
    const text=await resp.clone().text();
    let jsonBody=null;
    try {{ jsonBody=JSON.parse(text); }} catch(_e) {{}}
    return {{ok:true,url,method:init.method||'GET',status:resp.status,statusText:resp.statusText,headers:Object.fromEntries(resp.headers.entries()),text:text.slice(0,10000),json:jsonBody}};
  }} catch(e) {{
    return {{ok:false,url,method:init.method||'GET',error:String(e&&e.message||e)}};
  }}
}})()
"""
        result = await self.runtime_eval(expr, await_promise=await_promise, context_id=None)
        value = result.get("value")
        if isinstance(value, dict):
            return {"ok": bool(result.get("ok")) and bool(value.get("ok")), "url": target, "method": method_name, "result": value}
        return {"ok": bool(result.get("ok")), "url": target, "method": method_name, "result": value, "raw": result}

    async def upload_formdata_from_page(
        self,
        url: str,
        *,
        headers: Any = None,
        fields: Any = None,
        files: Any = None,
        method: str = "POST",
        await_promise: bool = True,
    ) -> JsonDict:
        """在 page-frame 上下文构建 FormData 并发送 multipart 上传，避免退回 appservice wx.uploadFile。"""
        target = str(url or "").strip()
        if not target:
            return {"ok": False, "error": "url 不能为空"}
        method_name = str(method or "POST").upper()
        header_obj = headers if isinstance(headers, dict) else {}
        field_obj = fields if isinstance(fields, dict) else {}
        file_items = files if isinstance(files, list) else []
        normalized_files: list[JsonDict] = []
        for index, item in enumerate(file_items):
            if not isinstance(item, dict):
                continue
            normalized_files.append(
                {
                    "fieldName": str(item.get("fieldName") or item.get("name") or "file"),
                    "filename": str(item.get("filename") or item.get("fileName") or f"upload-{index + 1}.bin"),
                    "mimeType": str(item.get("mimeType") or item.get("contentType") or "application/octet-stream"),
                    "content": item.get("content") if isinstance(item.get("content"), str) else json.dumps(item.get("content"), ensure_ascii=False, default=str),
                    "encoding": str(item.get("encoding") or "utf-8").lower(),
                }
            )
        expr = f"""
(async()=>{{
  const url={json.dumps(target, ensure_ascii=False)};
  const method={json.dumps(method_name, ensure_ascii=False)};
  const headers={json.dumps(header_obj, ensure_ascii=False)};
  const fields={json.dumps(field_obj, ensure_ascii=False)};
  const files={json.dumps(normalized_files, ensure_ascii=False)};
  const fd=new FormData();
  const appendField=(key,value)=>{{
    if(Array.isArray(value)){{ for(const item of value) appendField(key,item); return; }}
    if(value===null||typeof value==='undefined'){{ fd.append(key,''); return; }}
    if(typeof value==='object'){{ fd.append(key,JSON.stringify(value)); return; }}
    fd.append(key,String(value));
  }};
  const decodeBytes=(spec)=>{{
    const text=String(spec&&spec.content||'');
    const encoding=String(spec&&spec.encoding||'utf-8').toLowerCase();
    if(encoding==='base64'||encoding==='base64url'){{
      const normalized=encoding==='base64url'?text.replace(/-/g,'+').replace(/_/g,'/'):text;
      const padded=normalized + '='.repeat((4 - normalized.length % 4) % 4);
      const binary=atob(padded);
      return Uint8Array.from(binary, ch => ch.charCodeAt(0));
    }}
    if(encoding==='hex'){{
      const clean=text.replace(/[^0-9a-f]/gi,'');
      const size=Math.floor(clean.length/2);
      const out=new Uint8Array(size);
      for(let i=0;i<size;i++) out[i]=parseInt(clean.slice(i*2,i*2+2),16);
      return out;
    }}
    return new TextEncoder().encode(text);
  }};
  Object.entries(fields||{{}}).forEach(([key,value])=>appendField(key,value));
  for(const spec of files||[]){{
    const blob=new Blob([decodeBytes(spec)],{{type:String(spec&&spec.mimeType||'application/octet-stream')}});
    fd.append(String(spec&&spec.fieldName||'file'), blob, String(spec&&spec.filename||'upload.bin'));
  }}
  try {{
    const resp=await fetch(url, {{method, headers, body:fd}});
    const text=await resp.clone().text();
    let jsonBody=null;
    try {{ jsonBody=JSON.parse(text); }} catch(_e) {{}}
    return {{
      ok:true,
      url,
      method,
      status:resp.status,
      statusText:resp.statusText,
      headers:Object.fromEntries(resp.headers.entries()),
      text:text.slice(0,10000),
      json:jsonBody,
      fieldsCount:Object.keys(fields||{{}}).length,
      filesCount:(files||[]).length
    }};
  }} catch(e) {{
    return {{
      ok:false,
      url,
      method,
      error:String(e&&e.message||e),
      fieldsCount:Object.keys(fields||{{}}).length,
      filesCount:(files||[]).length
    }};
  }}
}})()
"""
        result = await self.runtime_eval(expr, await_promise=await_promise, context_id=None)
        value = result.get("value")
        if isinstance(value, dict):
            return {
                "ok": bool(result.get("ok")) and bool(value.get("ok")),
                "url": target,
                "method": method_name,
                "result": value,
                "fields": field_obj,
                "files": [{"fieldName": item["fieldName"], "filename": item["filename"], "mimeType": item["mimeType"], "encoding": item["encoding"]} for item in normalized_files],
            }
        return {
            "ok": bool(result.get("ok")),
            "url": target,
            "method": method_name,
            "result": value,
            "fields": field_obj,
            "files": [{"fieldName": item["fieldName"], "filename": item["filename"], "mimeType": item["mimeType"], "encoding": item["encoding"]} for item in normalized_files],
            "raw": result,
        }

    async def get_hooked_requests(self) -> list[JsonDict]:
        """从运行时读取 Hook 捕获的 wx/fetch/xhr/upload/choose 记录。"""
        records: list[JsonDict] = []
        context_ids = [self.selected_appservice_context_id, None] if self.selected_appservice_context_id is not None else [None]
        seen: set[str] = set()
        for context_id in context_ids:
            with IgnoreOptionalCdpError():
                result = await self.runtime_eval("(()=>[...(globalThis.__MCP_WX_REQUESTS__||[]),...(globalThis.__MCP_FETCH_XHR_REQUESTS__||[]),...(globalThis.__MCP_UPLOAD_REQUESTS__||[])])()", context_id=context_id)
                value = result.get("value")
                if isinstance(value, list):
                    for item in value:
                        if not isinstance(item, dict):
                            continue
                        rid = str(item.get("id") or json.dumps(item, ensure_ascii=False, default=str))
                        if rid in seen:
                            continue
                        seen.add(rid)
                        records.append(item)
        return records

    async def get_all_requests(self, *, limit: int = 200, keyword: Any = None, domain: Any = None, path_prefix: Any = None) -> JsonDict:
        """合并 CDP 缓存和 Hook 记录，返回统一请求列表。"""
        hooked = await self.get_hooked_requests()
        merged: dict[str, JsonDict] = {key: self.normalize_request(value) for key, value in self.requests.items()}
        for item in hooked:
            rid = str(item.get("id") or f"hook-{len(merged)}")
            merged[rid] = self.normalize_request({**item, "requestId": rid})
        items = list(merged.values())
        kw = str(keyword or "").lower()
        dm = str(domain or "").lower()
        pp = str(path_prefix or "")
        if kw:
            items = [r for r in items if kw in json.dumps(r, ensure_ascii=False).lower()]
        if dm:
            items = [r for r in items if dm in str(urlparse(str(r.get("url") or "")).netloc).lower()]
        if pp:
            items = [r for r in items if str(urlparse(str(r.get("url") or "")).path).startswith(pp)]
        items.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        return {"ok": True, "total": len(items), "requests": items[: max(1, int(limit))]}

    async def get_request_detail(self, request_id: str) -> JsonDict:
        """读取指定请求详情，必要时尝试通过 CDP 获取响应体。"""
        all_requests = await self.get_all_requests(limit=2000)
        for req in all_requests.get("requests", []):
            if str(req.get("id")) == request_id or str(req.get("requestId")) == request_id:
                detail = dict(req)
                if req.get("source") == "cdp":
                    with IgnoreOptionalCdpError():
                        body = await self.cdp.send("Network.getResponseBody", {"requestId": request_id}, timeout_ms=5000)
                        detail["responseBodyRaw"] = body.get("result", {})
                return {"ok": True, "request": detail}
        return {"ok": False, "error": f"未找到请求：{request_id}"}

    def normalize_request(self, raw: JsonDict) -> JsonDict:
        """把 CDP 或 Hook 原始记录归一为统一结构。"""
        url = str(raw.get("url") or raw.get("request", {}).get("url") or "")
        parsed = urlparse(url)
        body = raw.get("requestBodyPreview", raw.get("postData", raw.get("request", {}).get("postData")))
        headers = raw.get("requestHeaders", raw.get("request", {}).get("headers", {})) or {}
        response_headers = raw.get("responseHeaders", raw.get("response", {}).get("headers", {})) or {}
        return {"id": str(raw.get("requestId") or raw.get("id") or ""), "requestId": str(raw.get("requestId") or raw.get("id") or ""), "source": str(raw.get("source") or "cdp"), "method": str(raw.get("method") or raw.get("request", {}).get("method") or "GET"), "url": url, "path": parsed.path, "query": parse_url_query(url), "requestHeaders": headers, "requestBodyPreview": safe_json_loads(body), "statusCode": raw.get("statusCode", raw.get("response", {}).get("status")), "responseHeaders": response_headers, "responseBodyPreview": safe_json_loads(raw.get("responseBodyPreview", "")), "timestamp": raw.get("timestamp") or now_iso(), "callStack": raw.get("callStack") or raw.get("initiator"), "raw": raw}

    def _on_network_event(self, event: JsonDict) -> None:
        """处理 CDP Network 事件并更新请求缓存。"""
        method = str(event.get("method") or "")
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        request_id = str(params.get("requestId") or "")
        if method.startswith("Network.webSocket"):
            self.websocket_events.append(event)
            return
        if not request_id:
            return
        record = self.requests.setdefault(request_id, {"requestId": request_id, "source": "cdp"})
        if request_id not in self.request_order:
            self.request_order.append(request_id)
        if method == "Network.requestWillBeSent":
            req = params.get("request") or {}
            record.update({"url": req.get("url"), "method": req.get("method"), "request": req, "initiator": params.get("initiator"), "timestamp": params.get("timestamp") or now_iso()})
        elif method == "Network.requestWillBeSentExtraInfo":
            record["requestHeaders"] = params.get("headers") or record.get("requestHeaders", {})
        elif method == "Network.responseReceived":
            record["response"] = params.get("response") or {}
            record["statusCode"] = record["response"].get("status")
        elif method == "Network.responseReceivedExtraInfo":
            record["responseHeaders"] = params.get("headers") or record.get("responseHeaders", {})
        elif method == "Network.loadingFinished":
            record["loadingFinished"] = True
        elif method == "Network.loadingFailed":
            record["loadingFailed"] = params.get("errorText") or True

    def _on_script_parsed(self, event: JsonDict) -> None:
        """缓存 Debugger.scriptParsed 事件中的脚本元信息。"""
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        script_id = str(params.get("scriptId") or "")
        if script_id:
            self.scripts[script_id] = dict(params)

    def _on_execution_context_created(self, event: JsonDict) -> None:
        """缓存 Runtime execution context 信息。"""
        params = event.get("params") if isinstance(event.get("params"), dict) else {}
        ctx = params.get("context") if isinstance(params.get("context"), dict) else {}
        context_id = ctx.get("id")
        if isinstance(context_id, int):
            self.contexts[context_id] = dict(ctx)

    def _on_console_event(self, event: JsonDict) -> None:
        """缓存控制台、异常和暂停事件。"""
        self.console_events.append(event)

    async def dump_runtime_snapshot(self) -> JsonDict:
        """采集当前页面 URL、storage、路由和可见文本摘要。"""
        expr = "(()=>({href:location.href,title:document.title,route:globalThis.__wxRoute||'',storage:Object.keys(localStorage||{}).slice(0,50).reduce((a,k)=>(a[k]=String(localStorage.getItem(k)).slice(0,200),a),{}),visibleText:(document.body&&document.body.innerText||'').slice(0,1500),wxConfig:typeof __wxConfig!=='undefined'?{appId:__wxConfig.appId,pages:(__wxConfig.pages||[]).slice(0,20)}:null}))()"
        result = await self.runtime_eval(expr)
        return {"ok": bool(result.get("ok")), "snapshot": result.get("value"), "contexts": list(self.contexts.values()), "status": await self.status()}

    async def scan_sensitive_storage(self) -> JsonDict:
        """扫描 wx/local/session Storage 中的凭据、密码、内部配置和令牌线索。"""
        expr = r"""
(()=>{const out={wxStorage:{},localStorage:{},sessionStorage:{},errors:[]};
try{if(typeof wx!=='undefined'&&wx.getStorageInfoSync&&wx.getStorageSync){const info=wx.getStorageInfoSync()||{};(info.keys||[]).forEach(k=>{try{out.wxStorage[k]=wx.getStorageSync(k)}catch(e){out.errors.push('wx:'+k+':'+String(e))}})}}catch(e){out.errors.push('wxStorage:'+String(e))}
try{if(typeof localStorage!=='undefined'){for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);out.localStorage[k]=localStorage.getItem(k)}}}catch(e){out.errors.push('localStorage:'+String(e))}
try{if(typeof sessionStorage!=='undefined'){for(let i=0;i<sessionStorage.length;i++){const k=sessionStorage.key(i);out.sessionStorage[k]=sessionStorage.getItem(k)}}}catch(e){out.errors.push('sessionStorage:'+String(e))}
return out;})()
"""
        contexts = [("appservice", self.selected_appservice_context_id)] if self.selected_appservice_context_id is not None else []
        contexts.append(("page_frame", None))
        raw_results: list[JsonDict] = []
        value: JsonDict = {"wxStorage": {}, "localStorage": {}, "sessionStorage": {}, "errors": []}
        for context_name, context_id in contexts:
            runtime = await self.runtime_eval(expr, context_id=context_id)
            raw_results.append({"context": context_name, "contextId": context_id, "result": runtime})
            current = runtime.get("value")
            if not isinstance(current, dict):
                continue
            for source_name in ["wxStorage", "localStorage", "sessionStorage"]:
                source_value = current.get(source_name) or {}
                if isinstance(source_value, dict):
                    value[source_name].update(source_value)
            if isinstance(current.get("errors"), list):
                value["errors"].extend(current.get("errors") or [])
        findings: list[JsonDict] = []
        for source in ["wxStorage", "localStorage", "sessionStorage"]:
            data = value.get(source) or {}
            if not isinstance(data, dict):
                continue
            findings.extend(self.classify_sensitive_storage_source(source, data))
        return {
            "ok": any(bool(item.get("result", {}).get("ok")) for item in raw_results),
            "findings": findings,
            "count": len(findings),
            "sources": {name: len(value.get(name) or {}) for name in ["wxStorage", "localStorage", "sessionStorage"]},
            "errors": value.get("errors") or [],
            "raw": raw_results,
        }

    def classify_sensitive_storage_source(self, source: str, data: dict[str, Any]) -> list[JsonDict]:
        """对单个 storage 源执行敏感 key/value 分类。"""
        findings: list[JsonDict] = []
        for key, value in data.items():
            text = f"{key}\n{compact_text(value, 1000)}"
            for category, pattern in SENSITIVE_STORAGE_RULES:
                matched = sorted({m.group(0) for m in pattern.finditer(text)})[:8]
                if not matched:
                    continue
                findings.append(
                    {
                        "source": source,
                        "key": str(key),
                        "category": category,
                        "reason": matched,
                        "valuePreview": self.mask_sensitive_value(value),
                    }
                )
        return findings

    @staticmethod
    def mask_sensitive_value(value: Any) -> str:
        """默认脱敏 storage 值，仅保留少量前后缀便于复核。"""
        text = compact_text(value, 300)
        if not text:
            return ""
        if len(text) <= 6:
            return "***"
        return f"{text[:4]}***{text[-2:]}"

    async def inspect_upload_surface(self) -> JsonDict:
        """检查当前路由 DOM、页面方法和 data 中的上传/选图/头像相关指示。"""
        dom_expr = r"""
(()=>{const re=/upload|chooseImage|chooseMedia|avatar|file|media|photo|image|上传|头像|选择图片|图片|文件/i;
const nodes=Array.from(document.querySelectorAll('button,a,input,textarea,label,[role=button],image,img,view,text')).slice(0,800);
return nodes.map((e,i)=>{const attrs={id:e.id||'',className:String(e.className||''),type:e.getAttribute&&e.getAttribute('type')||'',name:e.getAttribute&&e.getAttribute('name')||'',placeholder:e.getAttribute&&e.getAttribute('placeholder')||'',src:e.getAttribute&&e.getAttribute('src')||'',ariaLabel:e.getAttribute&&e.getAttribute('aria-label')||''};const text=String(e.innerText||e.textContent||e.value||'').slice(0,160);const joined=JSON.stringify(attrs)+' '+text;if(!re.test(joined))return null;return {type:'element',index:i,tag:e.tagName,text,attrs,selector:e.id?'#'+e.id:(e.className?e.tagName.toLowerCase()+'.'+String(e.className).split(/\s+/).filter(Boolean).join('.'):e.tagName.toLowerCase())}}).filter(Boolean).slice(0,100);})()
"""
        app_expr = r"""
(()=>{const re=/upload|chooseImage|chooseMedia|avatar|file|media|photo|image|上传|头像|选择图片|图片|文件/i;
const pages=typeof getCurrentPages==='function'?getCurrentPages():[];const page=pages[pages.length-1]||{};const methods=[];Object.keys(page).forEach(k=>{try{if(typeof page[k]==='function'&&re.test(k))methods.push(k)}catch(e){}});
const dataHits=[];const seen=new Set();function walk(obj,path,depth){if(!obj||depth>3||seen.has(obj))return;if(typeof obj==='object')seen.add(obj);Object.keys(obj||{}).slice(0,300).forEach(k=>{let v;try{v=obj[k]}catch(e){return}const p=path?path+'.'+k:k;const s=String(k)+' '+(typeof v==='string'?v:'');if(re.test(s))dataHits.push({path:p,value:typeof v==='string'?v.slice(0,160):Object.prototype.toString.call(v)});if(v&&typeof v==='object')walk(v,p,depth+1)})}walk(page.data||{},'',0);
return {route:page.route||globalThis.__wxRoute||'',methods:methods.slice(0,100),dataKeys:dataHits.slice(0,100),hasWxUpload:!!(globalThis.wx&&wx.uploadFile),hasChooseImage:!!(globalThis.wx&&wx.chooseImage),hasChooseMedia:!!(globalThis.wx&&wx.chooseMedia)};})()
"""
        dom = await self.runtime_eval(dom_expr)
        app = await self.runtime_eval(app_expr, context_id=self.selected_appservice_context_id)
        indicators: list[JsonDict] = []
        dom_value = dom.get("value") if isinstance(dom, dict) else None
        app_value = app.get("value") if isinstance(app, dict) else None
        if isinstance(dom_value, list):
            indicators.extend([item for item in dom_value if isinstance(item, dict)])
        if isinstance(app_value, dict):
            indicators.extend({"type": "method", "name": name} for name in app_value.get("methods") or [])
            indicators.extend({"type": "data", **item} for item in app_value.get("dataKeys") or [] if isinstance(item, dict))
        return {"ok": bool(dom.get("ok")) or bool(app.get("ok")), "indicators": indicators, "dom": dom_value, "appservice": app_value, "raw": {"dom": dom, "appservice": app}}

    async def list_scripts(self, url_filter: str = "") -> JsonDict:
        """列出已加载脚本，支持 URL 过滤。"""
        await self.ensure_debugger_enabled()
        scripts = list(self.scripts.values())
        if url_filter:
            scripts = [s for s in scripts if url_filter in str(s.get("url") or "")]
        return {"ok": True, "count": len(scripts), "scripts": scripts}

    async def get_script_source(self, *, script_id: Any = None, url: Any = None, offset: Any = None, length: int = 2000, start_line: Any = None, end_line: Any = None) -> JsonDict:
        """读取脚本源码片段，支持 URL 或 scriptId。"""
        await self.ensure_debugger_enabled()
        sid = str(script_id or "")
        if not sid and url:
            for key, script in self.scripts.items():
                if str(url) in str(script.get("url") or ""):
                    sid = key
                    break
        if not sid:
            return {"ok": False, "error": "缺少 script_id 或无法从 url 匹配脚本"}
        response = await self.cdp.send("Debugger.getScriptSource", {"scriptId": sid}, timeout_ms=10000)
        source = response.get("result", {}).get("scriptSource", "")
        if start_line is not None or end_line is not None:
            lines = source.splitlines()
            start = max(0, int(start_line or 1) - 1)
            end = min(len(lines), int(end_line or len(lines)))
            snippet = "\n".join(f"{idx + 1}: {line}" for idx, line in enumerate(lines[start:end], start))
        else:
            start = max(0, int(offset or 0))
            snippet = source[start : start + max(1, int(length))]
        return {"ok": True, "scriptId": sid, "url": self.scripts.get(sid, {}).get("url"), "length": len(source), "source": snippet}

    async def save_script_source(self, file_path: str, *, script_id: Any = None, url: Any = None) -> JsonDict:
        """把脚本源码保存到用户指定文件，统一使用 utf-8。"""
        if not file_path:
            return {"ok": False, "error": "file_path 不能为空"}
        result = await self.get_script_source(script_id=script_id, url=url, offset=0, length=10_000_000)
        if not result.get("ok"):
            return result
        path = Path(file_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_text, str(result.get("source") or ""), encoding="utf-8")
        return {"ok": True, "path": str(path), "bytes": path.stat().st_size}

    async def search_in_sources(self, query: str, *, case_sensitive: bool = False, is_regex: bool = False, max_results: int = 50, url_filter: Any = None) -> JsonDict:
        """在已加载脚本中搜索字符串或正则。"""
        await self.ensure_debugger_enabled()
        matches: list[JsonDict] = []
        flags = 0 if case_sensitive else re.I
        pattern = re.compile(query, flags) if is_regex else None
        for sid, script in list(self.scripts.items()):
            if url_filter and str(url_filter) not in str(script.get("url") or ""):
                continue
            source_result = await self.get_script_source(script_id=sid, offset=0, length=2_000_000)
            source = str(source_result.get("source") or "")
            for line_no, line in enumerate(source.splitlines(), 1):
                hit = bool(pattern.search(line)) if pattern else ((query in line) if case_sensitive else (query.lower() in line.lower()))
                if hit:
                    matches.append({"scriptId": sid, "url": script.get("url"), "line": line_no, "text": compact_text(line, 300)})
                    if len(matches) >= max_results:
                        return {"ok": True, "matches": matches, "truncated": True}
        return {"ok": True, "matches": matches, "truncated": False}

    async def break_on_xhr(self, url: str) -> JsonDict:
        """按 URL 子串设置 XHR/fetch 断点。"""
        await self.ensure_debugger_enabled()
        result = await self.cdp.send("DOMDebugger.setXHRBreakpoint", {"url": url}, timeout_ms=5000)
        return {"ok": True, "url": url, "raw": result}

    async def set_breakpoint_on_text(self, text: str) -> JsonDict:
        """通过源码文本搜索后在首个命中行设置断点。"""
        found = await self.search_in_sources(text, max_results=1)
        matches = found.get("matches") or []
        if not matches:
            return {"ok": False, "error": "未找到文本，未设置断点"}
        first = matches[0]
        result = await self.cdp.send("Debugger.setBreakpointByUrl", {"url": first.get("url"), "lineNumber": max(0, int(first.get("line") or 1) - 1)}, timeout_ms=5000)
        return {"ok": True, "match": first, "raw": result}

    async def get_paused_info(self) -> JsonDict:
        """返回最近一次暂停事件和控制台事件。"""
        paused = [e for e in self.console_events if e.get("method") == "Debugger.paused"]
        return {"ok": True, "paused": paused[-1] if paused else None, "recentConsole": list(self.console_events)[-20:]}

    async def resume_execution(self) -> JsonDict:
        """恢复 JavaScript 执行。"""
        result = await self.cdp.send("Debugger.resume", timeout_ms=5000)
        return {"ok": True, "raw": result}

    async def step(self, kind: str) -> JsonDict:
        """执行 Debugger 单步控制。"""
        mapping = {"over": "Debugger.stepOver", "into": "Debugger.stepInto", "out": "Debugger.stepOut"}
        method = mapping.get(kind, "Debugger.stepOver")
        result = await self.cdp.send(method, timeout_ms=5000)
        return {"ok": True, "method": method, "raw": result}

    async def get_websocket_messages(self) -> JsonDict:
        """返回已缓存 WebSocket 事件。"""
        return {"ok": True, "events": list(self.websocket_events)}

    async def search_runtime_keywords(self, keywords: list[str]) -> JsonDict:
        """在运行时对象、storage、页面文本和请求缓存中搜索关键词。"""
        expr = "(()=>({keys:Object.keys(globalThis).slice(0,2000),storage:Object.keys(localStorage||{}).reduce((a,k)=>(a[k]=localStorage.getItem(k),a),{}),text:(document.body&&document.body.innerText||'').slice(0,5000)}))()"
        runtime = await self.runtime_eval(expr)
        haystack = json.dumps(runtime.get("value"), ensure_ascii=False) + json.dumps((await self.get_all_requests(limit=500)).get("requests", []), ensure_ascii=False)
        hits = {kw: [m.start() for m in re.finditer(re.escape(str(kw)), haystack, re.I)][:20] for kw in keywords}
        return {"ok": True, "hits": hits}

    async def inspect_wx_config(self) -> JsonDict:
        """读取小程序 __wxConfig / accountInfo 摘要。"""
        expr = "(()=>({wxConfig:typeof __wxConfig!=='undefined'?__wxConfig:null,account:typeof wx!=='undefined'&&wx.getAccountInfoSync?wx.getAccountInfoSync():null,route:globalThis.__wxRoute||''}))()"
        return await self.runtime_eval(expr, context_id=self.selected_appservice_context_id)

    async def trace_request_callstack(self, request_id: str) -> JsonDict:
        """返回指定请求的调用栈或 initiator 信息。"""
        detail = await self.get_request_detail(request_id)
        req = detail.get("request") if detail.get("ok") else {}
        return {"ok": bool(detail.get("ok")), "requestId": request_id, "callStack": req.get("callStack") if isinstance(req, dict) else None}

    async def inspect_vuex_store(self) -> JsonDict:
        """查找 Vuex-like store，并保存只读摘要。"""
        expr = "(()=>{const c=[globalThis.$store,globalThis.store,globalThis.__store__].filter(Boolean);return c.map((s,i)=>({index:i,keys:Object.keys(s),state:s.state,mutations:Object.keys(s._mutations||{}),actions:Object.keys(s._actions||{})}));})()"
        return await self.runtime_eval(expr, context_id=self.selected_appservice_context_id)

    async def patch_vuex_state(self, path: str, value: Any, dry_run: bool, require_confirm: bool) -> JsonDict:
        """按安全开关修改 Vuex state；默认 dryRun 不修改。"""
        if dry_run or not require_confirm:
            return {"ok": True, "dryRun": True, "message": "未修改 state；需要 dryRun=false 且 requireConfirm=true", "path": path, "value": value}
        expr = f"(()=>{{const s=(globalThis.$store||globalThis.store||{{}}).state;if(!s)return 'no state';const parts={json.dumps(path.split('.'), ensure_ascii=False)};let o=s;for(let i=0;i<parts.length-1;i++)o=o[parts[i]];o[parts.at(-1)]={json.dumps(value, ensure_ascii=False)};return true;}})()"
        return await self.runtime_eval(expr, context_id=self.selected_appservice_context_id)

    async def restore_vuex_state(self, dry_run: bool, require_confirm: bool) -> JsonDict:
        """恢复 Vuex state 快照占位；默认不修改。"""
        return {"ok": True, "dryRun": dry_run or not require_confirm, "message": "当前版本仅生成恢复提示，请使用 inspect_vuex_store 的快照人工复核"}

    async def list_interactive_elements(self) -> JsonDict:
        """列出当前页面可交互元素摘要。"""
        expr = "(()=>Array.from(document.querySelectorAll('button,a,input,textarea,[role=button]')).slice(0,200).map((e,i)=>({i,tag:e.tagName,text:(e.innerText||e.value||e.ariaLabel||'').slice(0,120),selector:e.id?'#'+e.id:e.className?e.tagName.toLowerCase()+'.'+String(e.className).split(/\\s+/).join('.') : e.tagName.toLowerCase()})))()"
        return await self.runtime_eval(expr)

    async def safe_click_and_observe(self, selector: str, require_confirm: bool) -> JsonDict:
        """安全点击元素并观察请求变化；高风险文本需要确认。"""
        if not selector:
            return {"ok": False, "error": "selector 不能为空"}
        before = len((await self.get_all_requests(limit=2000)).get("requests", []))
        expr = f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return {{clicked:false,error:'not found'}};const t=e.innerText||e.value||'';if(/支付|提交订单|删除|注销|退款|提现|确认支付/.test(t)&&{str(bool(require_confirm)).lower()}!==true)return {{clicked:false,blocked:true,text:t}};e.click();return {{clicked:true,text:t}};}})()"
        clicked = await self.runtime_eval(expr)
        await asyncio.sleep(0.3)
        after = await self.get_all_requests(limit=2000)
        return {"ok": True, "click": clicked.get("value"), "newRequestCount": len(after.get("requests", [])) - before}

    async def input_text_and_observe(self, selector: str, text: str) -> JsonDict:
        """向输入框写入文本并触发 input/change 事件。"""
        expr = f"(()=>{{const e=document.querySelector({json.dumps(selector)});if(!e)return {{ok:false,error:'not found'}};e.value={json.dumps(text)};e.dispatchEvent(new Event('input',{{bubbles:true}}));e.dispatchEvent(new Event('change',{{bubbles:true}}));return {{ok:true}};}})()"
        return await self.runtime_eval(expr)

    def build_api_inventory(self, requests: list[JsonDict]) -> JsonDict:
        """按 method+path 聚合接口清单。"""
        groups: dict[str, JsonDict] = {}
        for req in requests:
            key = f"{req.get('method')} {req.get('path')}"
            group = groups.setdefault(key, {"key": key, "method": req.get("method"), "path": req.get("path"), "count": 0, "statusCodes": set(), "examples": []})
            group["count"] += 1
            if req.get("statusCode") is not None:
                group["statusCodes"].add(req.get("statusCode"))
            if len(group["examples"]) < 3:
                group["examples"].append(req.get("id"))
        return {"ok": True, "apis": [{**g, "statusCodes": sorted(g["statusCodes"])} for g in groups.values()]}

    def analyze_auth_surface(self, requests: list[JsonDict]) -> JsonDict:
        """分析请求中认证字段位置和缺失认证线索。"""
        findings = []
        for req in requests:
            joined = json.dumps({"headers": req.get("requestHeaders"), "query": req.get("query"), "body": req.get("requestBodyPreview")}, ensure_ascii=False)
            has_auth = bool(AUTH_FIELD_RE.search(joined))
            if not has_auth and req.get("statusCode") in {200, 201, 204, None}:
                findings.append({"type": "missing_auth_candidate", "requestId": req.get("id"), "url": req.get("url")})
        return {"ok": True, "findings": findings, "note": "仅为线索，需在授权环境使用无/伪造凭据对比验证"}

    def find_idor_candidates(self, requests: list[JsonDict]) -> JsonDict:
        """识别路径、查询和 body 中含 ID 字段的越权候选接口。"""
        candidates = []
        for req in requests:
            names = list((req.get("query") or {}).keys())
            body = req.get("requestBodyPreview")
            if isinstance(body, dict):
                names.extend(body.keys())
            path_ids = re.findall(r"/(\d+|undefined)(?=/|$)", str(req.get("path") or ""))
            if path_ids or any(ID_FIELD_RE.search(str(name)) for name in names):
                candidates.append({"requestId": req.get("id"), "method": req.get("method"), "url": req.get("url"), "pathIds": path_ids, "fields": names})
        return {"ok": True, "candidates": candidates}

    def find_sensitive_data_exposure(self, requests: list[JsonDict]) -> JsonDict:
        """在响应预览中查找敏感字段名并默认脱敏。"""
        findings = []
        for req in requests:
            text = json.dumps(req.get("responseBodyPreview"), ensure_ascii=False)
            if SENSITIVE_FIELD_RE.search(text):
                findings.append({"requestId": req.get("id"), "url": req.get("url"), "matched": sorted(set(SENSITIVE_FIELD_RE.findall(text)))[:20], "preview": compact_text(text, 500)})
        return {"ok": True, "findings": findings}

    def find_by_regex(self, requests: list[JsonDict], pattern: re.Pattern, finding_type: str) -> JsonDict:
        """按正则在 URL、Header、Body 中筛选风险面。"""
        hits = []
        for req in requests:
            text = json.dumps(req, ensure_ascii=False)
            if pattern.search(text):
                hits.append({"type": finding_type, "requestId": req.get("id"), "method": req.get("method"), "url": req.get("url"), "statusCode": req.get("statusCode")})
        return {"ok": True, "findings": hits}

    async def build_replay_plan(self, request_id: str) -> JsonDict:
        """根据请求生成 Burp/手工重放计划，不自动发送请求。"""
        detail = await self.get_request_detail(request_id)
        if not detail.get("ok"):
            return detail
        req = detail["request"]
        return {"ok": True, "requestId": request_id, "manualOnly": True, "method": req.get("method"), "url": req.get("url"), "headers": req.get("requestHeaders"), "body": req.get("requestBodyPreview"), "checks": ["删除/替换 Authorization 后对比响应", "修改 ID 字段为本人相邻资源 ID", "timestamp/nonce/sign 保持原值测试重放窗口", "写操作必须人工确认且只在授权测试数据上执行"]}

    async def compare_two_requests(self, a: str, b: str) -> JsonDict:
        """对比两个请求的 URL、认证字段、Body 和状态差异。"""
        da = await self.get_request_detail(a)
        db = await self.get_request_detail(b)
        if not da.get("ok") or not db.get("ok"):
            return {"ok": False, "a": da, "b": db}
        ra, rb = da["request"], db["request"]
        return {"ok": True, "diff": {"urlChanged": ra.get("url") != rb.get("url"), "methodChanged": ra.get("method") != rb.get("method"), "statusChanged": ra.get("statusCode") != rb.get("statusCode"), "queryA": ra.get("query"), "queryB": rb.get("query"), "authA": self.extract_auth_fields(ra), "authB": self.extract_auth_fields(rb)}}

    def extract_auth_fields(self, req: JsonDict) -> JsonDict:
        """提取请求中的认证相关字段。"""
        out: JsonDict = {}
        for source_name in ["requestHeaders", "query"]:
            data = req.get(source_name) or {}
            if isinstance(data, dict):
                out[source_name] = {k: "***" if len(str(v)) > 8 else v for k, v in data.items() if AUTH_FIELD_RE.search(str(k))}
        return out

    def passive_param_fuzz_suggestions(self, requests: list[JsonDict]) -> JsonDict:
        """基于已捕获参数生成被动 fuzz 建议，不发送请求。"""
        suggestions = []
        for req in requests:
            params = list((req.get("query") or {}).keys())
            body = req.get("requestBodyPreview")
            if isinstance(body, dict):
                params.extend(body.keys())
            interesting = [p for p in params if ID_FIELD_RE.search(str(p)) or AUTH_FIELD_RE.search(str(p))]
            if interesting:
                suggestions.append({"requestId": req.get("id"), "url": req.get("url"), "parameters": interesting, "tests": ["空值", "本人相邻 ID", "超长字符串", "类型切换 number/string"]})
        return {"ok": True, "suggestions": suggestions}

    def generate_security_notes(self, requests: list[JsonDict]) -> JsonDict:
        """生成 Markdown 报告素材。"""
        inventory = self.build_api_inventory(requests)
        sections = ["# 小程序安全评估笔记", "", f"生成时间：{now_iso()}", "", f"接口数量：{len(inventory.get('apis', []))}", "", "## 重点线索", "", "- 认证面：见 analyze_auth_surface", "- IDOR 候选：见 find_idor_candidates", "- 敏感信息：见 find_sensitive_data_exposure"]
        return {"ok": True, "markdown": "\n".join(sections)}

    def generate_api_table_markdown(self, requests: list[JsonDict]) -> str:
        """生成接口清单 Markdown 表格。"""
        inventory = self.build_api_inventory(requests).get("apis", [])
        lines = ["| Method | Path | Count | Status |", "|---|---|---:|---|"]
        for api in inventory:
            lines.append(f"| {api.get('method')} | `{api.get('path')}` | {api.get('count')} | {','.join(map(str, api.get('statusCodes', [])))} |")
        return "\n".join(lines)

    async def export_session(self, requests: list[JsonDict]) -> JsonDict:
        """导出当前 MCP 采集会话到 output/reports，文件写入放入线程执行。"""
        report_dir = Path("output") / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / f"mcp-session-{int(time.time())}.json"
        payload = {"createdAt": now_iso(), "status": await self.status(), "requests": requests, "scripts": list(self.scripts.values())}
        await asyncio.to_thread(path.write_text, json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"ok": True, "path": str(path), "requestCount": len(requests)}

    async def run_decrypt_pipeline(self, value: str, steps: list[Any]) -> JsonDict:
        """按步骤执行多层解码/解密流水线。"""
        current = value
        outputs = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "decode_payload")
            if action.startswith("decode"):
                result = decode_payload(current, str(step.get("encoding") or step.get("input_encoding") or "auto"))
                current = result.get("text") or result.get("hex_preview") or current
            elif action.startswith("decrypt"):
                result = decrypt_payload(current, algorithm=str(step.get("algorithm") or "aes"), key=str(step.get("key") or ""), mode=str(step.get("mode") or "cbc"), iv=str(step.get("iv") or ""), input_encoding=str(step.get("input_encoding") or "base64"), key_encoding=str(step.get("key_encoding") or "utf-8"))
                current = result.get("text") or current
            else:
                result = {"error": f"未知步骤：{action}"}
            outputs.append({"step": step, "result": result})
        return {"ok": True, "final": current, "steps": outputs}

    async def discover_runtime_crypto_functions(self) -> JsonDict:
        """枚举运行时中疑似加密/签名函数名。"""
        expr = "(()=>Object.keys(globalThis).filter(k=>/encrypt|decrypt|sign|crypto|md5|sha|aes|rsa|enc/i.test(k)).slice(0,200))()"
        return await self.runtime_eval(expr, context_id=self.selected_appservice_context_id)

    async def call_runtime_crypto_function(self, function_name: str, args: list[Any]) -> JsonDict:
        """调用指定运行时函数并返回结果。"""
        expr = f"(()=>{{const fn=globalThis[{json.dumps(function_name)}];if(typeof fn!=='function')return {{ok:false,error:'not function'}};return {{ok:true,value:fn.apply(null,{json.dumps(args, ensure_ascii=False)})}};}})()"
        return await self.runtime_eval(expr, context_id=self.selected_appservice_context_id)

    def match_reverse_cases(self, text: str) -> JsonDict:
        """把源码特征映射到当前项目 SKILL.md 的逆向场景。"""
        pattern = identify_crypto_pattern(text).get("patterns", {})
        cases = []
        if pattern.get("webpack"):
            cases.append("场景 7：Webpack 打包逆向")
        if pattern.get("jsvmp"):
            cases.append("场景 8：JSVMP 虚拟机保护")
        if pattern.get("aes") or pattern.get("rsa") or pattern.get("md5"):
            cases.append("场景 2/6/10：加密参数与动态密钥追踪")
        return {"ok": True, "cases": cases, "patterns": pattern}

    def detect_reverse_strategy(self, text: str) -> JsonDict:
        """根据代码保护特征给出逆向优先策略。"""
        matched = self.match_reverse_cases(text)
        patterns = matched.get("patterns", {})
        if patterns.get("jsvmp"):
            strategy = "优先 hook_wx_request 截取最终签名；若失败再做入口/出口断点追踪"
        elif patterns.get("webpack"):
            strategy = "先枚举 __webpack_require__.c 模块缓存，再按 encrypt/sign/request 关键词定位模块"
        else:
            strategy = "先 search_in_sources 搜索 encrypt/decrypt/sign，再用 break_on_xhr 获取调用栈"
        return {"ok": True, "strategy": strategy, "matched": matched}

    async def cdp_call(self, method: str, params: JsonDict | None = None, session_id: str | None = None) -> JsonDict:
        """调用任意 CDP 方法，支持 flatten sessionId。"""
        if not method:
            return {"ok": False, "error": "method 不能为空"}
        result = await self.cdp.send(method, params or {}, session_id=session_id, timeout_ms=15000)
        return {"ok": True, "method": method, "sessionId": session_id, "result": result}

    async def cdp_call_target(self, target_id: str, method: str, params: JsonDict | None = None) -> JsonDict:
        """attach 到指定 targetId 后在子 session 中调用 CDP 方法。"""
        if not target_id or not method:
            return {"ok": False, "error": "target_id 和 method 均不能为空"}
        attached = await self.cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True}, timeout_ms=10000)
        session_id = attached.get("result", {}).get("sessionId")
        if not session_id:
            return {"ok": False, "error": "attachToTarget 未返回 sessionId", "raw": attached}
        result = await self.cdp.send(method, params or {}, session_id=session_id, timeout_ms=15000)
        return {"ok": True, "targetId": target_id, "sessionId": session_id, "method": method, "result": result}

    async def get_recent_requests(self, limit: int = 50, *, domain: str | None = None, path_prefix: str | None = None, keyword: str | None = None, compact: bool = True) -> JsonDict:
        """返回最近 CDP/Hook 请求，兼容 wmpf-mcp-bridge 的 get_recent_requests。"""
        data = await self.get_all_requests(limit=limit, keyword=keyword, domain=domain, path_prefix=path_prefix)
        if not compact:
            return data
        compact_items = [
            {"id": item.get("id"), "source": item.get("source"), "method": item.get("method"), "url": item.get("url"), "statusCode": item.get("statusCode")}
            for item in data.get("requests", [])
        ]
        return {"ok": True, "compact": True, "requests": compact_items, "total": data.get("total", len(compact_items))}

    async def get_response_body(self, request_id: str) -> JsonDict:
        """读取 CDP Network.getResponseBody 响应体。"""
        if not request_id:
            return {"ok": False, "error": "request_id 不能为空"}
        try:
            result = await self.cdp.send("Network.getResponseBody", {"requestId": request_id}, timeout_ms=8000)
            return {"ok": True, "requestId": request_id, "result": result.get("result", result)}
        except Exception as exc:
            return {"ok": False, "requestId": request_id, "error": str(exc)}

    async def get_recent_console(self, limit: int = 50) -> JsonDict:
        """返回最近 console、exception 和 paused 事件。"""
        return {"ok": True, "events": list(self.console_events)[-max(1, int(limit)): ]}

    async def get_basic_page_info(self) -> JsonDict:
        """返回兼容旧版的基础页面快照。"""
        return await self.dump_runtime_snapshot()

    async def get_document_html(self, max_length: int = 20_000) -> JsonDict:
        """读取 document.documentElement.outerHTML 前缀。"""
        limit = max(1, int(max_length))
        expr = f"(()=>String(document.documentElement&&document.documentElement.outerHTML||'').slice(0,{limit}))()"
        result = await self.runtime_eval(expr)
        return {"ok": bool(result.get("ok")), "html": result.get("value"), "maxLength": limit}

    async def query_selector_text(self, selector: str, max_length: int = 10_000) -> JsonDict:
        """读取 document.querySelector(selector) 的文本和 HTML 摘要。"""
        if not selector:
            return {"ok": False, "error": "selector 不能为空"}
        limit = max(1, int(max_length))
        expr = f"(()=>{{const el=document.querySelector({json.dumps(selector)});if(!el)return {{ok:false,selector:{json.dumps(selector)},error:'Element not found'}};const cut=v=>String(v??'').slice(0,{limit});return {{ok:true,selector:{json.dumps(selector)},innerText:cut(el.innerText),textContent:cut(el.textContent),outerHTML:cut(el.outerHTML)}};}})()"
        result = await self.runtime_eval(expr)
        return result.get("value") if isinstance(result.get("value"), dict) else result

    async def inspect_window_keys(self, pattern: str | None = None, limit: int = 200) -> JsonDict:
        """列出 globalThis/window key，可按关键词过滤。"""
        expr = f"(()=>{{const pat={json.dumps(pattern or '')}.toLowerCase();const keys=Object.keys(globalThis).sort();const f=pat?keys.filter(k=>k.toLowerCase().includes(pat)):keys;return {{ok:true,pattern:pat,count:f.length,keys:f.slice(0,{max(1,int(limit))})}};}})()"
        result = await self.runtime_eval(expr)
        return result.get("value") if isinstance(result.get("value"), dict) else result

    async def search_global_string(self, keyword: str, max_length: int = 20_000) -> JsonDict:
        """搜索 document、storage、window keys 和请求缓存中的单个关键词。"""
        hits = await self.search_runtime_keywords([keyword])
        text = json.dumps(hits, ensure_ascii=False)
        return {"ok": True, "keyword": keyword, "result": safe_json_loads(text[: max(1, int(max_length))])}
