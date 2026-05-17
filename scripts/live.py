"""CLI for receiving live Motive/NatNet frames and broadcasting Heron JSON."""

from __future__ import annotations

import argparse
import socket
import sys
import time

from .natnet import (
    DEFAULT_COMMAND_PORT,
    DEFAULT_DATA_PORT,
    DEFAULT_MULTICAST_ADDRESS,
    DEFAULT_NATNET_VERSION,
    NatNetClient,
    NatNetError,
)
from .packet import (
    STATE_MOTIVE_OFF,
    STATE_NO_FRAME_DATA,
    STATE_STARTUP_ERROR,
    build_heron_packet,
    build_status_packet,
)
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
        "--heartbeat-interval",
        type=float,
        default=1.0,
        help="Seconds between status packets when Motive is unavailable.",
    )
    parser.add_argument(
        "--motive-timeout",
        type=float,
        default=2.0,
        help="Seconds without NatNet frames before broadcasting motive_off/no_frame_data.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=2.0,
        help="Seconds to wait before recreating NatNet sockets after a startup error.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Reduce console output for Task Scheduler/background operation.",
    )
    parser.add_argument(
        "--no-modeldef-request",
        action="store_true",
        help="Skip the startup request for Motive model definitions.",
    )
    return parser


def _last_frame_age_ms(last_frame_at: float | None) -> int | None:
    if last_frame_at is None:
        return None
    return int((time.monotonic() - last_frame_at) * 1000)


def _send_status(
    broadcaster: UdpJsonBroadcaster,
    args: argparse.Namespace,
    *,
    state: str,
    message: str,
    last_frame_at: float | None,
    last_frame_number: int | None,
    motive_reachable: bool | None = None,
) -> None:
    packet = build_status_packet(
        state=state,
        message=message,
        rigid_body_name=args.rigid_body,
        rigid_body_id=args.rigid_body_id,
        device=args.device,
        frame=last_frame_number,
        last_frame_age_ms=_last_frame_age_ms(last_frame_at),
        motive_reachable=motive_reachable,
    )
    broadcaster.send_packet(packet)


def run_live(args: argparse.Namespace) -> None:
    frame_count = 0
    last_frame_at: float | None = None
    last_frame_number: int | None = None
    last_status_at = 0.0
    motive_reachable = False

    with UdpJsonBroadcaster(args.broadcast_host, args.broadcast_port) as broadcaster:
        if not args.headless:
            print(
                f"Broadcasting {args.rigid_body} frames and status to "
                f"{args.broadcast_host}:{args.broadcast_port}..."
            )

        while True:
            try:
                with NatNetClient(
                    server_ip=args.server_ip,
                    local_ip=args.local_ip,
                    command_port=args.command_port,
                    data_port=args.data_port,
                    multicast_address=args.multicast_address,
                    connection_type=args.connection_type,
                    version=args.natnet_version,
                    timeout=min(args.heartbeat_interval, 1.0),
                ) as client:
                    if not args.no_modeldef_request:
                        model_defs = client.request_model_definitions(timeout=1.0)
                        motive_reachable = model_defs is not None
                        if model_defs and model_defs.rigid_body_names:
                            names = ", ".join(
                                f"{name}#{rigid_body_id}"
                                for rigid_body_id, name in sorted(model_defs.rigid_body_names.items())
                            )
                            if not args.headless:
                                print(f"Loaded Motive rigid bodies: {names}")
                        elif not args.headless:
                            print(
                                "No Motive model definitions received; waiting for frame data.",
                                file=sys.stderr,
                            )

                    while True:
                        frame = client.recv_frame()
                        now = time.monotonic()
                        if frame is None:
                            timed_out = last_frame_at is None or (now - last_frame_at) >= args.motive_timeout
                            if timed_out and (now - last_status_at) >= args.heartbeat_interval:
                                if motive_reachable:
                                    state = STATE_NO_FRAME_DATA
                                    message = (
                                        "Motive is reachable, but no NatNet frame data is being received. "
                                        "Check Broadcast Frame Data and Transmission Type in Motive."
                                    )
                                else:
                                    state = STATE_MOTIVE_OFF
                                    message = "No NatNet command or frame data is being received from Motive."
                                _send_status(
                                    broadcaster,
                                    args,
                                    state=state,
                                    message=message,
                                    last_frame_at=last_frame_at,
                                    last_frame_number=last_frame_number,
                                    motive_reachable=motive_reachable,
                                )
                                last_status_at = now
                                if not args.headless:
                                    print(f"\rstate={state} waiting for Motive frame data".ljust(120), end="", flush=True)
                            continue

                        last_frame_at = now
                        last_frame_number = frame.frame_number
                        packet = build_heron_packet(
                            frame,
                            rigid_body_name=args.rigid_body,
                            aliases=tuple(args.alias or ()),
                            rigid_body_id=args.rigid_body_id,
                            device=args.device,
                        )
                        broadcaster.send_packet(packet)
                        frame_count += 1
                        if frame_count % 30 == 0 and not args.headless:
                            status = packet["status"]
                            heron = packet["heron"]
                            print(
                                f"\rframe={packet['frame']} state={status['state']} "
                                f"tracking={heron['tracking_valid']} "
                                f"markers={len(heron['markers'])} "
                                f"potential={len(heron['potential_objects'])}".ljust(120),
                                end="",
                                flush=True,
                            )
            except (NatNetError, OSError) as exc:
                motive_reachable = False
                now = time.monotonic()
                if (now - last_status_at) >= args.heartbeat_interval:
                    _send_status(
                        broadcaster,
                        args,
                        state=STATE_STARTUP_ERROR,
                        message=f"NatNet startup error: {exc}",
                        last_frame_at=last_frame_at,
                        last_frame_number=last_frame_number,
                        motive_reachable=False,
                    )
                    last_status_at = now
                    if not args.headless:
                        print(
                            f"\rstate=startup_error retrying in {args.retry_delay:.1f}s: {exc}".ljust(120),
                            end="",
                            flush=True,
                        )
                time.sleep(args.retry_delay)


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    try:
        run_live(args)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
