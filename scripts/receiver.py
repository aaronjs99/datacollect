"""Reusable Heron packet receiver and CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .packet import PacketValidationError
from .udp import UdpHeronReceiver


def format_status(packet: dict, address: tuple[str, int] | None = None) -> str:
    heron = packet["heron"]
    rigid_body = heron["rigid_body"]
    source = f" from {address[0]}:{address[1]}" if address else ""
    marker_count = len(heron["markers"])
    potential_count = len(heron["potential_objects"])

    if not heron["tracking_valid"] or rigid_body.get("position_m") is None:
        return (
            f"frame={packet.get('frame')} Heron LOST "
            f"markers={marker_count} potential={potential_count}{source}"
        )

    position = rigid_body["position_m"]
    return (
        f"frame={packet.get('frame')} Heron "
        f"x={position['x']:.4f} y={position['y']:.4f} z={position['z']:.4f} "
        f"markers={marker_count} potential={potential_count}{source}"
    )


def run_receiver(
    *,
    bind: str = "0.0.0.0",
    port: int = 5005,
    jsonl: str | None = None,
    print_invalid: bool = True,
) -> None:
    jsonl_handle = None
    if jsonl:
        jsonl_path = Path(jsonl)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handle = jsonl_path.open("a", encoding="utf-8")

    try:
        with UdpHeronReceiver(bind=bind, port=port) as receiver:
            print(f"Listening for {bind}:{receiver.port} Heron UDP JSON packets...")
            while True:
                try:
                    packet, address = receiver.recv_packet()
                except PacketValidationError as exc:
                    if print_invalid:
                        print(f"\nIgnoring invalid packet: {exc}", file=sys.stderr)
                    continue

                if jsonl_handle is not None:
                    jsonl_handle.write(json.dumps(packet, separators=(",", ":")) + "\n")
                    jsonl_handle.flush()

                status = format_status(packet, address)
                print("\r" + status.ljust(120), end="", flush=True)
    except KeyboardInterrupt:
        print()
    finally:
        if jsonl_handle is not None:
            jsonl_handle.close()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Receive Heron UDP JSON broadcast packets.")
    parser.add_argument("--bind", default="0.0.0.0", help="Local interface to bind.")
    parser.add_argument("--port", type=int, default=5005, help="UDP port to listen on.")
    parser.add_argument("--jsonl", help="Optional JSONL file to append every valid packet to.")
    parser.add_argument(
        "--quiet-invalid",
        action="store_true",
        help="Suppress invalid packet warnings.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    run_receiver(
        bind=args.bind,
        port=args.port,
        jsonl=args.jsonl,
        print_invalid=not args.quiet_invalid,
    )
