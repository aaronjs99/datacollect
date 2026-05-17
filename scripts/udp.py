"""UDP helpers for Heron JSON packets."""

from __future__ import annotations

import socket
from typing import Any

from .packet import decode_packet, encode_packet


class UdpJsonBroadcaster:
    def __init__(self, host: str = "255.255.255.255", port: int = 5005) -> None:
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def close(self) -> None:
        self.socket.close()

    def __enter__(self) -> UdpJsonBroadcaster:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def send_packet(self, packet: dict[str, Any]) -> int:
        return self.socket.sendto(encode_packet(packet), (self.host, self.port))


class UdpHeronReceiver:
    def __init__(self, bind: str = "0.0.0.0", port: int = 5005, timeout: float | None = None) -> None:
        self.bind = bind
        self.requested_port = port
        self.timeout = timeout
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.settimeout(timeout)
        self.socket.bind((bind, port))
        self.port = self.socket.getsockname()[1]
        self.latest_packet: dict[str, Any] | None = None

    def close(self) -> None:
        self.socket.close()

    def __enter__(self) -> UdpHeronReceiver:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def recv_packet(self, timeout: float | None = None) -> tuple[dict[str, Any], tuple[str, int]]:
        previous_timeout = self.socket.gettimeout()
        if timeout is not None:
            self.socket.settimeout(timeout)
        try:
            data, address = self.socket.recvfrom(65535)
        finally:
            if timeout is not None:
                self.socket.settimeout(previous_timeout)
        packet = decode_packet(data)
        self.latest_packet = packet
        return packet, address
