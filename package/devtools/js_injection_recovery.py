"""集中处理长期 JS 脚本 runtime 重建后的自动恢复判定。"""

from __future__ import annotations

from package.js_injection.models import is_runtime_toggle_script


def should_auto_restore_runtime_toggle(state: dict) -> bool:
    """判断单个长期脚本状态是否具备自动恢复资格。"""
    return bool(
        isinstance(state, dict)
        and is_runtime_toggle_script(state)
        and state.get("auto_restore")
        and isinstance(state.get("script"), dict)
        and str(state.get("script_id") or "").strip()
    )


def build_auto_restore_candidates(states_by_record: dict[int, dict[str, dict]], *, owner_key: str, record_id: int) -> list[dict]:
    """筛出当前会话下需要在新 runtime 就绪后恢复的长期脚本。"""
    candidates: list[dict] = []
    target_record_id = int(record_id or 0)
    target_owner_key = str(owner_key or "").strip()
    for current_record_id, states in dict(states_by_record or {}).items():
        if int(current_record_id or 0) != target_record_id or not isinstance(states, dict):
            continue
        for script_id, state in states.items():
            if not should_auto_restore_runtime_toggle(state):
                continue
            if str(state.get("owner_key") or "").strip() != target_owner_key:
                continue
            candidates.append(
                {
                    "script_id": str(script_id or state.get("script_id") or "").strip(),
                    "script": dict(state.get("script") or {}),
                    "record_id": target_record_id,
                    "owner_key": target_owner_key,
                }
            )
    return candidates
