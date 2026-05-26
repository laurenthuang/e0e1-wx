"""Configure process startup behavior before GUI modules are imported."""

from __future__ import annotations

import multiprocessing as mp
import sys
from pathlib import Path


def pythonw_child_executable() -> Path | None:
    """Return pythonw.exe for Windows source-mode child processes when available."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return None

    current_executable = Path(sys.executable)
    if current_executable.name.casefold() == "pythonw.exe":
        return None

    candidate = current_executable.with_name("pythonw.exe")
    if candidate.exists():
        return candidate
    return None


def configure_multiprocessing_for_gui_subprocesses() -> bool:
    """Use a windowless Python executable for multiprocessing children in source mode."""
    child_executable = pythonw_child_executable()
    if child_executable is None:
        return False
    mp.set_executable(str(child_executable))
    return True
