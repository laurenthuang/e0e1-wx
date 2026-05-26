"""记录主线程关键路径耗时，便于观察卡顿回归。"""

from __future__ import annotations


class UiLatencyTracker:
    """统计 UI 关键路径的执行次数和最慢耗时。"""

    def __init__(self, threshold_ms: float = 50.0) -> None:
        """初始化阈值和统计容器。"""
        self.threshold_ms = float(threshold_ms)
        self._stats: dict[str, dict[str, float | int]] = {}

    def record(self, name: str, duration_ms: float) -> None:
        """记录一次 UI 操作耗时。"""
        stats = self._stats.setdefault(name, {"count": 0, "slow_count": 0, "max_ms": 0.0})
        stats["count"] = int(stats["count"]) + 1
        stats["max_ms"] = max(float(stats["max_ms"]), float(duration_ms))
        if duration_ms >= self.threshold_ms:
            stats["slow_count"] = int(stats["slow_count"]) + 1

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """返回当前统计快照。"""
        return {key: dict(value) for key, value in self._stats.items()}
