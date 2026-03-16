from __future__ import annotations

from typing import List, Dict, Any, Tuple
import hashlib


def validate_waypoints(waypoints: List[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, Any]]]:
    """Validate a simple waypoint list (from YAML) and return (ok, details, normalized_list).

    Normalization: ensure keys lat/lon/alt present, convert numeric types.
    """
    norm = []
    try:
        if not isinstance(waypoints, list):
            return False, "waypoints must be a list", []
        for i, w in enumerate(waypoints):
            if not isinstance(w, dict):
                return False, f"waypoint[{i}] must be a dict", []
            lat = w.get("lat")
            lon = w.get("lon")
            alt = w.get("alt")
            frame = w.get("frame", 6)
            action = w.get("action", "waypoint")
            if lat is None or lon is None or alt is None:
                return False, f"waypoint[{i}] missing lat/lon/alt", []
            try:
                lat = float(lat)
                lon = float(lon)
                alt = float(alt)
            except Exception:
                return False, f"waypoint[{i}] lat/lon/alt must be numeric", []
            norm.append({"seq": i, "lat": lat, "lon": lon, "alt": alt, "frame": int(frame), "action": action})
    except Exception as e:
        return False, f"validation error: {e}", []
    return True, "ok", norm


def waypoints_to_mission_items(waypoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert normalized waypoint dicts to mission item dicts matching MissionUploader expected schema.

    Returns list with keys: seq, frame, command, x, y, z, params...
    """
    items = []
    for w in waypoints:
        items.append({
            "seq": int(w.get("seq", 0)),
            "frame": int(w.get("frame", 6)),
            "command": 16,  # MAV_CMD_NAV_WAYPOINT
            "x": int(round(w.get("lat", 0) * 1e7)) if isinstance(w.get("lat"), float) else int(w.get("lat", 0)),
            "y": int(round(w.get("lon", 0) * 1e7)) if isinstance(w.get("lon"), float) else int(w.get("lon", 0)),
            "z": float(w.get("alt", 0.0)),
            "params": [],
        })
    return items


def compute_hash_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


__all__ = ["validate_waypoints", "waypoints_to_mission_items", "compute_hash_bytes"]
