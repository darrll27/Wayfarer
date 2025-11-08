"""Command mapping utilities for MAVLink writes.

This module centralizes conversion from normalized Packet commands
into concrete pymavlink send calls. Extend here as more message
types are needed.
"""

from typing import Sequence
from pymavlink import mavutil
from wayfarer.core.packet import Packet
import time


def _ensure_params_len(params: Sequence[float], n: int = 7) -> list:
    arr = list(params or [])
    if len(arr) < n:
        arr = arr + [0] * (n - len(arr))
    elif len(arr) > n:
        arr = arr[:n]
    return arr


def _resolve_mav_cmd_id(cmd: object) -> int:
    """Resolve MAV_CMD to numeric ID from various representations.

    Accepts:
      - int: returns as-is
      - str: tries mavutil.mavlink.<NAME>, optional 'MAV_CMD_' prefix,
        then falls back to scanning enums.
    """
    if isinstance(cmd, int):
        return cmd
    if isinstance(cmd, str):
        name = cmd
        # 1) direct attribute on mavutil.mavlink
        if hasattr(mavutil.mavlink, name):
            return int(getattr(mavutil.mavlink, name))
        # 2) with MAV_CMD_ prefix
        if not name.startswith("MAV_CMD_"):
            pref = f"MAV_CMD_{name}"
            if hasattr(mavutil.mavlink, pref):
                return int(getattr(mavutil.mavlink, pref))
        # 3) scan enums as last resort (case-sensitive match on enum entry name)
        try:
            enum = mavutil.mavlink.enums.get("MAV_CMD")
            if enum:
                for key, entry in enum.items():
                    # entry may have .name attribute
                    ename = getattr(entry, "name", None)
                    if ename == name or (not name.startswith("MAV_CMD_") and ename == f"MAV_CMD_{name}"):
                        return int(key)
        except Exception:
            pass
    raise ValueError(f"Unrecognized MAV_CMD: {cmd}")


def send_command(conn, pkt: Packet):
    """Map a normalized Packet to pymavlink send calls via `conn`.

        Supports:
            - COMMAND_LONG
            - SET_MODE
            - MISSION_UPLOAD
            - HEARTBEAT
            - REQUEST_DATA_STREAM
    """
    msg_type = pkt.msg_type
    try:
        if msg_type == "COMMAND_LONG":
            cmd_name = pkt.fields.get("command")
            cmd_id = _resolve_mav_cmd_id(cmd_name)
            params = _ensure_params_len(pkt.fields.get("params", [0] * 7), 7)
            # Resolve target system id with explicit precedence:
            # 1) pkt.fields['target_sysid']
            # 2) pkt.fields['sysid']
            # 3) extract from pkt.device_id (e.g., 'mav_sys3')
            # If none found, do NOT silently fall back to 1 — skip sending and log.
            target_sysid = pkt.fields.get("target_sysid")
            if target_sysid is None:
                target_sysid = pkt.fields.get("sysid")
            if target_sysid is None and getattr(pkt, "device_id", None):
                # try parse device_id like 'mav_sys3'
                try:
                    if isinstance(pkt.device_id, str) and pkt.device_id.startswith("mav_sys"):
                        target_sysid = int(pkt.device_id.split("mav_sys", 1)[1])
                except Exception:
                    target_sysid = None
            if target_sysid is None:
                print(f"[ERROR] No target sysid found in packet (fields or device_id); not sending command")
                return

            target_compid = pkt.fields.get("target_compid")
            if target_compid is None:
                target_compid = pkt.fields.get("compid", 1)
            conn.mav.command_long_send(
                target_sysid,
                target_compid,
                int(cmd_id) if cmd_id is not None else 0,
                0,
                *params,
            )
        elif msg_type == "SET_MODE":
            conn.mav.set_mode_send(
                pkt.fields.get("target_sysid", 1),
                pkt.fields.get("base_mode", 209),
                pkt.fields.get("custom_mode", 4),
            )
        elif msg_type == "HEARTBEAT":
            # Determine temporary source identity for on-wire send.
            # Prefer explicit fields if present, otherwise derive from pkt.device_id
            orig_sys = getattr(conn, "source_system", None)
            orig_comp = getattr(conn, "source_component", None)
            src_sys = pkt.fields.get("src_sysid")
            src_comp = pkt.fields.get("src_compid")
            # Derive from device_id like 'mav_sys3' when explicit src not provided
            if src_sys is None and getattr(pkt, "device_id", None):
                try:
                    if isinstance(pkt.device_id, str) and pkt.device_id.startswith("mav_sys"):
                        src_sys = int(pkt.device_id.split("mav_sys", 1)[1])
                except Exception:
                    src_sys = None
            # Fallback compid from generic 'compid' field or default to 1
            if src_comp is None:
                src_comp = pkt.fields.get("compid", 1)
            try:
                if src_sys is not None:
                    conn.source_system = int(src_sys)
                if src_comp is not None:
                    conn.source_component = int(src_comp)
            except Exception:
                pass
            try:
                conn.mav.heartbeat_send(
                    int(pkt.fields.get("type", getattr(mavutil.mavlink, "MAV_TYPE_GCS", 6))),
                    int(pkt.fields.get("autopilot", getattr(mavutil.mavlink, "MAV_AUTOPILOT_INVALID", 8))),
                    int(pkt.fields.get("base_mode", 192)),
                    int(pkt.fields.get("custom_mode", 0)),
                    int(pkt.fields.get("system_status", 4)),
                )
            finally:
                # Restore original identity to avoid global mutation
                try:
                    if orig_sys is not None:
                        conn.source_system = orig_sys
                    if orig_comp is not None:
                        conn.source_component = orig_comp
                except Exception:
                    pass
        elif msg_type == "REQUEST_DATA_STREAM":
            # Determine temporary source identity for on-wire request.
            orig_sys = getattr(conn, "source_system", None)
            orig_comp = getattr(conn, "source_component", None)
            src_sys = pkt.fields.get("src_sysid")
            src_comp = pkt.fields.get("src_compid")
            # Derive from device_id like 'mav_sys3' when explicit src not provided
            if src_sys is None and getattr(pkt, "device_id", None):
                try:
                    if isinstance(pkt.device_id, str) and pkt.device_id.startswith("mav_sys"):
                        src_sys = int(pkt.device_id.split("mav_sys", 1)[1])
                except Exception:
                    src_sys = None
            if src_comp is None:
                src_comp = pkt.fields.get("compid", 1)
            try:
                if src_sys is not None:
                    conn.source_system = int(src_sys)
                if src_comp is not None:
                    conn.source_component = int(src_comp)
            except Exception:
                pass
            try:
                conn.mav.request_data_stream_send(
                    int(pkt.fields.get("target_system", 0)),
                    int(pkt.fields.get("target_component", 0)),
                    int(pkt.fields.get("req_stream_id", getattr(mavutil.mavlink, "MAV_DATA_STREAM_ALL", 0))),
                    int(pkt.fields.get("req_message_rate", 10)),
                    int(pkt.fields.get("start_stop", 1)),
                )
            finally:
                try:
                    if orig_sys is not None:
                        conn.source_system = orig_sys
                    if orig_comp is not None:
                        conn.source_component = orig_comp
                except Exception:
                    pass
        elif msg_type == "MISSION_UPLOAD":
            # Handle mission upload: expects 'mission_items' in fields
            mission_items = pkt.fields.get("mission_items")
            target_sysid = pkt.fields.get("target_sysid") or pkt.fields.get("sysid")
            if target_sysid is None and getattr(pkt, "device_id", None):
                try:
                    if isinstance(pkt.device_id, str) and pkt.device_id.startswith("mav_sys"):
                        target_sysid = int(pkt.device_id.split("mav_sys", 1)[1])
                except Exception:
                    target_sysid = None
            if target_sysid is None:
                print(f"[ERROR] No target sysid found in mission upload packet; not sending mission")
                return
            target_compid = pkt.fields.get("target_compid") or pkt.fields.get("compid", 1)
            if not mission_items or not isinstance(mission_items, list):
                print(f"[ERROR] No mission_items found or not a list in mission upload packet")
                return
            # Send MISSION_COUNT first
            conn.mav.mission_count_send(
                target_sysid,
                target_compid,
                len(mission_items)
            )
            print(f"[INFO] MISSION_UPLOAD: sent MISSION_COUNT={len(mission_items)} for device_id={pkt.device_id}")
            # Send each mission item as a MAVLink MISSION_ITEM_INT message
            for idx, item in enumerate(mission_items):
                seq = idx
                command = item.get("command", 16)  # MAV_CMD_NAV_WAYPOINT
                current = 1 if idx == 0 else 0
                autocontinue = item.get("autocontinue", 1)
                params = item.get("params", [0]*7)
                param1 = params[0] if len(params) > 0 else 0
                param2 = params[1] if len(params) > 1 else 0
                param3 = params[2] if len(params) > 2 else 0
                param4 = params[3] if len(params) > 3 else 0
                # Use correct coordinate set based on frame type
                frame = item.get("frame")
                if frame == 6 and all(k in item for k in ("lat", "lon", "alt")):
                    x = int(item["lat"] * 1e7)
                    y = int(item["lon"] * 1e7)
                    z = float(item["alt"])
                elif frame == 3 and all(k in item for k in ("x", "y", "z")):
                    x = int(item["x"])
                    y = int(item["y"])
                    z = float(item["z"])
                else:
                    print(f"[ERROR] Invalid or missing coordinates/frame in mission item: {item}")
                    continue
                conn.mav.mission_item_int_send(
                    target_sysid,
                    target_compid,
                    seq,
                    frame,
                    command,
                    current,
                    autocontinue,
                    param1,
                    param2,
                    param3,
                    param4,
                    x,
                    y,
                    z
                )
                print(f"[DEBUG] MISSION_UPLOAD: sent MISSION_ITEM_INT seq={seq} for device_id={pkt.device_id}")
            print(f"[INFO] MISSION_UPLOAD: sent {len(mission_items)} items for device_id={pkt.device_id}")
            # No blocking wait for MISSION_ACK
        else:
            print(f"[WARN] No handler for msg_type={msg_type}")
        print(f"[DEBUG] send_command() sent msg_type={msg_type} for device_id={pkt.device_id}")
    except Exception as e:
        print(f"[ERROR] send_command() failed: {e}")


# Export supported message types for discovery/manifest
SUPPORTED_MSG_TYPES = [
    "COMMAND_LONG",
    "SET_MODE",
    "MISSION_UPLOAD",
    "HEARTBEAT",
    "REQUEST_DATA_STREAM",
]


def get_supported_msg_types():
    """Return list of msg_type strings that command_mapper supports."""
    return list(SUPPORTED_MSG_TYPES)
