"""整理云函数调用记录的归一化、合并、展示和重放辅助函数。"""

from __future__ import annotations

import copy
import json


SOURCE_LABELS = {
    "dynamic": "动态",
    "manual": "手动",
    "replay": "重放",
    "static": "静态",
    "runtime_static": "运行时静态",
}
ENTRY_TYPE_LABELS = {
    "function": "云函数",
    "storage": "云存储",
    "container": "云托管",
    "database": "云数据库",
}


def _format_value(value) -> str:
    """把任意字段值压缩成适合 UI 展示的短文本。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple, set)):
        payload = list(value) if isinstance(value, (list, tuple, set)) else value
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(payload)
    text = str(value).strip()
    return text


def _safe_int(value, default: int = 0) -> int:
    """安全地把值转换成整数。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value, default: float = 0.0) -> float:
    """安全地把值转换成浮点数。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _source_label(origin: str) -> str:
    """把来源标识转换成中文展示文案。"""
    text = str(origin or "").strip()
    return SOURCE_LABELS.get(text, text or "-")


def _entry_type_label(entry_type: str) -> str:
    """把调用类型转换成中文展示文案。"""
    text = str(entry_type or "").strip()
    if not text:
        return "-"
    if text.startswith("db"):
        return ENTRY_TYPE_LABELS["database"]
    return ENTRY_TYPE_LABELS.get(text, text)


def _ensure_request(call: dict) -> dict:
    """把调用请求整理成统一的可序列化结构。"""
    request = call.get("request")
    request_data = copy.deepcopy(request) if isinstance(request, dict) else {}
    data = call.get("data")
    if isinstance(data, dict):
        request_data.setdefault("data", copy.deepcopy(data))
    if "name" not in request_data and call.get("name") is not None:
        request_data["name"] = str(call.get("name") or "")
    if "timeout_seconds" not in request_data and call.get("timeout_seconds") not in (None, ""):
        request_data["timeout_seconds"] = _safe_float(call.get("timeout_seconds"))
    return request_data


def _ensure_response(call: dict) -> dict | list | str | int | float | bool | None:
    """把调用响应整理成统一的可序列化结构。"""
    if "response" in call:
        return copy.deepcopy(call.get("response"))
    if "result" in call:
        return copy.deepcopy(call.get("result"))
    return None


def normalize_cloud_call_record(call: dict, *, default_origin: str = "dynamic") -> dict:
    """把云函数调用记录统一成可展示、可重放的标准结构。"""
    call = dict(call or {}) if isinstance(call, dict) else {}
    request = _ensure_request(call)
    response = _ensure_response(call)
    origin = str(call.get("origin") or default_origin or "dynamic").strip() or "dynamic"
    entry_type = str(call.get("entry_type") or call.get("type") or "function").strip() or "function"
    source_call_id = str(call.get("source_call_id") or call.get("replay_of") or "").strip()
    call_id = str(call.get("call_id") or "").strip()
    timestamp = str(call.get("timestamp") or call.get("time") or "").strip()
    start_ts = _safe_int(call.get("start_ts") or call.get("ts") or call.get("timestamp_ms"), 0)
    end_ts = _safe_int(call.get("end_ts") or call.get("finished_ts"), 0)
    duration_ms = _safe_int(call.get("duration_ms"), 0)
    if duration_ms <= 0 and start_ts > 0 and end_ts >= start_ts:
        duration_ms = end_ts - start_ts
    if not call_id:
        if origin == "replay" and source_call_id:
            call_id = f"replay:{source_call_id}"
        else:
            stable_name = str(call.get("name") or request.get("name") or call.get("method_name") or "").strip()
            call_id = f"{origin}:{stable_name}:{start_ts or end_ts or len(request)}"
    status = str(call.get("status") or "").strip()
    if not status:
        if call.get("ok") is True:
            status = "success"
        elif call.get("ok") is False:
            status = "fail"
    normalized = {
        "call_id": call_id,
        "origin": origin,
        "source_call_id": source_call_id,
        "app_id": str(call.get("app_id") or call.get("appId") or "").strip(),
        "method_name": str(call.get("method_name") or call.get("method") or "").strip(),
        "entry_type": entry_type,
        "name": str(call.get("name") or request.get("name") or "").strip(),
        "request": request,
        "response": response,
        "result": copy.deepcopy(response),
        "status": status,
        "error": copy.deepcopy(call.get("error")),
        "timestamp": timestamp,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_ms": duration_ms,
        "timeout_seconds": _safe_float(call.get("timeout_seconds") or request.get("timeout_seconds"), 0.0),
        "replayable": bool(call.get("replayable", entry_type == "function")),
        "raw": copy.deepcopy(call),
    }
    if not normalized["request"] and isinstance(call.get("data"), dict):
        normalized["request"] = {"data": copy.deepcopy(call.get("data"))}
    if normalized["response"] is None and status == "success" and isinstance(call.get("response"), dict):
        normalized["response"] = copy.deepcopy(call.get("response"))
    return normalized


def merge_cloud_call_history(base_history: list | None, update_history: list | None) -> list[dict]:
    """按 call_id 合并云函数历史，保留最新记录并保持最新顺序。"""
    merged: dict[str, dict] = {}
    ordered_keys: list[str] = []
    for item in [*(base_history or []), *(update_history or [])]:
        if not isinstance(item, dict):
            continue
        normalized = normalize_cloud_call_record(item, default_origin=str(item.get("origin") or item.get("source") or "manual"))
        key = str(normalized.get("call_id") or "").strip()
        if not key:
            key = json.dumps(normalized.get("raw") or {}, ensure_ascii=False, sort_keys=True, default=str)
        if key in merged:
            try:
                ordered_keys.remove(key)
            except ValueError:
                pass
        merged[key] = normalized
        ordered_keys.append(key)
    return [merged[key] for key in ordered_keys]


def cloud_call_row_values(entry: dict) -> tuple[str, str, str, str, str, str]:
    """把调用记录压缩成表格一行可直接展示的文本。"""
    normalized = normalize_cloud_call_record(entry, default_origin=str(entry.get("origin") or "manual"))
    duration_ms = _safe_int(normalized.get("duration_ms") or 0)
    duration_text = f"{duration_ms} ms" if duration_ms > 0 else ""
    return (
        _source_label(str(normalized.get("origin") or "")),
        _entry_type_label(str(normalized.get("entry_type") or "")),
        str(normalized.get("name") or "-"),
        str(normalized.get("status") or "-"),
        duration_text,
        str(normalized.get("timestamp") or ""),
    )


def cloud_call_detail_rows(entry: dict) -> list[tuple[str, str]]:
    """把调用记录展开成详情页的键值行。"""
    normalized = normalize_cloud_call_record(entry, default_origin=str(entry.get("origin") or "manual"))
    rows: list[tuple[str, str]] = []
    for key, label in (
        ("call_id", "调用标识"),
        ("origin", "来源"),
        ("source_call_id", "回放源"),
        ("app_id", "AppId"),
        ("method_name", "方法"),
        ("name", "名称"),
        ("entry_type", "类型"),
        ("status", "状态"),
        ("duration_ms", "耗时"),
        ("timeout_seconds", "超时"),
    ):
        value = normalized.get(key)
        if value in (None, "", 0, 0.0):
            continue
        if key == "origin":
            rows.append((label, _format_value(value)))
            continue
        if key == "entry_type":
            rows.append((label, _entry_type_label(str(value))))
            continue
        if key == "duration_ms":
            rows.append((label, f"{_safe_int(value)} ms"))
            continue
        if key == "timeout_seconds":
            rows.append((label, f"{_safe_float(value):g} s"))
            continue
        rows.append((label, _format_value(value)))
    if normalized.get("request") not in (None, {}, []):
        rows.append(("请求", _format_value(normalized["request"])))
    if normalized.get("response") not in (None, {}, []):
        rows.append(("响应", _format_value(normalized["response"])))
    if normalized.get("error") not in (None, "", {}):
        rows.append(("错误", _format_value(normalized["error"])))
    return rows


def build_cloud_call_replay_payload(entry: dict, timeout_seconds: float) -> dict:
    """根据选中的调用记录生成可直接下发的重放参数。"""
    normalized = normalize_cloud_call_record(entry, default_origin=str(entry.get("origin") or "manual"))
    request = normalized.get("request") if isinstance(normalized.get("request"), dict) else {}
    data = request.get("data") if isinstance(request.get("data"), dict) else {}
    source_call_id = str(normalized.get("source_call_id") or normalized.get("call_id") or "").strip()
    return {
        "name": str(normalized.get("name") or ""),
        "data": copy.deepcopy(data),
        "timeout_seconds": _safe_float(timeout_seconds or normalized.get("timeout_seconds") or 5.0, 5.0),
        "origin": "replay",
        "source_call_id": source_call_id,
        "call_id": f"replay:{source_call_id or 'unknown'}",
        "replay_of": source_call_id,
    }
