"""Command mapping utilities for MAVLink writes.

This module centralizes conversion from normalized Packet commands
into concrete pymavlink send calls. Extend here as more message
types are needed.
"""

from typing import Sequence
from pymavlink import mavutil
from wayfarer.core.packet import Packet


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
    """
    msg_type = pkt.msg_type
    try:
        if msg_type == "COMMAND_LONG":
            cmd_name = pkt.fields.get("command")
            cmd_id = _resolve_mav_cmd_id(cmd_name)
            params = _ensure_params_len(pkt.fields.get("params", [0] * 7), 7)
            target_sysid = pkt.fields.get("target_sysid", 1)
            target_compid = pkt.fields.get("target_compid", 1)
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
        else:
            print(f"[WARN] No handler for msg_type={msg_type}")
    except Exception as e:
        print(f"[ERROR] send_command() failed: {e}")
