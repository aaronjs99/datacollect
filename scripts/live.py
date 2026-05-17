"""CLI for receiving live Motive/NatNet frames and broadcasting Heron JSON."""

from __future__ import annotations

import argparse
import socket
import sys

from .natnet import (
    DEFAULT_COMMAND_PORT,
    DEFAULT_DATA_PORT,
    DEFAULT_MULTICAST_ADDRESS,
    DEFAULT_NATNET_VERSION,
    NatNetClient,
    NatNetError,
)
from .packet import build_heron_packet
from .udp import UdpJsonBroadcaster


def _parse_version(value: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in value.split(".")]
    if not 1 <= len(parts) <= 4:
        raise argparse.ArgumentTypeError("NatNet version must look like 4.2 or 4.2.0.0")
    return tuple((parts + [0, 0, 0, 0])[:4])  # type: ignore[return-value]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Receive Motive/NatNet frames and broadcast Heron state as UDP JSON."
    )
    parser.add_argument("--server-ip", default="127.0.0.1", help="Motive/NatNet server IP.")
    parser.add_argument("--local-ip", help="Local interface IP for the NatNet client.")
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--data-port", type=int, default=DEFAULT_DATA_PORT)
    parser.add_argument("--multicast-address", default=DEFAULT_MULTICAST_ADDRESS)
    parser.add_argument(
        "--connection-type",
        choices=("multicast", "unicast", "broadcast"),
        default="multicast",
        help="How to receive Motive frame data.",
    )
    parser.add_argument("--natnet-version", type=_parse_version, default=DEFAULT_NATNET_VERSION)
    parser.add_argument("--rigid-body", default="Heron", help="Motive rigid body name to broadcast.")
    parser.add_argument(
        "--alias",
        action="append",
        default=["robot_link"],
        help="Additional rigid body name to accept; can be supplied more than once.",
    )
    parser.add_argument("--rigid-body-id", type=int, help="Fallback rigid body streaming ID.")
    parser.add_argument("--broadcast-host", default="255.255.255.255")
    parser.add_argument("--broadcast-port", type=int, default=5005)
    parser.add_argument("--device", default=socket.gethostname(), help="Device name included in packets.")
    parser.add_argument(
        "--no-modeldef-request",
        action="store_true",
        help="Skip the startup request for Motive model definitions.",
    )
    return parser


def run_live(args: argparse.Namespace) -> None:
    frame_count = 0
    with NatNetClient(
        server_ip=args.server_ip,
        local_ip=args.local_ip,
        command_port=args.command_port,
        data_port=args.data_port,
        multicast_address=args.multicast_address,
        connection_type=args.connection_type,
        version=args.natnet_version,
    ) as client, UdpJsonBroadcaster(args.broadcast_host, args.broadcast_port) as broadcaster:
        if not args.no_modeldef_request:
            model_defs = client.request_model_definitions(timeout=1.0)
            if model_defs and model_defs.rigid_body_names:
                names = ", ".join(
                    f"{name}#{rigid_body_id}"
                    for rigid_body_id, name in sorted(model_defs.rigid_body_names.items())
                )
                print(f"Loaded Motive rigid bodies: {names}")
            else:
                print(
                    "No Motive model definitions received; use --rigid-body-id if names are unavailable.",
                    file=sys.stderr,
                )

        print(
            f"Broadcasting {args.rigid_body} frames to "
            f"{args.broadcast_host}:{args.broadcast_port}..."
        )
        for frame in client.iter_frames():
            packet = build_heron_packet(
                frame,
                rigid_body_name=args.rigid_body,
                aliases=tuple(args.alias or ()),
                rigid_body_id=args.rigid_body_id,
                device=args.device,
            )
            broadcaster.send_packet(packet)
            frame_count += 1
            if frame_count % 30 == 0:
                heron = packet["heron"]
                print(
                    f"\rframe={packet['frame']} tracking={heron['tracking_valid']} "
                    f"markers={len(heron['markers'])} "
                    f"potential={len(heron['potential_objects'])}",
                    end="",
                    flush=True,
                )


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        run_live(args)
    except KeyboardInterrupt:
        print()
    except (NatNetError, OSError) as exc:
        raise SystemExit(f"Live Motive broadcaster failed: {exc}") from exc


if __name__ == "__main__":
    main()
