"""在 DevTools worker 内执行 JS 文件注入的异步运行时。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from package.js_injection.catalog import script_id_for_path


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
    """从 Runtime.evaluate 返回中提取 CDP 异常文本。"""
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


def parse_injection_response(response: dict) -> dict:
    """解析注入脚本返回值，失败时抛出可展示异常。"""
    exception_text = _extract_exception_text(response)
    if exception_text:
        raise RuntimeError(exception_text)
    value = _extract_cdp_value(response)
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"注入返回值不是合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("注入返回值为空")
    if not bool(payload.get("ok")):
        raise RuntimeError(str(payload.get("error") or payload.get("message") or "注入失败"))
    return {
        "ok": True,
        "skipped": bool(payload.get("skipped")),
        "message": str(payload.get("message") or ""),
        "log": str(payload.get("log") or ""),
    }


def build_injection_expression(script: dict, source: str, content_hash: str, *, automatic: bool = True) -> str:
    """构造 Runtime.evaluate 表达式，自动注入时附加重复注入保护。"""
    script_id = str(script.get("id") or script_id_for_path(script.get("path") or "")).strip()
    script_name = str(script.get("name") or "JS文件").strip()
    safe_source_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in script_name) or "script"
    if not automatic:
        return f"""
(async function() {{
{_report_runtime_source()}
  try {{
{_indent_source(source)}
    return JSON.stringify({{ ok: true, skipped: false, message: "已注入", log: __e0e1InjectionLog }});
  }} catch (error) {{
    const reason = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    return JSON.stringify({{ ok: false, skipped: false, error: reason }});
  }}
}})();
//# sourceURL=e0e1-js-injection/{safe_source_name}.js
""".strip()
    return f"""
(async function() {{
  const registryKey = "__e0e1JsInjectionRegistry__";
  const scriptId = {json.dumps(script_id, ensure_ascii=False)};
  const contentHash = {json.dumps(content_hash, ensure_ascii=False)};
  const registry = globalThis[registryKey] || (globalThis[registryKey] = Object.create(null));
  if (registry[scriptId] === contentHash) {{
    return JSON.stringify({{ ok: true, skipped: true, message: "已注入，跳过重复注入" }});
  }}
{_report_runtime_source()}
  try {{
{_indent_source(source)}
    registry[scriptId] = contentHash;
    return JSON.stringify({{ ok: true, skipped: false, message: "已注入", log: __e0e1InjectionLog }});
  }} catch (error) {{
    const reason = error && (error.stack || error.message) ? (error.stack || error.message) : String(error);
    return JSON.stringify({{ ok: false, skipped: false, error: reason }});
  }}
}})();
//# sourceURL=e0e1-js-injection/{safe_source_name}.js
""".strip()


def _report_runtime_source() -> str:
    """返回注入脚本可调用的日志上报桥接代码。"""
    return """
  let __e0e1InjectionLog = "";
  const __e0e1SerializeInjectionReport = function(payload) {
    try {
      if (typeof payload === "string") {
        return payload;
      }
      return JSON.stringify(payload);
    } catch (error) {
      return String(payload);
    }
  };
  globalThis.__e0e1JsInjectionReport = function(payload) {
    const text = __e0e1SerializeInjectionReport(payload);
    __e0e1InjectionLog = String(text || "").slice(0, 12000);
    try {
      if (globalThis.console && typeof globalThis.console.log === "function") {
        globalThis.console.log("[e0e1][JS注入]", payload);
      }
    } catch (error) {}
    return __e0e1InjectionLog;
  };
""".rstrip()


def _indent_source(source: str) -> str:
    """缩进用户脚本源码，保持源码按原样执行。"""
    return "\n".join(f"    {line}" for line in str(source or "").splitlines())


async def read_js_source(path: str | Path) -> str:
    """在线程中按 UTF-8 读取 JS 文件源码。"""
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


async def inject_js_file(bridge, script: dict, injected_keys: set[tuple[str, str]], *, automatic: bool = True) -> dict:
    """读取并向当前小程序 Runtime 注入一个 JS 文件，按自动/手工模式决定是否去重。"""
    script_path = str(script.get("path") or "").strip()
    if not script_path:
        raise RuntimeError("JS 文件路径为空")
    source = await read_js_source(script_path)
    script_id = str(script.get("id") or script_id_for_path(script_path)).strip()
    content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    injected_key = (script_id, content_hash)
    if automatic and injected_key in injected_keys:
        return {"ok": True, "skipped": True, "message": "已注入，跳过重复注入"}
    expression = build_injection_expression({**script, "id": script_id}, source, content_hash, automatic=automatic)
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
    result = parse_injection_response(response)
    if automatic:
        injected_keys.add(injected_key)
    return result
