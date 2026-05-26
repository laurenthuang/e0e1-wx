"""摘要：创建 package 内置 Streamable HTTP MCP 应用并注册 SKILL.md 分组工具。"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from package.mcp_control.crypto_helpers import json_text
from package.mcp_control.runtime_session import McpRuntimeSession


def create_mcp_app(runtime: McpRuntimeSession | None = None) -> FastMCP:
    """创建 MCP 应用实例，并把当前 SKILL.md 需要的分组工具注册进去。"""
    session = runtime or McpRuntimeSession()
    mcp = FastMCP(
        name="wxcdp",
        instructions=(
            "本 MCP 内置于 e0e1-wx-gui 的 package/mcp_control 中。"
            "按当前目录 SKILL.md 使用 connection_ops、network_ops、runtime_ops、debugger_ops、"
            "analysis_ops、decrypt_ops、reverse_ops、replay_ops、pentest_ops、route_ops。"
        ),
        streamable_http_path="/mcp",
        stateless_http=False,
    )

    @mcp.tool(name="connection_ops", description="CDP 连接与 target 管理：status/connect_wmpf/select_appservice_context/list_targets/switch_target。")
    async def connection_ops(action: str = "status", ws_url: str | None = None, wsUrl: str | None = None, target_id: str | None = None, targetId: str | None = None) -> str:
        """执行连接管理类操作。"""
        return await session.connection_ops(action, ws_url=ws_url, wsUrl=wsUrl, target_id=target_id, targetId=targetId)

    @mcp.tool(name="network_ops", description="网络采集与 Hook：network_enable/install_early_hooks/hook_wx_request/hook_upload_apis/hook_fetch_and_xhr/fetch_from_page/upload_formdata_from_page/get_all_requests 等。")
    async def network_ops(
        action: str,
        request_id: str | None = None,
        requestId: str | None = None,
        id: str | None = None,
        limit: int | None = None,
        keyword: str | None = None,
        query: str | None = None,
        keywords: list[str] | None = None,
        domain: str | None = None,
        path_prefix: str | None = None,
        pathPrefix: str | None = None,
        url: str | None = None,
        method: str | None = None,
        headers: dict[str, Any] | None = None,
        body: Any | None = None,
        fields: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        await_promise: bool = True,
    ) -> str:
        """执行网络采集类操作。"""
        return await session.network_ops(action, request_id=request_id, requestId=requestId, id=id, limit=limit, keyword=keyword, query=query, keywords=keywords, domain=domain, path_prefix=path_prefix, pathPrefix=pathPrefix, url=url, method=method, headers=headers, body=body, fields=fields, files=files, await_promise=await_promise)

    @mcp.tool(name="runtime_ops", description="运行时求值、快照、敏感 Storage 扫描、上传面检测、交互与 Vuex 检查。")
    async def runtime_ops(
        action: str,
        expression: str | None = None,
        await_promise: bool = True,
        context_id: int | None = None,
        contextId: int | None = None,
        selector: str | None = None,
        text: str | None = None,
        path: str | None = None,
        value: Any | None = None,
        dryRun: bool = True,
        requireConfirm: bool = False,
    ) -> str:
        """执行运行时类操作。"""
        return await session.runtime_ops(action, expression=expression, await_promise=await_promise, context_id=context_id, contextId=contextId, selector=selector, text=text, path=path, value=value, dryRun=dryRun, requireConfirm=requireConfirm)

    @mcp.tool(name="debugger_ops", description="源码分析、断点、执行控制和 WebSocket 消息。")
    async def debugger_ops(
        action: str,
        query: str | None = None,
        text: str | None = None,
        expression: str | None = None,
        url: str | None = None,
        pattern: str | None = None,
        script_id: str | None = None,
        scriptId: str | None = None,
        file_path: str | None = None,
        filePath: str | None = None,
        offset: int | None = None,
        length: int | None = None,
        start_line: int | None = None,
        startLine: int | None = None,
        end_line: int | None = None,
        endLine: int | None = None,
        case_sensitive: bool = False,
        is_regex: bool = False,
        max_results: int | None = None,
        url_filter: str | None = None,
        urlFilter: str | None = None,
        await_promise: bool = True,
        context_id: int | None = None,
        contextId: int | None = None,
        kind: str | None = None,
        type: str | None = None,
    ) -> str:
        """执行调试器类操作。"""
        return await session.debugger_ops(action, query=query, text=text, expression=expression, url=url, pattern=pattern, script_id=script_id, scriptId=scriptId, file_path=file_path, filePath=filePath, offset=offset, length=length, start_line=start_line, startLine=startLine, end_line=end_line, endLine=endLine, case_sensitive=case_sensitive, is_regex=is_regex, max_results=max_results, url_filter=url_filter, urlFilter=urlFilter, await_promise=await_promise, context_id=context_id, contextId=contextId, kind=kind, type=type)

    @mcp.tool(name="analysis_ops", description="接口资产、认证/IDOR/敏感信息/上传/支付风险线索、重放计划和报告导出。")
    async def analysis_ops(action: str, request_id: str | None = None, requestId: str | None = None, request_id_a: str | None = None, requestIdA: str | None = None, request_id_b: str | None = None, requestIdB: str | None = None, limit: int | None = None) -> str:
        """执行分析类操作。"""
        return await session.analysis_ops(action, request_id=request_id, requestId=requestId, request_id_a=request_id_a, requestIdA=requestIdA, request_id_b=request_id_b, requestIdB=requestIdB, limit=limit)

    @mcp.tool(name="decrypt_ops", description="编码识别、解码、解密、多层流水线和运行时加密函数调用。")
    async def decrypt_ops(
        action: str,
        value: str | None = None,
        algorithm: str | None = None,
        key: str | None = None,
        mode: str | None = None,
        iv: str | None = None,
        input_encoding: str | None = None,
        key_encoding: str | None = None,
        iv_encoding: str | None = None,
        encoding: str | None = None,
        steps: list[Any] | None = None,
        function_name: str | None = None,
        functionName: str | None = None,
        args: list[Any] | None = None,
    ) -> str:
        """执行解密类操作。"""
        return await session.decrypt_ops(action, value=value, algorithm=algorithm, key=key, mode=mode, iv=iv, input_encoding=input_encoding, key_encoding=key_encoding, iv_encoding=iv_encoding, encoding=encoding, steps=steps, function_name=function_name, functionName=functionName, args=args)

    @mcp.tool(name="reverse_ops", description="逆向案例匹配、加密模式识别和逆向策略建议。")
    async def reverse_ops(action: str = "detect_reverse_strategy", text: str | None = None, source: str | None = None) -> str:
        """执行逆向辅助类操作。"""
        return await session.reverse_ops(action, text=text, source=source)

    @mcp.tool(name="replay_ops", description="自动重放任务管理；默认只生成计划，不自动发送写请求。")
    async def replay_ops(action: str, request_id: str | None = None, requestId: str | None = None, job_id: str | None = None, jobId: str | None = None) -> str:
        """执行重放计划类操作。"""
        return await session.replay_ops(action, request_id=request_id, requestId=requestId, job_id=job_id, jobId=jobId)

    @mcp.tool(name="pentest_ops", description="主动扫描任务管理，任务隔离并可查询。")
    async def pentest_ops(action: str, scope: str | None = None, job_id: str | None = None, jobId: str | None = None) -> str:
        """执行主动扫描任务类操作。"""
        return await session.pentest_ops(action, scope=scope, job_id=job_id, jobId=jobId)

    @mcp.tool(name="route_ops", description="小程序路由操作：inspect_routes/enable_redirect_guard/disable_redirect_guard/navigate_route/navigate_route_with_guard。")
    async def route_ops(
        action: str,
        route: str | None = None,
        is_tabbar: bool = False,
        isTabbar: bool | None = None,
        wait_ms: int | None = None,
        waitMs: int | None = None,
    ) -> str:
        """执行小程序路由和防跳转守卫类操作。"""
        return await session.route_ops(
            action,
            route=route,
            is_tabbar=bool(is_tabbar if isTabbar is None else isTabbar),
            wait_ms=wait_ms if wait_ms is not None else waitMs,
        )



    @mcp.tool(name="status", description="Return MCP bridge status and CDP connection state.")
    async def status() -> str:
        """?? MCP ? CDP ???"""
        return await session.connection_ops("status")

    @mcp.tool(name="connect_wmpf", description="Connect to local WMPFDebugger CDP WebSocket.")
    async def connect_wmpf(wsUrl: str | None = None, ws_url: str | None = None) -> str:
        """??????? CDP WebSocket?"""
        return await session.connection_ops("connect_wmpf", wsUrl=wsUrl, ws_url=ws_url)

    @mcp.tool(name="select_appservice_context", description="Auto-detect and select the appservice Runtime execution context.")
    async def select_appservice_context(force: bool = False) -> str:
        """???? appservice ???????"""
        del force
        return await session.connection_ops("select_appservice_context")

    @mcp.tool(name="cdp_call", description="Call an arbitrary CDP method. Supports flatten sessionId.")
    async def cdp_call(method: str, params: dict[str, Any] | None = None, sessionId: str | None = None, session_id: str | None = None) -> str:
        """???? CDP ???"""
        return json_text(await session.cdp_call(method, params or {}, sessionId or session_id))

    @mcp.tool(name="cdp_call_target", description="Attach to targetId with flatten=true and call a CDP method in that session.")
    async def cdp_call_target(targetId: str | None = None, target_id: str | None = None, method: str = "", params: dict[str, Any] | None = None) -> str:
        """??? target ?? session ??? CDP ???"""
        return json_text(await session.cdp_call_target(targetId or target_id or "", method, params or {}))

    @mcp.tool(name="runtime_eval", description="Evaluate JavaScript in current runtime.")
    async def runtime_eval(expression: str, returnByValue: bool = True, awaitPromise: bool = True) -> str:
        """??? Runtime ?? JavaScript?"""
        del returnByValue
        return await session.runtime_ops("runtime_eval", expression=expression, await_promise=awaitPromise)

    @mcp.tool(name="runtime_eval_appservice", description="Evaluate JavaScript in the auto-selected appservice context.")
    async def runtime_eval_appservice(expression: str, forceSelect: bool = False) -> str:
        """? appservice Runtime ?? JavaScript?"""
        if forceSelect:
            await session.select_appservice_context()
        return await session.runtime_ops("runtime_eval_appservice", expression=expression)

    @mcp.tool(name="dump_runtime_snapshot", description="Capture page runtime snapshot for security assessment context.")
    async def dump_runtime_snapshot(maxLength: int = 20_000) -> str:
        """????????????"""
        del maxLength
        return await session.runtime_ops("dump_runtime_snapshot")

    @mcp.tool(name="scan_sensitive_storage", description="Scan wx/local/session storage for OSS/COS/S3, DB, API, payment, SMS, JWT, password, and internal config secrets.")
    async def scan_sensitive_storage() -> str:
        """扫描敏感 Storage。"""
        return await session.runtime_ops("scan_sensitive_storage")

    @mcp.tool(name="inspect_upload_surface", description="Inspect current route for upload/chooseImage/chooseMedia/avatar/file indicators.")
    async def inspect_upload_surface() -> str:
        """检查当前页上传面。"""
        return await session.runtime_ops("inspect_upload_surface")

    @mcp.tool(name="get_basic_page_info", description="Backward-compatible page info snapshot.")
    async def get_basic_page_info() -> str:
        """?????????"""
        return json_text(await session.get_basic_page_info())

    @mcp.tool(name="get_document_html", description="Return document.documentElement.outerHTML prefix.")
    async def get_document_html(maxLength: int = 20_000) -> str:
        """?? document HTML ???"""
        return json_text(await session.get_document_html(maxLength))

    @mcp.tool(name="query_selector_text", description="Return text and HTML snippets for document.querySelector(selector).")
    async def query_selector_text(selector: str, maxLength: int = 10_000) -> str:
        """????????? HTML?"""
        return json_text(await session.query_selector_text(selector, maxLength))

    @mcp.tool(name="list_interactive_elements", description="List clickable/input elements with risk hints.")
    async def list_interactive_elements() -> str:
        """????????"""
        return await session.runtime_ops("list_interactive_elements")

    @mcp.tool(name="safe_click_and_observe", description="Click one element and observe passive deltas. Dangerous texts require requireConfirm=true.")
    async def safe_click_and_observe(selector: str, waitMs: int = 1500, captureBeforeAfter: bool = True, requireConfirm: bool = False) -> str:
        """????????????"""
        del waitMs, captureBeforeAfter
        return await session.runtime_ops("safe_click_and_observe", selector=selector, requireConfirm=requireConfirm)

    @mcp.tool(name="input_text_and_observe", description="Input text into one field and observe passive deltas.")
    async def input_text_and_observe(selector: str, text: str, waitMs: int = 800) -> str:
        """??????????"""
        del waitMs
        return await session.runtime_ops("input_text_and_observe", selector=selector, text=text)

    @mcp.tool(name="network_enable", description="Enable CDP Network domain.")
    async def network_enable() -> str:
        """?? CDP Network domain?"""
        return await session.network_ops("network_enable")

    @mcp.tool(name="get_recent_requests", description="Return recent CDP Network requests with optional filtering and compact output.")
    async def get_recent_requests(limit: int = 50, domain: str | None = None, pathPrefix: str | None = None, keyword: str | None = None, excludeStatic: bool = True, compact: bool = True) -> str:
        """???????"""
        del excludeStatic
        return json_text(await session.get_recent_requests(limit, domain=domain, path_prefix=pathPrefix, keyword=keyword, compact=compact))

    @mcp.tool(name="get_response_body", description="Return CDP Network.getResponseBody.")
    async def get_response_body(requestId: str | None = None, request_id: str | None = None) -> str:
        """??????"""
        return json_text(await session.get_response_body(requestId or request_id or ""))

    @mcp.tool(name="get_recent_console", description="Return recent console and exception events.")
    async def get_recent_console(limit: int = 50) -> str:
        """??????????"""
        return json_text(await session.get_recent_console(limit))

    @mcp.tool(name="inspect_window_keys", description="List window keys, optionally filtered.")
    async def inspect_window_keys(pattern: str | None = None, limit: int = 200) -> str:
        """?? window/globalThis keys?"""
        return json_text(await session.inspect_window_keys(pattern, limit))

    @mcp.tool(name="search_global_string", description="Search document, scripts, window keys for one keyword.")
    async def search_global_string(keyword: str, maxLength: int = 20_000) -> str:
        """?????????"""
        return json_text(await session.search_global_string(keyword, maxLength))

    @mcp.tool(name="hook_wx_request", description="Inject non-mutating wx.request hook.")
    async def hook_wx_request() -> str:
        """?? wx.request Hook?"""
        return await session.network_ops("hook_wx_request")

    @mcp.tool(name="hook_upload_apis", description="Inject early non-mutating wx.uploadFile/chooseImage/chooseMedia hooks in appservice.")
    async def hook_upload_apis() -> str:
        """注入上传与选图 Hook。"""
        return await session.network_ops("hook_upload_apis")

    @mcp.tool(name="install_early_hooks", description="Install Phase-0 hooks before route navigation: appservice select, wx.request, upload APIs, fetch/XHR.")
    async def install_early_hooks() -> str:
        """Phase 0 最早安装所有 Hook。"""
        return await session.network_ops("install_early_hooks")

    @mcp.tool(name="hook_fetch_and_xhr", description="Inject non-mutating fetch/XHR hooks with response capture.")
    async def hook_fetch_and_xhr() -> str:
        """?? fetch/XHR Hook?"""
        return await session.network_ops("hook_fetch_and_xhr")

    @mcp.tool(name="fetch_from_page", description="Send a page-frame fetch request, useful for testing APIs outside wx.request domain whitelist.")
    async def fetch_from_page(url: str, method: str = "GET", headers: dict[str, Any] | None = None, body: Any | None = None) -> str:
        """在 page-frame 上下文执行 fetch。"""
        return await session.network_ops("fetch_from_page", url=url, method=method, headers=headers, body=body)

    @mcp.tool(name="upload_formdata_from_page", description="Preferred upload helper: send multipart/form-data with page-frame fetch + FormData instead of appservice wx.uploadFile.")
    async def upload_formdata_from_page(
        url: str,
        headers: dict[str, Any] | None = None,
        fields: dict[str, Any] | None = None,
        files: list[dict[str, Any]] | None = None,
        method: str = "POST",
    ) -> str:
        """在 page-frame 上下文构建 FormData 并发起 multipart 上传。"""
        return await session.network_ops("upload_formdata_from_page", url=url, method=method, headers=headers, fields=fields, files=files)

    @mcp.tool(name="get_hooked_requests", description="Return fetch/XHR/wx.request hook records.")
    async def get_hooked_requests(limit: int = 50) -> str:
        """?? Hook ?????"""
        return json_text({"ok": True, "requests": (await session.get_hooked_requests())[-max(1, int(limit)): ]})

    @mcp.tool(name="get_all_requests", description="Return normalized CDP + wx.request + fetch/XHR requests.")
    async def get_all_requests(limit: int = 50, keyword: str | None = None, domain: str | None = None, pathPrefix: str | None = None) -> str:
        """????????"""
        return await session.network_ops("get_all_requests", limit=limit, keyword=keyword, domain=domain, pathPrefix=pathPrefix)

    @mcp.tool(name="get_request_detail", description="Return one normalized request and try CDP response body when possible.")
    async def get_request_detail(requestId: str | None = None, request_id: str | None = None, maxLength: int = 20_000) -> str:
        """???????"""
        del maxLength
        return await session.network_ops("get_request_detail", requestId=requestId, request_id=request_id)

    @mcp.tool(name="get_api_inventory", description="Generate deduplicated API inventory from all observed requests.")
    async def get_api_inventory(limit: int = 300) -> str:
        """?????????"""
        return await session.analysis_ops("get_api_inventory", limit=limit)

    @mcp.tool(name="analyze_auth_surface", description="Analyze authentication fields and replay hints.")
    async def analyze_auth_surface() -> str:
        """??????"""
        return await session.analysis_ops("analyze_auth_surface")

    @mcp.tool(name="find_idor_candidates", description="Find manual IDOR test candidates. Does not send requests.")
    async def find_idor_candidates() -> str:
        """?? IDOR ???"""
        return await session.analysis_ops("find_idor_candidates")

    @mcp.tool(name="find_sensitive_data_exposure", description="Find sensitive fields in observed requests/responses, masked by default.")
    async def find_sensitive_data_exposure() -> str:
        """???????????"""
        return await session.analysis_ops("find_sensitive_data_exposure")

    @mcp.tool(name="find_upload_surfaces", description="Find upload/file related APIs and manual checks.")
    async def find_upload_surfaces() -> str:
        """??????"""
        return await session.analysis_ops("find_upload_surfaces")

    @mcp.tool(name="find_payment_and_order_surfaces", description="Find payment/order/coupon/wallet surfaces. Does not mutate or replay.")
    async def find_payment_and_order_surfaces() -> str:
        """?????????"""
        return await session.analysis_ops("find_payment_and_order_surfaces")

    @mcp.tool(name="find_debug_admin_surfaces", description="Find debug/test/admin/internal/dev/staging/mock indicators.")
    async def find_debug_admin_surfaces() -> str:
        """?????????"""
        return await session.analysis_ops("find_debug_admin_surfaces")

    @mcp.tool(name="build_replay_plan", description="Build a manual replay test plan; never sends the request.")
    async def build_replay_plan(requestId: str | None = None, request_id: str | None = None) -> str:
        """?????????"""
        return await session.analysis_ops("build_replay_plan", requestId=requestId, request_id=request_id)

    @mcp.tool(name="compare_two_requests", description="Compare two observed requests for auth/body/response differences.")
    async def compare_two_requests(requestIdA: str | None = None, request_id_a: str | None = None, requestIdB: str | None = None, request_id_b: str | None = None) -> str:
        """???????"""
        return await session.analysis_ops("compare_two_requests", requestIdA=requestIdA, request_id_a=request_id_a, requestIdB=requestIdB, request_id_b=request_id_b)

    @mcp.tool(name="passive_param_fuzz_suggestions", description="Generate passive fuzz suggestions only; does not send requests.")
    async def passive_param_fuzz_suggestions(requestId: str | None = None, request_id: str | None = None) -> str:
        """???? fuzz ???"""
        return await session.analysis_ops("passive_param_fuzz_suggestions", requestId=requestId, request_id=request_id)

    @mcp.tool(name="inspect_wx_config", description="Inspect __wxConfig, __wxAppCode__, __wxRoute, __wxAppData__ summaries.")
    async def inspect_wx_config(maxLength: int = 20_000) -> str:
        """????????????"""
        del maxLength
        return await session.network_ops("inspect_wx_config")

    @mcp.tool(name="search_runtime_keywords", description="Search runtime, storage, scripts, and observed requests for keywords.")
    async def search_runtime_keywords(keywords: list[str] | None = None, maxLength: int = 20_000) -> str:
        """???????????"""
        del maxLength
        return await session.network_ops("search_runtime_keywords", keywords=keywords or [])

    @mcp.tool(name="trace_request_callstack", description="Return captured call stacks from wx/fetch/XHR hooks.")
    async def trace_request_callstack(requestId: str | None = None, request_id: str | None = None, limit: int = 50) -> str:
        """????????"""
        del limit
        return await session.network_ops("trace_request_callstack", requestId=requestId, request_id=request_id)

    @mcp.tool(name="inspect_vuex_store", description="Inspect Vuex-like store in appservice and save an original state snapshot.")
    async def inspect_vuex_store(maxLength: int = 20_000, forceSelect: bool = False) -> str:
        """?? Vuex-like store?"""
        del maxLength, forceSelect
        return await session.runtime_ops("inspect_vuex_store")

    @mcp.tool(name="patch_vuex_state", description="Patch Vuex-like state. Defaults to dryRun and requires requireConfirm=true to mutate.")
    async def patch_vuex_state(path: str = "", value: Any | None = None, dryRun: bool = True, requireConfirm: bool = False, forceSelect: bool = False) -> str:
        """?? Vuex-like state?"""
        del forceSelect
        return await session.runtime_ops("patch_vuex_state", path=path, value=value, dryRun=dryRun, requireConfirm=requireConfirm)

    @mcp.tool(name="restore_vuex_state", description="Restore Vuex-like state from the snapshot saved by inspect_vuex_store. Defaults to dryRun.")
    async def restore_vuex_state(dryRun: bool = True, requireConfirm: bool = False, forceSelect: bool = False) -> str:
        """?? Vuex-like state?"""
        del forceSelect
        return await session.runtime_ops("restore_vuex_state", dryRun=dryRun, requireConfirm=requireConfirm)

    @mcp.tool(name="find_sign_related_requests", description="Find requests containing sign/signature/timestamp/nonce fields.")
    async def find_sign_related_requests() -> str:
        """?????????"""
        return await session.analysis_ops("find_sign_related_requests")

    @mcp.tool(name="export_session", description="Export current assessment session JSON to output/reports.")
    async def export_session() -> str:
        """???????"""
        return await session.analysis_ops("export_session")

    @mcp.tool(name="generate_security_notes", description="Generate Markdown security assessment notes from observed evidence.")
    async def generate_security_notes(maxLength: int = 80_000) -> str:
        """?????????"""
        del maxLength
        return await session.analysis_ops("generate_security_notes")

    @mcp.tool(name="generate_api_table_markdown", description="Generate Markdown API table.")
    async def generate_api_table_markdown(maxLength: int = 80_000) -> str:
        """?? API Markdown ???"""
        del maxLength
        return await session.analysis_ops("generate_api_table_markdown")

    return mcp
