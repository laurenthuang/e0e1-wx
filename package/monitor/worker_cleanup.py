"""在监控子进程中调度记录删除后的后台清理任务。"""

from __future__ import annotations

import asyncio

from package.cleanup import RecordCleanupRequest, cleanup_record_assets
from package.monitor.constants import DELETE_CLEANUP_MAX_CONCURRENCY


class MonitorCleanupMixin:
    """为监控 worker 提供后台删除清理调度能力。"""

    def ensure_cleanup_scheduler(self) -> None:
        """按需初始化后台删除任务集合和并发限制器。"""
        if not isinstance(getattr(self, "cleanup_tasks", None), set):
            self.cleanup_tasks: set[asyncio.Task] = set()
        if getattr(self, "cleanup_semaphore", None) is None:
            self.cleanup_semaphore = asyncio.Semaphore(DELETE_CLEANUP_MAX_CONCURRENCY)

    def schedule_record_cleanup(self, request: RecordCleanupRequest) -> None:
        """把一次记录删除清理提交到后台协程，不阻塞命令处理。"""
        self.ensure_cleanup_scheduler()
        task = asyncio.create_task(self.run_record_cleanup(request))
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.on_cleanup_task_done)

    async def run_record_cleanup(self, request: RecordCleanupRequest) -> None:
        """在受控并发下执行一次记录删除清理，并把结果发回 UI。"""
        self.ensure_cleanup_scheduler()
        async with self.cleanup_semaphore:
            result = await asyncio.to_thread(cleanup_record_assets, request)
        if result.deleted_output_dirs:
            self.emit({"type": "info", "message": f"已删除 {result.deleted_output_dirs} 个 output 输出目录。"})
        if result.deleted_cache_entries:
            self.emit({"type": "info", "message": f"已删除 {result.deleted_cache_entries} 个缓存条目。"})
        if result.deleted_packages_dirs:
            self.emit({"type": "info", "message": f"已删除 {result.deleted_packages_dirs} 个小程序包目录。"})
        for warning in result.warnings:
            self.emit({"type": "warning", "message": warning})

    def on_cleanup_task_done(self, task: asyncio.Task) -> None:
        """移除已结束的后台清理任务，并把异常转换为告警。"""
        if isinstance(getattr(self, "cleanup_tasks", None), set):
            self.cleanup_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.emit({"type": "warning", "message": f"后台删除清理失败：{exc}"})

    async def wait_for_cleanup_tasks(self) -> None:
        """等待当前已提交的后台清理任务全部结束。"""
        tasks = list(getattr(self, "cleanup_tasks", set()))
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown_cleanup_tasks(self) -> None:
        """停止监控 worker 前取消并回收后台删除清理任务。"""
        tasks = list(getattr(self, "cleanup_tasks", set()))
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(getattr(self, "cleanup_tasks", None), set):
            self.cleanup_tasks.clear()
