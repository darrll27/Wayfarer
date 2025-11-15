"""Simple MAVLink v2 encoder helpers.

We support encoding COMMAND_LONG and a minimal detector for MAVLink v2 packets.
This module uses pymavlink to construct messages and writes them into an
in-memory buffer, returning the packed bytes.

The encoder focuses on MAVLink v2; if the environment or incoming packets are
not v2, callers should use `is_mavlink2_packet` to detect and optionally warn.
"""
from __future__ import annotations

import io
import warnings
from typing import Sequence

from pymavlink import mavutil


def is_mavlink2_packet(data: bytes) -> bool:
    """Return True if the given packet bytes look like MAVLink v2 (0xFD start).

    This is a lightweight detector — it checks only the magic prefix byte.
    """
    if not data:
        return False
    return data[0] == 0xFD


def _make_mavlink_writer(src_sys: int | None = None, src_comp: int | None = None):
    """Create an in-memory MAVLink writer (MAVLink instance that writes into BytesIO).

    We attempt to prefer MAVLink v2 packing when possible by setting attributes
    on the MAVLink instance. If pymavlink doesn't expose those attributes, we
    still return a working writer; callers should still detect the produced
    packet type if they depend on strict v2 behavior.
    """
    buf = io.BytesIO()
    mav = mavutil.mavlink.MAVLink(buf)
    # Try to hint at MAVLink v2 when supported
    try:
        # some pymavlink versions support a protocol_version/ mavlink20 attribute
        setattr(mav, "protocol_version", 2)
    except Exception:
        try:
            setattr(mav, "mavlink20", True)
        except Exception:
            pass
    # Set source system/component if provided
    if src_sys is not None:
        try:
            setattr(mav, 'srcSystem', int(src_sys))
        except Exception:
            pass
    if src_comp is not None:
        try:
            setattr(mav, 'srcComponent', int(src_comp))
        except Exception:
            pass
    return mav, buf


def encode_heartbeat(src_sys: int, src_comp: int, mav_type: int = None, autopilot: int = None, base_mode: int = 192, custom_mode: int = 0, system_status: int = 4) -> bytes:
    """Encode a HEARTBEAT message using the given source sys/comp.

    The src_sys/src_comp are written into the MAVLink header so receivers see
    the heartbeat as originating from the GCS/agent.
    """
    # default values from pymavlink constants if not supplied
    try:
        mav_type = mav_type or mavutil.mavlink.MAV_TYPE_GCS
    except Exception:
        mav_type = 6
    try:
        autopilot = autopilot or mavutil.mavlink.MAV_AUTOPILOT_INVALID
    except Exception:
        autopilot = 8

    mav, buf = _make_mavlink_writer(src_sys, src_comp)
    try:
        msg = mav.heartbeat_encode(int(mav_type), int(autopilot), int(base_mode), int(custom_mode), int(system_status))
    except Exception as e:
        raise RuntimeError(f"failed to encode HEARTBEAT: {e}") from e
    # ensure header carries the desired source
    try:
        # some MAVLink writer instances allow setting srcSystem/srcComponent
        if src_sys is not None:
            setattr(mav, 'srcSystem', int(src_sys))
        if src_comp is not None:
            setattr(mav, 'srcComponent', int(src_comp))
    except Exception:
        pass

    mav.send(msg)
    return buf.getvalue()


def encode_command_long(target_sys: int, target_comp: int, command: int, params: Sequence[float] | None = None, confirmation: int = 0, src_sys: int = 255, src_comp: int = 1) -> bytes:
    """Encode a COMMAND_LONG message as packed MAVLink bytes.

    - target_sys, target_comp: destination
    - command: numeric MAV_CMD value
    - params: sequence of up to 7 float parameters (missing values default to 0)
    - confirmation: usually 0
    - src_sys, src_comp: source system/component (defaults to GCS: 250/1)

    Returns packed bytes suitable for sending over a MAVLink wire.
    """
    if params is None:
        params = []
    # normalize to 7 params
    p = list(params)[:7] + [0.0] * max(0, 7 - len(params))

    mav, buf = _make_mavlink_writer(src_sys, src_comp)
    # build message
    try:
        msg = mav.command_long_encode(
            target_sys,
            target_comp,
            int(command),
            int(confirmation),
            float(p[0]),
            float(p[1]),
            float(p[2]),
            float(p[3]),
            float(p[4]),
            float(p[5]),
            float(p[6]),
        )
    except Exception as e:
        raise RuntimeError(f"failed to encode COMMAND_LONG: {e}") from e

    # send/write into buffer and return bytes
    mav.send(msg)
    return buf.getvalue()


def encode_mission_count(target_sys: int, target_comp: int, count: int, mission_type: int = 0, src_sys: int = 255, src_comp: int = 1) -> bytes:
    """Encode a MISSION_COUNT message.

    - target_sys, target_comp: destination
    - count: number of mission items
    - mission_type: 0 for mission, 1 for fence, 2 for rally (if supported)
    - src_sys, src_comp: source system/component (defaults to GCS: 250/1)
    """
    mav, buf = _make_mavlink_writer(src_sys, src_comp)
    try:
        msg = mav.mission_count_encode(
            target_sys,
            target_comp,
            int(count),
        )
    except Exception as e:
        raise RuntimeError(f"failed to encode MISSION_COUNT: {e}") from e

    mav.send(msg)
    return buf.getvalue()


def encode_mission_item_int(target_sys: int, target_comp: int, seq: int, frame: int, command: int, current: int = 0, autocontinue: int = 1, params: Sequence[float] | None = None, x: int = 0, y: int = 0, z: float = 0.0, src_sys: int = 255, src_comp: int = 1) -> bytes:
    """Encode a MISSION_ITEM_INT message (minimal required fields).

    This produces the packed MAVLink bytes for MISSION_ITEM_INT. The
    `params` sequence fills param1..param4 and defaults to zero if missing.
    - src_sys, src_comp: source system/component (defaults to GCS: 250/1)
    """
    if params is None:
        params = []
    p = list(params)[:4] + [0.0] * max(0, 4 - len(params))

    mav, buf = _make_mavlink_writer(src_sys, src_comp)
    try:
        msg = mav.mission_item_int_encode(
            target_sys,
            target_comp,
            int(seq),
            int(frame),
            int(command),
            int(current),
            int(autocontinue),
            float(p[0]),
            float(p[1]),
            float(p[2]),
            float(p[3]),
            int(x),
            int(y),
            float(z),
        )
    except Exception as e:
        raise RuntimeError(f"failed to encode MISSION_ITEM_INT: {e}") from e

    mav.send(msg)
    return buf.getvalue()


def encode_mission_request_list(target_sys: int, target_comp: int, mission_type: int = 0, src_sys: int = 255, src_comp: int = 1) -> bytes:
    """Encode MISSION_REQUEST_LIST message."""
    try:
        mav, buf = _make_mavlink_writer(src_sys, src_comp)
        # pymavlink's mission_request_list_encode typically expects only
        # target_system and target_component (mission_type isn't part of
        # older pymavlink signatures). Call the two-arg form for maximum
        # compatibility.
        try:
            msg = mav.mission_request_list_encode(target_sys, target_comp)
        except TypeError:
            # fallback: if the implementation accepts mission_type, use it
            msg = mav.mission_request_list_encode(target_sys, target_comp, mission_type)
    except Exception as e:
        raise RuntimeError(f"failed to encode MISSION_REQUEST_LIST: {e}") from e

    mav.send(msg)
    return buf.getvalue()


def encode_mission_request_int(target_sys: int, target_comp: int, seq: int, mission_type: int = 0, src_sys: int = 255, src_comp: int = 1) -> bytes:
    """Encode MISSION_REQUEST_INT message."""
    try:
        mav, buf = _make_mavlink_writer(src_sys, src_comp)
        # mission_request_int_encode historically takes (target_sys, target_comp, seq)
        # newer versions may accept mission_type as a fourth argument; try the
        # 3-arg form first and fall back to 4-arg if needed.
        try:
            msg = mav.mission_request_int_encode(target_sys, target_comp, seq)
        except TypeError:
            msg = mav.mission_request_int_encode(target_sys, target_comp, seq, mission_type)
    except Exception as e:
        raise RuntimeError(f"failed to encode MISSION_REQUEST_INT: {e}") from e

    mav.send(msg)
    return buf.getvalue()


__all__ = ["is_mavlink2_packet", "encode_heartbeat", "encode_command_long", "encode_mission_count", "encode_mission_item_int", "encode_mission_request_list", "encode_mission_request_int"]
