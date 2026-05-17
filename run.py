"""Root command dispatcher for the datacollect tools."""

from __future__ import annotations

import sys
from collections.abc import Callable
from importlib import import_module


CommandMain = Callable[[list[str] | None], None]

COMMANDS: dict[str, tuple[str, str, str]] = {
    "live": ("receive Motive/NatNet frames and broadcast Heron UDP JSON", "scripts.live", "main"),
    "receive": ("listen for Heron UDP JSON packets", "scripts.receiver", "main"),
    "plot": ("plot marker trajectories from an exported Motive CSV", "scripts.plot", "main"),
}


def _print_help() -> None:
    print("Usage: python run.py <command> [options]\n")
    print("Commands:")
    for name, (description, _, _) in COMMANDS.items():
        print(f"  {name:<8} {description}")
    print("\nExamples:")
    print("  python run.py live --server-ip 127.0.0.1 --rigid-body Heron")
    print("  python run.py receive --bind 0.0.0.0 --port 5005")
    print("  python run.py plot --file ./data/Heron_Test_01.csv --prefix Heron:Marker")
    print("\nCommand help:")
    print("  python run.py <command> --help")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        _print_help()
        return

    command = args.pop(0)
    try:
        _, module_name, function_name = COMMANDS[command]
    except KeyError as exc:
        valid = ", ".join(COMMANDS)
        raise SystemExit(f"Unknown command {command!r}. Valid commands: {valid}") from exc

    command_main: CommandMain = getattr(import_module(module_name), function_name)
    command_main(args)


if __name__ == "__main__":
    main()
