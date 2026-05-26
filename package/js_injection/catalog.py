"""异步扫描 tools/js 与手工导入 JS 文件的目录模型。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path

from package.js_injection.mode_overrides import (
    SCRIPT_OVERRIDE_FOLLOW_DECLARED,
    coerce_runtime_toggle_override_value,
    resolve_script_mode_override,
)
from package.js_injection.models import normalize_script_mode


def normalized_script_path(path: str | Path) -> str:
    """把脚本路径归一为稳定字符串，供去重和状态持久化使用。"""
    raw_path = os.path.expanduser(str(path or "").strip())
    if not raw_path:
        return ""
    return os.path.normcase(os.path.abspath(raw_path))


def script_id_for_path(path: str | Path) -> str:
    """基于归一化绝对路径生成稳定脚本 ID。"""
    normalized = normalized_script_path(path).casefold()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def discover_tool_js_paths(tools_dir: Path) -> list[Path]:
    """在线程中发现 tools/js 下的所有 JS 文件。"""
    if not tools_dir.exists() or not tools_dir.is_dir():
        return []
    return sorted((item for item in tools_dir.glob("*.js") if item.is_file()), key=lambda item: item.name.casefold())


def parse_js_metadata(source: str) -> dict:
    """解析 UserScript 头部元数据，避免扫描模块依赖 DevTools 包。"""
    metadata: dict[str, str] = {}
    in_block = False
    for line in str(source or "").splitlines():
        stripped = line.strip()
        if stripped == "// ==UserScript==":
            in_block = True
            continue
        if stripped == "// ==/UserScript==":
            break
        if not in_block or not stripped.startswith("// @"):
            continue
        match = re.match(r"^//\s*@(\S+)\s*(.*?)\s*$", stripped)
        if match:
            metadata[match.group(1)] = match.group(2)
    return metadata


def normalize_imported_paths(imported_files: list[str] | tuple[str, ...] | None) -> list[Path]:
    """归一化手工导入路径，仅保留 .js 文件路径。"""
    paths: list[Path] = []
    for raw_path in imported_files or []:
        normalized = normalized_script_path(raw_path)
        if not normalized:
            continue
        path = Path(normalized)
        if path.suffix.casefold() != ".js":
            continue
        paths.append(path)
    return paths


def read_script_descriptor(path: Path, source: str, runtime_toggle_override: str = SCRIPT_OVERRIDE_FOLLOW_DECLARED) -> dict:
    """读取单个脚本的 UTF-8 元数据并生成列表描述。"""
    script_id = script_id_for_path(path)
    display_path = normalized_script_path(path)
    name = path.stem
    try:
        text = path.read_text(encoding="utf-8")
        metadata = parse_js_metadata(text)
        stat = path.stat()
        name = str(metadata.get("name") or name).strip() or path.stem
        declared_mode, mode = resolve_script_mode_override(
            normalize_script_mode(metadata.get("e0e1-mode")),
            coerce_runtime_toggle_override_value(runtime_toggle_override),
        )
        return {
            "id": script_id,
            "name": name,
            "path": display_path,
            "source": source,
            "available": True,
            "signature": f"{int(stat.st_size)}:{int(stat.st_mtime_ns)}",
            "message": "",
            "declared_mode": declared_mode,
            "mode": mode,
        }
    except Exception as exc:
        declared_mode, mode = resolve_script_mode_override(
            normalize_script_mode(""),
            coerce_runtime_toggle_override_value(runtime_toggle_override),
        )
        return {
            "id": script_id,
            "name": name,
            "path": display_path,
            "source": source,
            "available": False,
            "signature": "",
            "message": f"读取失败：{exc}",
            "declared_mode": declared_mode,
            "mode": mode,
        }


async def scan_js_catalog(
    tools_dir: str | Path,
    imported_files: list[str] | tuple[str, ...] | None = None,
    runtime_toggle_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """异步扫描 tools/js 与手工导入脚本，并按路径去重。"""
    tools_path = Path(tools_dir)
    tool_paths = await asyncio.to_thread(discover_tool_js_paths, tools_path)
    imported_paths = normalize_imported_paths(imported_files)
    candidates: list[tuple[Path, str]] = [(path, "tools") for path in tool_paths]
    candidates.extend((path, "imported") for path in imported_paths)

    seen_ids: set[str] = set()
    unique_candidates: list[tuple[Path, str]] = []
    for path, source in candidates:
        script_id = script_id_for_path(path)
        if script_id in seen_ids:
            continue
        seen_ids.add(script_id)
        unique_candidates.append((path, source))

    overrides = {
        str(key): coerce_runtime_toggle_override_value(value)
        for key, value in dict(runtime_toggle_overrides or {}).items()
        if str(key or "").strip() and coerce_runtime_toggle_override_value(value)
    }
    descriptors = await asyncio.gather(
        *(
            asyncio.to_thread(read_script_descriptor, path, source, overrides.get(script_id_for_path(path), False))
            for path, source in unique_candidates
        )
    )
    return [dict(item) for item in descriptors]
