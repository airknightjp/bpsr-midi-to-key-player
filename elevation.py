from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


SW_SHOWNORMAL = 1


def is_running_as_administrator() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _launch_command() -> tuple[str, list[str], str]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        arguments = list(sys.argv[1:])
        working_directory = executable.parent
    else:
        executable = Path(sys.executable).resolve()
        entry_point = Path(__file__).resolve().with_name("main.py")
        arguments = [str(entry_point), *sys.argv[1:]]
        working_directory = entry_point.parent
    return str(executable), arguments, str(working_directory)


def launch_as_administrator() -> bool:
    if os.name != "nt":
        return False
    executable, arguments, working_directory = _launch_command()
    parameters = subprocess.list2cmdline(arguments)
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            working_directory,
            SW_SHOWNORMAL,
        )
    except (AttributeError, OSError):
        return False
    return int(result) > 32


def relaunch_as_administrator_if_requested(requested: bool) -> bool:
    if not requested or is_running_as_administrator():
        return False
    return launch_as_administrator()
