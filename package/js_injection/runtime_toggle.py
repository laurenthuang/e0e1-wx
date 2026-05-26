"""封装长期 JS 脚本的启用、取消与返回值解析。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from pathlib import Path

from package.js_injection.catalog import script_id_for_path


def runtime_toggle_controller_name(script_id: str) -> str:
    """根据脚本 ID 生成稳定的长期脚本控制器名。"""
    return f"__e0e1RuntimeToggle__{str(script_id or '').strip()}"


def _extract_cdp_value(response: dict):
    """从 Runtime.evaluate 返回中提取远程对象 value。"""
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    remote_object = result.get("result")
    if not isinstance(remote_object, dict):
        return None
    return remote_object.get("value")


def _extract_exception_text(response: dict) -> str:
    """从 Runtime.evaluate 返回中提取异常文本。"""
    if not isinstance(response, dict):
        return ""
    result = response.get("result")
    if not isinstance(result, dict):
        return ""
    details = result.get("exceptionDetails")
    if not isinstance(details, dict):
        return ""
    text = str(details.get("text") or "").strip()
    exception = details.get("exception")
    if isinstance(exception, dict):
        description = str(exception.get("description") or exception.get("value") or "").strip()
        if description:
            return description
    return text


def _raise_cdp_error(response: dict, fallback: str) -> None:
    """检查通用 CDP 响应中的 error 字段并抛出中文异常。"""
    if not isinstance(response, dict):
        return
    error = response.get("error")
    if not isinstance(error, dict):
        return
    message = str(error.get("message") or fallback or "CDP 命令执行失败").strip()
    code = error.get("code")
    if code is not None:
        message = f"{message}（code={code}）"
    raise RuntimeError(message)


def _extract_add_script_identifier(response: dict) -> str:
    """从 Page.addScriptToEvaluateOnNewDocument 响应中读取持久脚本标识。"""
    _raise_cdp_error(response, "长期脚本持久注册失败")
    if not isinstance(response, dict):
        return ""
    result = response.get("result")
    if not isinstance(result, dict):
        return ""
    return str(result.get("identifier") or "").strip()


def parse_runtime_toggle_response(response: dict, *, enabled_default: bool) -> dict:
    """解析长期脚本启用或取消的 CDP 返回结果。"""
    _raise_cdp_error(response, "长期脚本执行失败")
    exception_text = _extract_exception_text(response)
    if exception_text:
        raise RuntimeError(exception_text)
    value = _extract_cdp_value(response)
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"长期脚本返回值不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("长期脚本返回值为空")
    if not bool(payload.get("ok", True)):
        raise RuntimeError(str(payload.get("error") or payload.get("message") or "长期脚本执行失败"))
    return {
        "ok": True,
        "enabled": bool(payload.get("enabled", enabled_default)),
        "message": str(payload.get("message") or ""),
        "log": str(payload.get("log") or ""),
        "controller_key": str(payload.get("controller_key") or ""),
    }


async def read_runtime_toggle_source(path: str | Path) -> str:
    """在线程中按 UTF-8 读取长期脚本源码。"""
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


def _indent_source(source: str) -> str:
    """缩进用户脚本源码，保持执行顺序稳定。"""
    return "\n".join(f"    {line}" for line in str(source or "").splitlines())


def build_runtime_toggle_enable_expression(script: dict, source: str, controller_key: str) -> str:
    """构造“注册控制器并立即启用”的 Runtime.evaluate 表达式。"""
    script_name = str(script.get("name") or "runtime-toggle").strip() or "runtime-toggle"
    safe_source_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in script_name)
    return f"""
(async function() {{
  const controllerKey = {json.dumps(controller_key, ensure_ascii=False)};
  const registryKey = "__e0e1RuntimeToggleRegistry__";
  const registry = globalThis[registryKey] || (globalThis[registryKey] = Object.create(null));
  globalThis.__e0e1RegisterRuntimeToggle = function(controller) {{
    registry[controllerKey] = controller;
    return controller;
  }};
  try {{
{_indent_source(source)}
    const controller = registry[controllerKey];
    if (!controller || typeof controller.enable !== "function" || typeof controller.disable !== "function") {{
      throw new Error("脚本不支持长期启停");
    }}
    const result = await controller.enable();
    const status = typeof controller.status === "function" ? await controller.status() : {{}};
    return JSON.stringify({{
      ok: true,
      enabled: Boolean((status && status.enabled) ?? (result && result.enabled) ?? true),
      message: String((result && result.message) || (status && status.message) || "已启用（当前页面和后续页面）"),
      log: String((result && result.log) || (status && status.log) || ""),
      controller_key: controllerKey
    }});
  }} catch (error) {{
    const reason = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    return JSON.stringify({{ ok: false, enabled: false, error: reason, controller_key: controllerKey }});
  }} finally {{
    try {{
      delete globalThis.__e0e1RegisterRuntimeToggle;
    }} catch (error) {{}}
  }}
}})();
//# sourceURL=e0e1-js-runtime-toggle/{safe_source_name}.js
""".strip()


def build_runtime_toggle_persistent_expression(script: dict, source: str, controller_key: str) -> str:
    """构造后续新页面自动启用长期脚本的持久表达式。"""
    return build_runtime_toggle_enable_expression(script, source, controller_key)


def build_runtime_toggle_disable_expression(controller_key: str) -> str:
    """构造“调用控制器 disable()”的 Runtime.evaluate 表达式。"""
    return f"""
(async function() {{
  const controllerKey = {json.dumps(controller_key, ensure_ascii=False)};
  const registry = globalThis.__e0e1RuntimeToggleRegistry__ || Object.create(null);
  const controller = registry[controllerKey];
  if (!controller || typeof controller.disable !== "function") {{
    return JSON.stringify({{ ok: true, enabled: false, message: "已取消", log: "", controller_key: controllerKey }});
  }}
  try {{
    const result = await controller.disable();
    const status = typeof controller.status === "function" ? await controller.status() : {{}};
    return JSON.stringify({{
      ok: true,
      enabled: Boolean((status && status.enabled) ?? (result && result.enabled) ?? false),
      message: String((result && result.message) || (status && status.message) || "已取消"),
      log: String((result && result.log) || (status && status.log) || ""),
      controller_key: controllerKey
    }});
  }} catch (error) {{
    const reason = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    return JSON.stringify({{ ok: false, enabled: true, error: reason, controller_key: controllerKey }});
  }}
}})();
""".strip()


async def remove_runtime_toggle_persistent_script(bridge, persistent_identifier: str) -> None:
    """按持久脚本标识移除后续页面自动执行注册。"""
    identifier = str(persistent_identifier or "").strip()
    if not identifier:
        return
    response = await bridge.send_cdp_command(
        "Page.removeScriptToEvaluateOnNewDocument",
        {"identifier": identifier},
        timeout=10.0,
    )
    _raise_cdp_error(response, "移除长期脚本持久注册失败")


async def enable_runtime_js_file(bridge, script: dict) -> dict:
    """读取长期脚本，注册新页面持久脚本并立即启用当前页面。"""
    script_path = str(script.get("path") or "").strip()
    if not script_path:
        raise RuntimeError("JS 文件路径为空")
    source = await read_runtime_toggle_source(script_path)
    script_id = str(script.get("id") or script_id_for_path(script_path)).strip()
    controller_key = runtime_toggle_controller_name(script_id)
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    normalized_script = {**script, "id": script_id}
    persistent_expression = build_runtime_toggle_persistent_expression(normalized_script, source, controller_key)
    _raise_cdp_error(await bridge.send_cdp_command("Page.enable", {}, timeout=10.0), "启用页面脚本域失败")
    persistent_response = await bridge.send_cdp_command(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": persistent_expression},
        timeout=10.0,
    )
    persistent_identifier = _extract_add_script_identifier(persistent_response)
    if not persistent_identifier:
        raise RuntimeError("长期脚本持久注册未返回标识")
    expression = build_runtime_toggle_enable_expression(normalized_script, source, controller_key)
    try:
        response = await bridge.send_cdp_command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "includeCommandLineAPI": True,
            },
            timeout=10.0,
        )
        result = parse_runtime_toggle_response(response, enabled_default=True)
    except Exception:
        with contextlib.suppress(Exception):
            await remove_runtime_toggle_persistent_script(bridge, persistent_identifier)
        raise
    result["signature"] = f"{script_id}:{content_hash}"
    result["persistent_identifier"] = persistent_identifier
    return result


async def disable_runtime_js_file(bridge, script: dict, *, persistent_identifier: str = "") -> dict:
    """在当前 runtime 中取消长期脚本，并清理后续页面自动执行注册。"""
    script_path = str(script.get("path") or "").strip()
    script_id = str(script.get("id") or script_id_for_path(script_path)).strip()
    controller_key = runtime_toggle_controller_name(script_id)
    response = await bridge.send_cdp_command(
        "Runtime.evaluate",
        {
            "expression": build_runtime_toggle_disable_expression(controller_key),
            "returnByValue": True,
            "awaitPromise": True,
            "includeCommandLineAPI": True,
        },
        timeout=10.0,
    )
    result = parse_runtime_toggle_response(response, enabled_default=False)
    await remove_runtime_toggle_persistent_script(bridge, persistent_identifier)
    return result
