"""Small NatNet 4.x direct-depacketization client.

The parser focuses on the pieces this project needs: model definitions for
rigid-body names, rigid-body poses, labeled markers, and unlabeled markers.
It follows the layout used by OptiTrack's NatNet direct depacketization
samples while keeping the surface area intentionally narrow.
"""

from __future__ import annotations

import dataclasses
import socket
import struct
import time
from collections.abc import Callable, Iterator
from typing import Any


NAT_PING = 0
NAT_PINGRESPONSE = 1
NAT_REQUEST = 2
NAT_RESPONSE = 3
NAT_REQUEST_MODELDEF = 4
NAT_MODELDEF = 5
NAT_FRAMEOFDATA = 7

DEFAULT_COMMAND_PORT = 1510
DEFAULT_DATA_PORT = 1511
DEFAULT_MULTICAST_ADDRESS = "239.255.42.99"
DEFAULT_NATNET_VERSION = (4, 2, 0, 0)


class NatNetError(RuntimeError):
    """Raised when NatNet socket setup or parsing fails."""


class PacketParseError(NatNetError):
    """Raised when a NatNet packet cannot be parsed."""


@dataclasses.dataclass(frozen=True)
class MarkerSet:
    name: str
    markers: list[tuple[float, float, float]]


@dataclasses.dataclass(frozen=True)
class NatNetRigidBody:
    id: int
    name: str | None
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]
    tracking_valid: bool
    mean_error: float | None = None


@dataclasses.dataclass(frozen=True)
class NatNetMarker:
    id: int | None
    position: tuple[float, float, float]
    model_id: int | None = None
    marker_id: int | None = None
    label: str | None = None
    size: float | None = None
    params: int | None = None
    residual: float | None = None


@dataclasses.dataclass(frozen=True)
class NatNetFrame:
    frame_number: int
    rigid_bodies: list[NatNetRigidBody]
    labeled_markers: list[NatNetMarker]
    unlabeled_markers: list[NatNetMarker]
    marker_sets: list[MarkerSet] = dataclasses.field(default_factory=list)
    timestamp: float | None = None


@dataclasses.dataclass(frozen=True)
class NatNetModelDefinitions:
    rigid_body_names: dict[int, str]
    marker_set_names: dict[str, list[str]]


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def remaining(self) -> int:
        return len(self.data) - self.offset

    def read(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        if self.offset + size > len(self.data):
            raise PacketParseError("NatNet packet ended unexpectedly")
        values = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        return values[0] if len(values) == 1 else values

    def int32(self) -> int:
        return int(self.read("<i"))

    def uint32(self) -> int:
        return int(self.read("<I"))

    def uint64(self) -> int:
        return int(self.read("<Q"))

    def int16(self) -> int:
        return int(self.read("<h"))

    def float32(self) -> float:
        return float(self.read("<f"))

    def float64(self) -> float:
        return float(self.read("<d"))

    def vec3(self) -> tuple[float, float, float]:
        return (self.float32(), self.float32(), self.float32())

    def quat(self) -> tuple[float, float, float, float]:
        return (self.float32(), self.float32(), self.float32(), self.float32())

    def string(self) -> str:
        if self.offset >= len(self.data):
            raise PacketParseError("NatNet string started past packet end")

        if self.remaining() >= 4:
            possible_length = struct.unpack_from("<I", self.data, self.offset)[0]
            if 0 < possible_length <= self.remaining() - 4 and possible_length < 4096:
                start = self.offset + 4
                end = start + possible_length
                raw = self.data[start:end]
                if raw:
                    self.offset = end
                    return raw.rstrip(b"\0").decode("utf-8", errors="replace")

        end = self.data.find(b"\0", self.offset)
        if end == -1:
            raise PacketParseError("NatNet string was not null terminated")
        raw = self.data[self.offset:end]
        self.offset = end + 1
        return raw.decode("utf-8", errors="replace")

    def skip(self, size: int) -> None:
        if size < 0 or self.offset + size > len(self.data):
            raise PacketParseError("NatNet skip moved past packet end")
        self.offset += size


def _version_at_least(version: tuple[int, int, int, int], major: int, minor: int = 0) -> bool:
    return version[:2] >= (major, minor)


def _bundle_end(reader: _Reader, version: tuple[int, int, int, int]) -> int | None:
    if not _version_at_least(version, 4, 1):
        return None
    size = reader.int32()
    end = reader.offset + size
    if size < 0 or end > len(reader.data):
        raise PacketParseError("NatNet bundle size moved past packet end")
    return end


def _finish_bundle(reader: _Reader, end: int | None) -> None:
    if end is not None:
        reader.offset = end


def _read_rigid_body(
    reader: _Reader,
    version: tuple[int, int, int, int],
    names: dict[int, str],
) -> NatNetRigidBody:
    rigid_body_id = reader.int32()
    position = reader.vec3()
    orientation = reader.quat()

    if not _version_at_least(version, 3, 0):
        marker_count = reader.int32()
        reader.skip(marker_count * 3 * 4)
        reader.skip(marker_count * 4)
        reader.skip(marker_count * 4)

    mean_error = reader.float32() if _version_at_least(version, 2, 0) else None
    params = reader.int16() if _version_at_least(version, 2, 6) else 1
    tracking_valid = bool(params & 0x01)

    return NatNetRigidBody(
        id=rigid_body_id,
        name=names.get(rigid_body_id),
        position=position,
        orientation=orientation,
        tracking_valid=tracking_valid,
        mean_error=mean_error,
    )


def _decode_marker_id(marker_id: int) -> tuple[int, int]:
    return ((marker_id >> 16) & 0xFFFF, marker_id & 0xFFFF)


def _read_labeled_marker(
    reader: _Reader,
    version: tuple[int, int, int, int],
    names: dict[int, str],
) -> NatNetMarker:
    packed_id = reader.int32()
    position = reader.vec3()
    size = reader.float32()
    params = reader.int16() if _version_at_least(version, 2, 6) else None
    residual = reader.float32() if _version_at_least(version, 3, 0) else None
    model_id, marker_id = _decode_marker_id(packed_id)
    model_name = names.get(model_id)
    label = f"{model_name}:Marker {marker_id:03d}" if model_name else None
    return NatNetMarker(
        id=packed_id,
        position=position,
        model_id=model_id,
        marker_id=marker_id,
        label=label,
        size=size,
        params=params,
        residual=residual,
    )


def parse_frame_packet(
    payload: bytes,
    *,
    version: tuple[int, int, int, int] = DEFAULT_NATNET_VERSION,
    rigid_body_names: dict[int, str] | None = None,
) -> NatNetFrame:
    names = rigid_body_names or {}
    reader = _Reader(payload)
    frame_number = reader.int32()

    marker_sets: list[MarkerSet] = []
    marker_set_count = reader.int32()
    marker_set_end = _bundle_end(reader, version)
    for _ in range(marker_set_count):
        name = reader.string()
        marker_count = reader.int32()
        marker_sets.append(MarkerSet(name=name, markers=[reader.vec3() for _ in range(marker_count)]))
    _finish_bundle(reader, marker_set_end)

    unlabeled_count = reader.int32()
    unlabeled_end = _bundle_end(reader, version)
    unlabeled_markers = [
        NatNetMarker(id=index, position=reader.vec3(), label=f"Unlabeled {index}")
        for index in range(unlabeled_count)
    ]
    _finish_bundle(reader, unlabeled_end)

    rigid_body_count = reader.int32()
    rigid_body_end = _bundle_end(reader, version)
    rigid_bodies = [_read_rigid_body(reader, version, names) for _ in range(rigid_body_count)]
    _finish_bundle(reader, rigid_body_end)

    if _version_at_least(version, 2, 1):
        skeleton_count = reader.int32()
        skeleton_end = _bundle_end(reader, version)
        for _ in range(skeleton_count):
            reader.int32()
            skeleton_rigid_body_count = reader.int32()
            for _ in range(skeleton_rigid_body_count):
                _read_rigid_body(reader, version, names)
        _finish_bundle(reader, skeleton_end)

    labeled_markers: list[NatNetMarker] = []
    if _version_at_least(version, 2, 3):
        labeled_marker_count = reader.int32()
        labeled_marker_end = _bundle_end(reader, version)
        labeled_markers = [
            _read_labeled_marker(reader, version, names) for _ in range(labeled_marker_count)
        ]
        _finish_bundle(reader, labeled_marker_end)

    timestamp: float | None = None
    try:
        if _version_at_least(version, 2, 9):
            force_plate_count = reader.int32()
            force_plate_end = _bundle_end(reader, version)
            for _ in range(force_plate_count):
                _skip_device_like_data(reader)
            _finish_bundle(reader, force_plate_end)

        if _version_at_least(version, 3, 0):
            device_count = reader.int32()
            device_end = _bundle_end(reader, version)
            for _ in range(device_count):
                _skip_device_like_data(reader)
            _finish_bundle(reader, device_end)

        if _version_at_least(version, 4, 1) and reader.remaining() >= 4:
            asset_count = reader.int32()
            asset_end = _bundle_end(reader, version)
            for _ in range(asset_count):
                _skip_asset_data(reader, version)
            _finish_bundle(reader, asset_end)

        if reader.remaining() >= 8:
            reader.uint32()
            reader.uint32()
        if reader.remaining() >= 8:
            timestamp = reader.float64() if _version_at_least(version, 2, 7) else reader.float32()
        if _version_at_least(version, 3, 0):
            if reader.remaining() >= 8:
                reader.uint64()
            if reader.remaining() >= 8:
                reader.uint64()
            if reader.remaining() >= 8:
                reader.uint64()
    except PacketParseError:
        timestamp = None

    return NatNetFrame(
        frame_number=frame_number,
        rigid_bodies=rigid_bodies,
        labeled_markers=labeled_markers,
        unlabeled_markers=unlabeled_markers,
        marker_sets=marker_sets,
        timestamp=timestamp,
    )


def _skip_device_like_data(reader: _Reader) -> None:
    reader.int32()
    channel_count = reader.int32()
    for _ in range(channel_count):
        frame_count = reader.int32()
        reader.skip(frame_count * 4)


def _skip_asset_data(reader: _Reader, version: tuple[int, int, int, int]) -> None:
    reader.int32()
    rigid_body_count = reader.int32()
    for _ in range(rigid_body_count):
        _read_rigid_body(reader, version, {})
    marker_count = reader.int32()
    for _ in range(marker_count):
        _read_labeled_marker(reader, version, {})


def _read_rigid_body_description(
    reader: _Reader,
    version: tuple[int, int, int, int],
) -> tuple[int, str]:
    if _version_at_least(version, 4, 0):
        rigid_body_id = reader.int32()
        name = reader.string()
        reader.int32()
        reader.int32()
        reader.skip(7 * 4)
    else:
        name = reader.string() if _version_at_least(version, 2, 0) else ""
        rigid_body_id = reader.int32()
        reader.int32()
        reader.vec3()

    if _version_at_least(version, 3, 0) and reader.remaining() >= 4:
        marker_count = reader.int32()
        if 0 <= marker_count <= 10000:
            reader.skip(marker_count * 3 * 4)
            reader.skip(marker_count * 4)
            if _version_at_least(version, 4, 0):
                for _ in range(marker_count):
                    reader.string()
    return rigid_body_id, name


def parse_modeldef_packet(
    payload: bytes,
    *,
    version: tuple[int, int, int, int] = DEFAULT_NATNET_VERSION,
) -> NatNetModelDefinitions:
    reader = _Reader(payload)
    rigid_body_names: dict[int, str] = {}
    marker_set_names: dict[str, list[str]] = {}
    dataset_count = reader.int32()

    for _ in range(dataset_count):
        if reader.remaining() < 4:
            break
        dataset_type = reader.int32()
        dataset_end = _bundle_end(reader, version)
        try:
            if dataset_type == 0:
                name = reader.string()
                marker_count = reader.int32()
                marker_set_names[name] = [reader.string() for _ in range(marker_count)]
            elif dataset_type == 1:
                if dataset_end is not None:
                    name = reader.string()
                    rigid_body_id = reader.int32()
                else:
                    rigid_body_id, name = _read_rigid_body_description(reader, version)
                if name:
                    rigid_body_names[rigid_body_id] = name
            elif dataset_type == 2:
                reader.string()
                reader.int32()
                if dataset_end is None:
                    rigid_body_count = reader.int32()
                    for _ in range(rigid_body_count):
                        rigid_body_id, name = _read_rigid_body_description(reader, version)
                        if name:
                            rigid_body_names[rigid_body_id] = name
            elif dataset_type == 3:
                _skip_force_plate_description(reader)
            elif dataset_type == 4:
                _skip_device_description(reader)
            elif dataset_type == 5:
                _skip_camera_description(reader)
            else:
                break
        finally:
            _finish_bundle(reader, dataset_end)

    return NatNetModelDefinitions(
        rigid_body_names=rigid_body_names,
        marker_set_names=marker_set_names,
    )


def _skip_force_plate_description(reader: _Reader) -> None:
    reader.int32()
    reader.string()
    reader.float32()
    reader.float32()
    reader.vec3()
    reader.skip(12 * 12 * 4)
    reader.skip(4 * 3 * 4)
    reader.int32()
    reader.int32()
    channel_count = reader.int32()
    for _ in range(channel_count):
        reader.string()


def _skip_device_description(reader: _Reader) -> None:
    reader.int32()
    reader.string()
    reader.string()
    reader.int32()
    reader.int32()
    channel_count = reader.int32()
    for _ in range(channel_count):
        reader.string()


def _skip_camera_description(reader: _Reader) -> None:
    reader.string()
    reader.vec3()
    reader.quat()


def pack_natnet_message(message_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HH", message_id, len(payload)) + payload


def parse_natnet_message(
    data: bytes,
    *,
    version: tuple[int, int, int, int] = DEFAULT_NATNET_VERSION,
    rigid_body_names: dict[int, str] | None = None,
) -> tuple[int, NatNetFrame | NatNetModelDefinitions | bytes]:
    if len(data) < 4:
        raise PacketParseError("NatNet packet is shorter than the message header")
    message_id, payload_size = struct.unpack_from("<HH", data, 0)
    payload = data[4 : 4 + payload_size]
    if len(payload) != payload_size:
        raise PacketParseError("NatNet packet payload length did not match header")

    if message_id == NAT_FRAMEOFDATA:
        return message_id, parse_frame_packet(
            payload,
            version=version,
            rigid_body_names=rigid_body_names,
        )
    if message_id == NAT_MODELDEF:
        return message_id, parse_modeldef_packet(payload, version=version)
    return message_id, payload


def guess_local_ip(server_ip: str) -> str:
    if server_ip in {"127.0.0.1", "localhost"}:
        return "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((server_ip, DEFAULT_COMMAND_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()


class NatNetClient:
    """Receive NatNet frames from Motive using UDP sockets."""

    def __init__(
        self,
        *,
        server_ip: str = "127.0.0.1",
        local_ip: str | None = None,
        command_port: int = DEFAULT_COMMAND_PORT,
        data_port: int = DEFAULT_DATA_PORT,
        multicast_address: str = DEFAULT_MULTICAST_ADDRESS,
        connection_type: str = "multicast",
        version: tuple[int, int, int, int] = DEFAULT_NATNET_VERSION,
        timeout: float | None = 1.0,
    ) -> None:
        self.server_ip = server_ip
        self.local_ip = local_ip or guess_local_ip(server_ip)
        self.command_port = command_port
        self.data_port = data_port
        self.multicast_address = multicast_address
        self.connection_type = connection_type
        self.version = version
        self.timeout = timeout
        self.command_socket: socket.socket | None = None
        self.data_socket: socket.socket | None = None
        self.rigid_body_names: dict[int, str] = {}

    def __enter__(self) -> NatNetClient:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def open(self) -> None:
        self.command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.command_socket.settimeout(self.timeout)
        self.command_socket.bind((self.local_ip, 0))

        self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.data_socket.settimeout(self.timeout)

        if self.connection_type == "multicast":
            self.data_socket.bind(("", self.data_port))
            membership = socket.inet_aton(self.multicast_address) + socket.inet_aton(self.local_ip)
            self.data_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        elif self.connection_type == "broadcast":
            self.data_socket.bind(("", self.data_port))
        elif self.connection_type == "unicast":
            self.data_socket.bind((self.local_ip, self.data_port))
        else:
            raise NatNetError(f"Unsupported NatNet connection type: {self.connection_type}")

    def close(self) -> None:
        for sock in (self.data_socket, self.command_socket):
            if sock is not None:
                sock.close()
        self.data_socket = None
        self.command_socket = None

    def request_model_definitions(self, timeout: float = 1.0) -> NatNetModelDefinitions | None:
        if self.command_socket is None:
            raise NatNetError("NatNetClient.open() must be called before requesting model definitions")

        request = pack_natnet_message(NAT_REQUEST_MODELDEF)
        self.command_socket.sendto(request, (self.server_ip, self.command_port))
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                data, _ = self.command_socket.recvfrom(65535)
            except TimeoutError:
                continue
            except socket.timeout:
                continue
            message_id, message = parse_natnet_message(
                data,
                version=self.version,
                rigid_body_names=self.rigid_body_names,
            )
            if message_id == NAT_MODELDEF and isinstance(message, NatNetModelDefinitions):
                self.rigid_body_names.update(message.rigid_body_names)
                return message
        return None

    def iter_frames(self) -> Iterator[NatNetFrame]:
        if self.data_socket is None:
            raise NatNetError("NatNetClient.open() must be called before receiving frames")

        while True:
            frame = self.recv_frame()
            if frame is not None:
                yield frame

    def recv_frame(self) -> NatNetFrame | None:
        if self.data_socket is None:
            raise NatNetError("NatNetClient.open() must be called before receiving frames")

        try:
            data, _ = self.data_socket.recvfrom(65535)
        except TimeoutError:
            return None
        except socket.timeout:
            return None

        message_id, message = parse_natnet_message(
            data,
            version=self.version,
            rigid_body_names=self.rigid_body_names,
        )
        if message_id == NAT_MODELDEF and isinstance(message, NatNetModelDefinitions):
            self.rigid_body_names.update(message.rigid_body_names)
        elif message_id == NAT_FRAMEOFDATA and isinstance(message, NatNetFrame):
            return message
        return None

    def listen(self, callback: Callable[[NatNetFrame], None]) -> None:
        for frame in self.iter_frames():
            callback(frame)
