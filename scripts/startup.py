"""Windows startup task installer for the Heron broadcaster."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_TASK_NAME = "DataCollectHeronBroadcaster"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _runtime_dir() -> Path:
    path = _repo_root() / ".runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _launcher_path() -> Path:
    return _runtime_dir() / "start_heron_broadcaster.cmd"


def _startup_folder_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set; cannot locate the Windows Startup folder.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_shortcut_path(task_name: str) -> Path:
    return _startup_folder_path() / f"{task_name}.cmd"


def build_launcher(
    *,
    python_exe: str,
    live_args: list[str],
) -> Path:
    root = _repo_root()
    launcher = _launcher_path()
    log_path = _runtime_dir() / "heron_broadcaster.log"
    command = subprocess.list2cmdline(
        [python_exe, str(root / "run.py"), "live", "--headless", *live_args]
    )
    launcher.write_text(
        "\n".join(
            [
                "@echo off",
                f'cd /d "{root}"',
                f"{command} >> \"{log_path}\" 2>&1",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return launcher


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["schtasks", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def install_task(
    *,
    task_name: str = DEFAULT_TASK_NAME,
    trigger: str = "boot",
    python_exe: str = sys.executable,
    live_args: list[str] | None = None,
) -> None:
    launcher = build_launcher(python_exe=python_exe, live_args=live_args or [])
    if trigger == "startup-folder":
        shortcut = _startup_shortcut_path(task_name)
        shortcut.write_text(
            "\n".join(["@echo off", f'call "{launcher}"', ""]),
            encoding="utf-8",
        )
        print(f"Installed {task_name!r} in the current user's Windows Startup folder.")
        print(f"Startup entry: {shortcut}")
        print(f"Launcher: {launcher}")
        return

    schedule = "ONSTART" if trigger == "boot" else "ONLOGON"
    result = _run_schtasks(
        [
            "/Create",
            "/TN",
            task_name,
            "/TR",
            f'"{launcher}"',
            "/SC",
            schedule,
            "/F",
        ]
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Failed to install startup task.\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )
    print(f"Installed {task_name!r} as a Windows {schedule} scheduled task.")
    print(f"Launcher: {launcher}")


def uninstall_task(task_name: str = DEFAULT_TASK_NAME) -> None:
    shortcut = _startup_shortcut_path(task_name)
    if shortcut.exists():
        shortcut.unlink()
        print(f"Removed Startup folder entry {shortcut}.")

    result = _run_schtasks(["/Delete", "/TN", task_name, "/F"])
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        if "cannot find" in message.lower() or "does not exist" in message.lower():
            print(f"No Windows scheduled task named {task_name!r} was found.")
            return
        raise SystemExit(f"Failed to uninstall startup task.\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
    print(f"Removed Windows scheduled task {task_name!r}.")


def show_status(task_name: str = DEFAULT_TASK_NAME) -> None:
    shortcut = _startup_shortcut_path(task_name)
    if shortcut.exists():
        print(f"Startup folder entry: {shortcut}")
    else:
        print("Startup folder entry: not installed")

    result = _run_schtasks(["/Query", "/TN", task_name, "/V", "/FO", "LIST"])
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        if shortcut.exists():
            print("Scheduled task: not installed")
            return
        if output:
            print(output)
    elif output:
        print(output)
    raise SystemExit(result.returncode)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install/remove the Heron broadcaster as a Windows background startup task."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    install = subparsers.add_parser("install", help="Create or replace the startup task.")
    install.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    install.add_argument(
        "--trigger",
        choices=("boot", "logon", "startup-folder"),
        default="boot",
        help="boot/logon use Task Scheduler; startup-folder writes a no-admin current-user launcher.",
    )
    install.add_argument("--python", default=sys.executable, help="Python executable for the task.")
    install.add_argument(
        "live_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to 'python run.py live' after a '--' separator.",
    )

    uninstall = subparsers.add_parser("uninstall", help="Delete the startup task.")
    uninstall.add_argument("--task-name", default=DEFAULT_TASK_NAME)

    status = subparsers.add_parser("status", help="Show the scheduled task status.")
    status.add_argument("--task-name", default=DEFAULT_TASK_NAME)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    if args.action == "install":
        live_args = list(args.live_args)
        if live_args and live_args[0] == "--":
            live_args = live_args[1:]
        install_task(
            task_name=args.task_name,
            trigger=args.trigger,
            python_exe=args.python,
            live_args=live_args,
        )
    elif args.action == "uninstall":
        uninstall_task(task_name=args.task_name)
    elif args.action == "status":
        show_status(task_name=args.task_name)


if __name__ == "__main__":
    main()
