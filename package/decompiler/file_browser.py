"""提供目录浏览、文本编码识别和局部文件读取能力。"""

from __future__ import annotations

import codecs
import io
import mmap
from pathlib import Path

FORCED_TEXT_EXTENSIONS = {
    ".html",
    ".htm",
    ".wxml",
    ".xml",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".jsx",
    ".tsx",
    ".json",
    ".jsonc",
    ".css",
    ".wxss",
    ".scss",
    ".sass",
    ".less",
    ".yml",
    ".yaml",
    ".md",
}


def _printable_text_ratio(text: str) -> float:
    """计算文本中可打印字符占比，辅助区分文本和二进制。"""
    if not text:
        return 0.0
    printable_count = sum(1 for char in text if char in "\t\n\r" or (char.isprintable() and char != "\x00"))
    return printable_count / max(1, len(text))


def _likely_utf16_encoding(sample: bytes) -> str:
    """根据 BOM 和空字节分布推测 UTF-16 编码。"""
    if sample.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    if len(sample) < 8:
        return ""

    pair_count = len(sample) // 2
    even_bytes = sample[: pair_count * 2 : 2]
    odd_bytes = sample[1 : pair_count * 2 : 2]
    even_null_ratio = even_bytes.count(0) / max(1, len(even_bytes))
    odd_null_ratio = odd_bytes.count(0) / max(1, len(odd_bytes))

    candidates: list[str] = []
    if odd_null_ratio > 0.30 and even_null_ratio < 0.10:
        candidates.append("utf-16-le")
    if even_null_ratio > 0.30 and odd_null_ratio < 0.10:
        candidates.append("utf-16-be")

    for encoding in candidates:
        try:
            text = sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        if _printable_text_ratio(text) > 0.85:
            return encoding
    return ""


def detect_text_encoding(sample: bytes) -> str:
    """根据文件头与常见编码尝试判断文本编码。"""
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    utf16_encoding = _likely_utf16_encoding(sample)
    if utf16_encoding:
        return utf16_encoding
    for encoding in ("utf-8", "gb18030", "gbk", "big5"):
        try:
            sample.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8"


def should_force_text_preview(path: Path) -> bool:
    """根据文件后缀判断是否应优先按文本预览。"""
    return path.suffix.lower() in FORCED_TEXT_EXTENSIONS


def looks_binary(sample: bytes, *, force_text: bool = False) -> bool:
    """根据采样内容判断文件是否明显为二进制。"""
    if force_text:
        return False
    if not sample:
        return False
    if _likely_utf16_encoding(sample):
        return False
    if b"\x00" in sample:
        return True
    control_count = sum(1 for byte in sample if byte < 32 and byte not in {9, 10, 13})
    return control_count / max(1, len(sample)) > 0.30


def iter_text_files(output_dirs: list[Path]) -> list[Path]:
    """递归收集输出目录下可搜索的文本文件。"""
    files: list[Path] = []
    skipped_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg", ".mp3", ".mp4", ".ttf", ".woff", ".woff2"}
    skipped_parts = {".git", ".e0e1_cache", "__pycache__"}
    for output_dir in output_dirs:
        if not output_dir.is_dir():
            continue
        for path in output_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skipped_parts for part in path.parts):
                continue
            if path.suffix.lower() in skipped_suffixes:
                continue
            try:
                with path.open("rb") as file:
                    sample = file.read(4096)
            except OSError:
                continue
            if looks_binary(sample, force_text=should_force_text_preview(path)):
                continue
            files.append(path)
    return files


def read_text_lines(path: Path) -> list[tuple[int, str]]:
    """按 utf-8 优先策略读取文本文件的全部行。"""
    with path.open("rb") as file:
        sample = file.read(4096)
        encoding = detect_text_encoding(sample)
        file.seek(0)
        text_file = io.TextIOWrapper(file, encoding=encoding or "utf-8", errors="replace", newline="")
        try:
            return [(line_number, text) for line_number, text in enumerate(text_file, start=1)]
        finally:
            text_file.detach()


def _split_line_ending(text: str) -> tuple[str, str]:
    """拆分一行文本主体和换行结尾。"""
    if text.endswith("\r\n"):
        return text[:-2], "\r\n"
    if text.endswith("\n") or text.endswith("\r"):
        return text[:-1], text[-1]
    return text, ""


def trim_preview_text_for_ui(text: str, max_line_chars: int) -> tuple[str, bool]:
    """裁剪预览文本中的超长行，避免 Qt 自动换行计算拖垮界面。"""
    limit = max(20, int(max_line_chars or 0))
    changed = False
    lines: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        body, ending = _split_line_ending(raw_line)
        if len(body) <= limit:
            lines.append(raw_line)
            continue
        keep = max(1, limit - 3)
        lines.append(body[:keep] + "..." + ending)
        changed = True
    if text and not lines:
        body, ending = _split_line_ending(text)
        if len(body) > limit:
            keep = max(1, limit - 3)
            return body[:keep] + "..." + ending, True
    return "".join(lines), changed


def trim_line_around_match(text: str, max_chars: int, match_start: int = 0, match_end: int = 0, match_text: str = "") -> tuple[str, bool]:
    """把超长目标行裁剪到命中附近，避免 UI 预览渲染整条长行。"""
    limit = max(0, int(max_chars or 0))
    if limit <= 0:
        return "", bool(text)
    if len(text) <= limit:
        return text, False

    body = text.rstrip("\r\n")
    ending = text[len(body) :]
    body_limit = max(1, limit - len(ending))
    search_text = str(match_text or "")
    start = min(max(0, int(match_start or 0)), len(body))
    end = min(max(start, int(match_end or start)), len(body))
    if search_text and body[start : start + len(search_text)] != search_text:
        found_index = body.find(search_text)
        if found_index >= 0:
            start = found_index
            end = min(len(body), found_index + len(search_text))

    marker_budget = 6
    window_limit = max(1, body_limit - marker_budget)
    match_width = max(1, end - start)
    left_padding = max(0, (window_limit - match_width) // 2)
    window_start = max(0, start - left_padding)
    window_end = min(len(body), window_start + window_limit)
    window_start = max(0, window_end - window_limit)

    prefix = "..." if window_start > 0 else ""
    suffix = "..." if window_end < len(body) else ""
    trimmed = f"{prefix}{body[window_start:window_end]}{suffix}"
    if ending and len(trimmed) + len(ending) <= limit:
        trimmed += ending
    if len(trimmed) > limit:
        trimmed = trimmed[:limit]
    return trimmed, True


def list_directory_entries(path: Path) -> dict:
    """列出单层目录内容，供文件树懒加载使用。"""
    if not path.exists():
        return {"path": str(path), "exists": False, "entries": []}
    if not path.is_dir():
        return {"path": str(path), "exists": True, "entries": []}

    entries: list[dict] = []
    try:
        children = list(path.iterdir())
    except OSError as exc:
        return {"path": str(path), "exists": True, "error": str(exc), "entries": []}

    for child in children:
        try:
            is_dir = child.is_dir()
            is_file = child.is_file()
            if not is_dir and not is_file:
                continue
            size = 0 if is_dir else child.stat().st_size
            has_children = False
            if is_dir:
                try:
                    has_children = any(child.iterdir())
                except OSError:
                    has_children = False
        except OSError:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "is_dir": is_dir,
                "size": size,
                "has_children": has_children,
            }
        )
    entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
    return {"path": str(path), "exists": True, "entries": entries}


def read_text_window(
    path: Path,
    target_line: int,
    context_lines: int,
    max_chars: int,
    *,
    force_text: bool = False,
    match_start: int = 0,
    match_end: int = 0,
    match_text: str = "",
) -> dict:
    """在线程中读取目标行附近的文本窗口，避免大文件预览截断导致无法跳转。"""
    with path.open("rb") as file:
        sample = file.read(4096)
        binary = looks_binary(sample, force_text=force_text)
        encoding = detect_text_encoding(sample)
        if binary:
            return {
                "binary": True,
                "encoding": "hex",
                "text": sample[:4096].hex(" "),
                "line_base": 1,
                "truncated": True,
            }
        if not sample:
            return {
                "binary": False,
                "encoding": encoding,
                "text": "",
                "line_base": 1,
                "line_count": 0,
                "target_line": target_line,
                "truncated": False,
            }

        start_line = max(1, int(target_line) - max(0, int(context_lines)))
        end_line = max(start_line, int(target_line) + max(0, int(context_lines)))
        lines: list[str] = []
        char_count = 0
        reached_target = False
        truncated = False
        file.seek(0)
        with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mapped_file:
            line_number = 0
            while True:
                raw_line = mapped_file.readline()
                if not raw_line:
                    break
                line_number += 1
                if line_number < start_line:
                    continue
                if line_number > end_line:
                    break
                text = raw_line.decode(encoding, errors="replace")
                if line_number == target_line:
                    reached_target = True
                    remaining_chars = max(1, int(max_chars or 0) - char_count)
                    if len(text) > remaining_chars:
                        text, line_truncated = trim_line_around_match(
                            text,
                            remaining_chars,
                            match_start=match_start,
                            match_end=match_end,
                            match_text=match_text,
                        )
                        truncated = truncated or line_truncated
                if char_count + len(text) > max_chars:
                    truncated = True
                    break
                lines.append(text)
                char_count += len(text)
        return {
            "binary": False,
            "encoding": encoding,
            "text": "".join(lines),
            "line_base": start_line,
            "line_count": len(lines),
            "target_line": target_line,
            "truncated": truncated or not reached_target,
        }
