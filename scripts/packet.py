"""Heron UDP JSON packet schema helpers."""

from __future__ import annotations

import json
import math
import socket
import time
from typing import Any


SCHEMA = "datacollect.heron.v1"

STATE_OK = "ok"
STATE_MOTIVE_OFF = "motive_off"
STATE_OBJECT_NOT_FOUND = "object_not_found"
STATE_TRACKING_LOST = "tracking_lost"
STATE_STARTUP_ERROR = "startup_error"


class PacketValidationError(ValueError):
    """Raised when received JSON does not match the Heron packet contract."""


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_vector(values: Any, expected: int) -> bool:
    return isinstance(values, (tuple, list)) and len(values) == expected and all(
        _finite_number(value) for value in values
    )


def _position_dict(values: tuple[float, float, float]) -> dict[str, float]:
    return {"x": values[0], "y": values[1], "z": values[2]}


def _orientation_dict(values: tuple[float, float, float, float]) -> dict[str, float]:
    return {"x": values[0], "y": values[1], "z": values[2], "w": values[3]}


def _find_rigid_body(
    frame: Any,
    rigid_body_name: str,
    aliases: tuple[str, ...],
    rigid_body_id: int | None,
) -> Any | None:
    names = {rigid_body_name, *aliases}
    for rigid_body in getattr(frame, "rigid_bodies", []):
        if rigid_body_id is not None and getattr(rigid_body, "id", None) == rigid_body_id:
            return rigid_body
        if getattr(rigid_body, "name", None) in names:
            return rigid_body
    return None


def _status_dict(
    *,
    state: str,
    motive_receiving: bool,
    object_found: bool,
    tracking_valid: bool,
    heartbeat: bool,
    message: str | None = None,
    last_frame_age_ms: int | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "state": state,
        "flags": {
            "motive_receiving": motive_receiving,
            "object_found": object_found,
            "tracking_valid": tracking_valid,
            "heartbeat": heartbeat,
        },
        "message": message,
        "last_frame_age_ms": last_frame_age_ms,
    }
    return status


def _marker_label(marker: Any, body_name: str) -> str:
    label = getattr(marker, "label", None)
    if label:
        return label
    marker_id = getattr(marker, "marker_id", None)
    if marker_id is not None:
        return f"{body_name}:Marker {marker_id:03d}"
    marker_index = getattr(marker, "id", None)
    return f"{body_name}:Marker {marker_index}" if marker_index is not None else f"{body_name}:Marker"


def _collect_labeled_markers(frame: Any, rigid_body: Any | None, rigid_body_name: str) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    body_id = getattr(rigid_body, "id", None) if rigid_body is not None else None

    for marker in getattr(frame, "labeled_markers", []):
        position = getattr(marker, "position", None)
        if not _finite_vector(position, 3):
            continue
        label = getattr(marker, "label", None)
        model_id = getattr(marker, "model_id", None)
        belongs_to_body = body_id is not None and model_id == body_id
        belongs_by_label = isinstance(label, str) and label.startswith(f"{rigid_body_name}:Marker")
        if not (belongs_to_body or belongs_by_label):
            continue

        entry: dict[str, Any] = {
            "id": getattr(marker, "marker_id", getattr(marker, "id", None)),
            "label": _marker_label(marker, rigid_body_name),
            "position_m": _position_dict(tuple(position)),
        }
        size = getattr(marker, "size", None)
        residual = getattr(marker, "residual", None)
        if _finite_number(size):
            entry["size_m"] = size
        if _finite_number(residual):
            entry["residual"] = residual
        markers.append(entry)

    if markers:
        return markers

    for marker_set in getattr(frame, "marker_sets", []):
        if getattr(marker_set, "name", None) != rigid_body_name:
            continue
        for index, position in enumerate(getattr(marker_set, "markers", []), start=1):
            if not _finite_vector(position, 3):
                continue
            markers.append(
                {
                    "id": index,
                    "label": f"{rigid_body_name}:Marker {index:03d}",
                    "position_m": _position_dict(tuple(position)),
                }
            )
    return markers


def _collect_unlabeled_markers(frame: Any) -> list[dict[str, Any]]:
    potential_objects: list[dict[str, Any]] = []
    for index, marker in enumerate(getattr(frame, "unlabeled_markers", [])):
        position = getattr(marker, "position", None)
        if not _finite_vector(position, 3):
            continue
        entry: dict[str, Any] = {
            "id": getattr(marker, "id", index),
            "position_m": _position_dict(tuple(position)),
        }
        size = getattr(marker, "size", None)
        if _finite_number(size):
            entry["size_m"] = size
        potential_objects.append(entry)
    return potential_objects


def build_heron_packet(
    frame: Any,
    *,
    rigid_body_name: str = "Heron",
    aliases: tuple[str, ...] = ("robot_link",),
    rigid_body_id: int | None = None,
    device: str | None = None,
    received_at_unix_ns: int | None = None,
) -> dict[str, Any]:
    """Build the public Heron packet from a parsed Motive/NatNet frame."""

    rigid_body = _find_rigid_body(frame, rigid_body_name, aliases, rigid_body_id)
    object_found = rigid_body is not None
    tracking_valid = bool(rigid_body and getattr(rigid_body, "tracking_valid", False))

    rigid_body_packet: dict[str, Any] = {
        "name": getattr(rigid_body, "name", None) or rigid_body_name,
        "id": getattr(rigid_body, "id", rigid_body_id),
        "position_m": None,
        "orientation_xyzw": None,
    }

    if rigid_body is not None:
        position = getattr(rigid_body, "position", None)
        orientation = getattr(rigid_body, "orientation", None)
        if _finite_vector(position, 3):
            rigid_body_packet["position_m"] = _position_dict(tuple(position))
        else:
            tracking_valid = False
        if _finite_vector(orientation, 4):
            rigid_body_packet["orientation_xyzw"] = _orientation_dict(tuple(orientation))
        else:
            tracking_valid = False
        mean_error = getattr(rigid_body, "mean_error", None)
        if _finite_number(mean_error):
            rigid_body_packet["mean_error_m"] = mean_error

    if tracking_valid:
        state = STATE_OK
        message = "Heron rigid body is being tracked."
    elif object_found:
        state = STATE_TRACKING_LOST
        message = "Heron rigid body is present but not currently tracking."
    else:
        state = STATE_OBJECT_NOT_FOUND
        message = f"Rigid body {rigid_body_name!r} was not found in the latest Motive frame."

    return {
        "schema": SCHEMA,
        "device": device or socket.gethostname(),
        "frame": int(getattr(frame, "frame_number", 0)),
        "received_at_unix_ns": received_at_unix_ns if received_at_unix_ns is not None else time.time_ns(),
        "units": {"position": "m", "orientation": "quaternion_xyzw"},
        "status": _status_dict(
            state=state,
            motive_receiving=True,
            object_found=object_found,
            tracking_valid=tracking_valid,
            heartbeat=False,
            message=message,
        ),
        "heron": {
            "tracking_valid": tracking_valid,
            "rigid_body": rigid_body_packet,
            "markers": _collect_labeled_markers(frame, rigid_body, rigid_body_name),
            "potential_objects": _collect_unlabeled_markers(frame),
        },
    }


def build_status_packet(
    *,
    state: str,
    message: str,
    rigid_body_name: str = "Heron",
    rigid_body_id: int | None = None,
    device: str | None = None,
    frame: int | None = None,
    received_at_unix_ns: int | None = None,
    last_frame_age_ms: int | None = None,
) -> dict[str, Any]:
    motive_receiving = state not in {STATE_MOTIVE_OFF, STATE_STARTUP_ERROR}
    return {
        "schema": SCHEMA,
        "device": device or socket.gethostname(),
        "frame": frame,
        "received_at_unix_ns": received_at_unix_ns if received_at_unix_ns is not None else time.time_ns(),
        "units": {"position": "m", "orientation": "quaternion_xyzw"},
        "status": _status_dict(
            state=state,
            motive_receiving=motive_receiving,
            object_found=False,
            tracking_valid=False,
            heartbeat=True,
            message=message,
            last_frame_age_ms=last_frame_age_ms,
        ),
        "heron": {
            "tracking_valid": False,
            "rigid_body": {
                "name": rigid_body_name,
                "id": rigid_body_id,
                "position_m": None,
                "orientation_xyzw": None,
            },
            "markers": [],
            "potential_objects": [],
        },
    }


def validate_packet(packet: Any) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise PacketValidationError("Heron packet must be a JSON object")
    if packet.get("schema") != SCHEMA:
        raise PacketValidationError(f"Unsupported Heron packet schema: {packet.get('schema')!r}")

    heron = packet.get("heron")
    if not isinstance(heron, dict):
        raise PacketValidationError("Heron packet is missing the heron object")
    if not isinstance(heron.get("tracking_valid"), bool):
        raise PacketValidationError("heron.tracking_valid must be a boolean")
    if not isinstance(heron.get("rigid_body"), dict):
        raise PacketValidationError("heron.rigid_body must be an object")
    if not isinstance(heron.get("markers"), list):
        raise PacketValidationError("heron.markers must be a list")
    if not isinstance(heron.get("potential_objects"), list):
        raise PacketValidationError("heron.potential_objects must be a list")

    status = packet.get("status")
    if status is not None:
        if not isinstance(status, dict):
            raise PacketValidationError("status must be an object")
        if not isinstance(status.get("state"), str):
            raise PacketValidationError("status.state must be a string")
        if not isinstance(status.get("flags"), dict):
            raise PacketValidationError("status.flags must be an object")

    units = packet.get("units")
    if not isinstance(units, dict) or units.get("position") != "m":
        raise PacketValidationError("Heron packet position units must be meters")
    return packet


def decode_packet(data: bytes | str) -> dict[str, Any]:
    try:
        packet = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketValidationError(f"Invalid Heron JSON packet: {exc}") from exc
    return validate_packet(packet)


def encode_packet(packet: dict[str, Any]) -> bytes:
    validate_packet(packet)
    return json.dumps(packet, separators=(",", ":"), sort_keys=False).encode("utf-8")
