"""提供反编译 worker 内部使用的受限并发调度与执行池封装。"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Awaitable, Callable

from package.decompiler.core import decompile_wxapkg_file


async def run_bounded_jobs(
    jobs: list,
    *,
    limit: int,
    run_job: Callable[[object], Awaitable[object]],
    is_cancelled: Callable[[], bool],
) -> list:
    """按固定并发上限执行任务，并在取消后停止启动新任务。"""
    semaphore = asyncio.Semaphore(max(1, int(limit or 1)))
    results: list[object | None] = [None] * len(jobs)

    async def wrapped(index: int, job: object) -> None:
        """包装单个任务，统一处理并发限制与取消检查。"""
        if is_cancelled():
            return
        async with semaphore:
            if is_cancelled():
                return
            results[index] = await run_job(job)

    tasks = [asyncio.create_task(wrapped(index, job)) for index, job in enumerate(jobs)]
    await asyncio.gather(*tasks)
    return [item for item in results if item is not None]


def _decompile_one_job(job: dict) -> dict:
    """在子进程中执行单个 wxapkg 反编译任务并返回结构化结果。"""
    source_dir = Path(str(job.get("source_dir") or ""))
    output_dir = Path(str(job.get("output_dir") or ""))
    wxapkg_path = Path(str(job.get("wxapkg_path") or ""))
    new_folder = str(job.get("new_folder") or "")
    try:
        result = decompile_wxapkg_file(
            source_dir,
            output_dir,
            wxapkg_path,
            new_folder,
            None,
            None,
        )
        return {
            "new_folder": new_folder,
            "wxapkg_path": str(wxapkg_path),
            "output_dir": str(result.get("output_dir") or output_dir),
            "file_count": int(result.get("file_count") or 0),
            "ok": True,
            "error": "",
        }
    except Exception as exc:
        return {
            "new_folder": new_folder,
            "wxapkg_path": str(wxapkg_path),
            "output_dir": str(output_dir),
            "file_count": 0,
            "ok": False,
            "error": str(exc),
        }


async def run_decompile_jobs(
    *,
    jobs: list[dict],
    max_workers: int,
    is_cancelled: Callable[[], bool],
    loop: asyncio.AbstractEventLoop | None = None,
) -> list[dict]:
    """在独立反编译 worker 内并发执行多个 wxapkg 任务，并限制最大并发。"""
    current_loop = loop or asyncio.get_running_loop()
    worker_limit = max(1, min(int(max_workers or 1), os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="decompile-job") as executor:

        async def run_job(job: dict) -> dict:
            """把单个反编译任务提交给 worker 内共享执行池。"""
            return await current_loop.run_in_executor(executor, _decompile_one_job, job)

        return [
            dict(item)
            for item in await run_bounded_jobs(
                jobs,
                limit=worker_limit,
                run_job=run_job,
                is_cancelled=is_cancelled,
            )
            if isinstance(item, dict)
        ]
