"""Define mavlink command templates as functions.

Each function returns a dict describing the action and parameters. Later these will be
translated into mavsdk calls or raw mavlink messages.
"""
from typing import Dict, Any, List


def arm(sysid: int, force: bool = False) -> Dict[str, Any]:
    return {"cmd": "ARM", "sysid": sysid, "force": force}


def set_mode(sysid: int, mode: str) -> Dict[str, Any]:
    return {"cmd": "SET_MODE", "sysid": sysid, "mode": mode}


def set_hold_mode(sysid: int) -> Dict[str, Any]:
    return {"cmd": "SET_HOLD", "sysid": sysid}


def set_offboard_mode(sysid: int) -> Dict[str, Any]:
    return {"cmd": "SET_OFFBOARD", "sysid": sysid}


def upload_mission(sysid: int, waypoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"cmd": "UPLOAD_MISSION", "sysid": sysid, "count": len(waypoints), "waypoints": waypoints}
