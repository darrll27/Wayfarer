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
                frame = item.get("frame", 3)  # MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
                command = item.get("command", 16)  # MAV_CMD_NAV_WAYPOINT
                current = 1 if idx == 0 else 0
                autocontinue = item.get("autocontinue", 1)
                params = item.get("params", [0]*7)
                param1 = params[0] if len(params) > 0 else 0
                param2 = params[1] if len(params) > 1 else 0
                param3 = params[2] if len(params) > 2 else 0
                param4 = params[3] if len(params) > 3 else 0
                # Accept both lat/lon/alt and x/y/z
                if "lat" in item and "lon" in item and "alt" in item:
                    x = int(item.get("lat", 0) * 1e7)
                    y = int(item.get("lon", 0) * 1e7)
                    z = int(item.get("alt", 0))
                else:
                    x = int(item.get("x", 0) * 1e7)
                    y = int(item.get("y", 0) * 1e7)
                    z = int(item.get("z", 0))
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
SUPPORTED_MSG_TYPES = ["COMMAND_LONG", "SET_MODE"]


def get_supported_msg_types():
    """Return list of msg_type strings that command_mapper supports."""
    return list(SUPPORTED_MSG_TYPES)
