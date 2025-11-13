"""Waypoint manager: send and verify mission waypoints.

This module provides a thin abstraction to send missions and verify them. It
prefers `mavsdk` if available; otherwise it simulates success for scaffolding.
"""
from typing import List, Dict, Any
try:
    from mavsdk import System
    _HAS_MAVSDK = True
except Exception:
    System = None  # type: ignore
    _HAS_MAVSDK = False
import os
from .config import load_config, generate_per_drone_waypoints_for_group
from .router import parse_udp_uri
import asyncio


def _resolve_target_for_sysid(cfg, sysid: int):
    """Resolve a transport/udp uri for a given sysid using canonical config.

    Returns a string uri like 'udp://host:port' or 'host:port', or None if not resolvable.
    """
    try:
        for gname, grp in cfg.groups.items():
            for d in grp.drones:
                try:
                    if int(d.sysid) == int(sysid):
                        transport = d.transport
                        # If transport is a named transport in top-level transports
                        if transport in cfg.transports:
                            t = cfg.transports[transport]
                            # prefer explicit udp_target when present
                            if getattr(t, "udp_target", None):
                                return t.udp_target
                            # otherwise, if uri itself is udp:// return that
                            if getattr(t, "uri", None) and str(t.uri).startswith("udp://"):
                                return t.uri
                            # not resolvable to UDP
                            return None
                        # If transport looks like a URI (e.g. udp://host:port) return it
                        if isinstance(transport, str) and transport.startswith("udp://"):
                            return transport
                        # If transport looks like host:port
                        if isinstance(transport, str) and ":" in transport:
                            return transport
                except Exception:
                    continue
    except Exception:
        pass
    return None


async def send_mission(sysid: int, waypoints: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send mission waypoints to a vehicle. Returns a result dict.

    NOTE: This function assumes a mapping from sysid -> udp endpoint is available
    elsewhere (config). For now, it's a stub that returns success when mavsdk
    is not installed.
    """
    # Persist the mission to disk for logging (non-fatal). Include last_sent timestamp.
    from datetime import datetime, timezone
    last_sent = datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
    missions_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "missions"))
    os.makedirs(missions_dir, exist_ok=True)
    mission_path = os.path.join(missions_dir, f"mission_{sysid}.yaml")
    persist_ok = False
    persist_error = None
    try:
        import yaml
        with open(mission_path, "w") as fh:
            yaml.safe_dump({"waypoints": waypoints, "last_sent": last_sent}, fh, sort_keys=False)
        persist_ok = True
    except Exception as e:
        # best-effort persist; record error but don't fail the send
        persist_error = str(e)

    if not _HAS_MAVSDK:
        resp = {"ok": True, "sent_count": len(waypoints), "note": "mavsdk not available; simulated", "last_sent": last_sent}
        if persist_ok:
            resp["persisted"] = mission_path
        else:
            resp["persisted"] = None
            resp["persist_error"] = persist_error
        return resp

    # If mavsdk is available, find target endpoint from config for this sysid
    cfg = load_config()
    target_uri = _resolve_target_for_sysid(cfg, sysid)

    if not target_uri:
        return {"ok": False, "sent_count": 0, "reason": "no endpoint for sysid"}

    try:
        host, port = parse_udp_uri(target_uri)
    except Exception as e:
        return {"ok": False, "sent_count": 0, "reason": f"invalid uri: {e}"}

    vehicle = System()
    # Try preferred udpin/udp forms for mavsdk connections. Prefer udpin:// which
    # tells mavsdk to listen for incoming packets on the given port.
    connect_errors = []
    tried_addrs = [f"udpin://{host}:{port}", f"udp://{host}:{port}"]
    connected = False
    for addr in tried_addrs:
        try:
            await vehicle.connect(system_address=addr)
            connected = True
            break
        except Exception as e:
            connect_errors.append((addr, repr(e)))
    if not connected:
        return {"ok": False, "sent_count": 0, "reason": "connect failed", "connect_errors": connect_errors}

    # Convert waypoints to mission items depending on mavsdk API
    mission_items = []
    for wp in waypoints:
        # attempt to map keys to likely mission item constructor params
        lat = wp.get("lat")
        lon = wp.get("lon")
        alt = wp.get("alt")
        frame = wp.get("frame")
        action = wp.get("action")
        # use a generic dict; actual conversion happens in try/except below
        mission_items.append({"lat": lat, "lon": lon, "alt": alt, "frame": frame, "action": action})

    # Try common mavsdk mission upload interfaces
    try:
        mission = vehicle.mission
        # If upload_mission exists
        if hasattr(mission, "upload_mission"):
            # Try to convert items to the expected MissionItem form. Different
            # mavsdk versions have different MissionItem signatures; we attempt
            # a best-effort conversion and fall back to `set_mission` with
            # simple dicts if constructing MissionItem fails.
            try:
                from mavsdk.mission import MissionItem
                mi = []
                for m in mission_items:
                    # Construct MissionItem with the full argument list expected
                    # by newer mavsdk versions. Use reasonable defaults for
                    # optional fields.
                    lat = m.get("lat")
                    lon = m.get("lon")
                    alt = m.get("alt")
                    mi.append(
                        MissionItem(
                            lat,
                            lon,
                            alt,
                            0.0,          # speed_m_s
                            False,        # is_fly_through
                            0.0,          # gimbal_pitch_deg
                            0.0,          # gimbal_yaw_deg
                            0,            # camera_action
                            0.0,          # loiter_time_s
                            0.0,          # camera_photo_interval_s
                            0.0,          # acceptance_radius_m
                            0.0,          # yaw_deg
                            0.0,          # camera_photo_distance_m
                            0             # vehicle_action
                        )
                    )
                await mission.upload_mission(mi)
                resp = {"ok": True, "sent_count": len(mi), "last_sent": last_sent}
                if persist_ok:
                    resp["persisted"] = mission_path
                else:
                    resp["persisted"] = None
                    resp["persist_error"] = persist_error
                return resp
            except Exception:
                # Fall through to the set_mission fallback below.
                pass
        # Fallback to set_mission or other method patterns
        if hasattr(mission, "set_mission"):
            try:
                await mission.set_mission(mission_items)
                resp = {"ok": True, "sent_count": len(mission_items), "last_sent": last_sent}
                if persist_ok:
                    resp["persisted"] = mission_path
                else:
                    resp["persisted"] = None
                    resp["persist_error"] = persist_error
                return resp
            except Exception:
                pass
    except Exception as e:
        # upload failed; return structured error but include persistence metadata if available
        resp = {"ok": False, "sent_count": 0, "reason": f"mission upload failed: {e}", "errors": [{"stage": "upload", "detail": str(e)}], "last_sent": last_sent}
        if persist_ok:
            resp["persisted"] = mission_path
        else:
            resp["persisted"] = None
            resp["persist_error"] = persist_error
        return resp

    # If we reach here, we couldn't upload using known APIs but persistence (if any) remains as a log
    resp = {"ok": False, "sent_count": 0, "reason": "no known mission upload interface", "errors": [{"stage": "upload_interface", "detail": "no known mission upload interface available"}], "last_sent": last_sent}
    if persist_ok:
        resp["persisted"] = mission_path
    else:
        resp["persisted"] = None
        resp["persist_error"] = persist_error
    return resp


async def verify_mission(sysid: int) -> Dict[str, Any]:
    """Download mission from vehicle and return a simple verification result.

    If mavsdk is missing this returns a simulated verified response.
    """
    # Determine expected waypoints by finding the group containing this sysid
    cfg = load_config()
    expected = None
    for gname, grp in cfg.groups.items():
        found = False
        for d in grp.drones:
            try:
                if int(d.sysid) == int(sysid):
                    found = True
                    break
            except Exception:
                continue
        if found:
            per = generate_per_drone_waypoints_for_group(cfg, gname)
            expected = per.get(int(sysid), {}).get("waypoints", [])
            break

    if expected is None:
        expected = []

    if not _HAS_MAVSDK:
        # simulated verification: report expected but note that we couldn't fetch
        return {"ok": False, "verified": False, "reason": "mavsdk not available", "expected_count": len(expected)}

    # If mavsdk is available, attempt to connect to the vehicle's UDP address
    # Look up the udp endpoint from config (group mapping)
    target_uri = _resolve_target_for_sysid(cfg, sysid)

    if not target_uri:
        return {"ok": False, "verified": False, "reason": "no endpoint for sysid"}

    # parse target (strip udp://)
    try:
        host, port = parse_udp_uri(target_uri)
    except Exception as e:
        return {"ok": False, "verified": False, "reason": f"invalid uri: {e}"}

    system = System()
    # Try udpin first so mavsdk listens on the port, then fallback to udp://
    connect_errors = []
    tried_addrs = [f"udpin://{host}:{port}", f"udp://{host}:{port}"]
    connected = False
    for addr in tried_addrs:
        try:
            await asyncio.wait_for(system.connect(system_address=addr), timeout=5.0)
            connected = True
            break
        except Exception as e:
            connect_errors.append((addr, repr(e)))
    if not connected:
        return {"ok": False, "verified": False, "reason": "connect failed", "connect_errors": connect_errors}

    # Attempt to download mission items. The exact mavsdk mission API may vary;
    # we try a couple of interfaces defensively.
    fetched = []
    try:
        # Preferred: mission.get_mission returns a list (older/newer sdk differences exist)
        mission = system.mission
        # try download_mission if available
        if hasattr(mission, "download_mission"):
            # download_mission may be a coroutine returning items
            try:
                items = await mission.download_mission()
                fetched = items if isinstance(items, list) else list(items)
            except Exception:
                # fallback to get_mission
                fetched = []
        if not fetched and hasattr(mission, "get_mission"):
            # get_mission often yields an async generator
            try:
                async for itm in mission.get_mission():
                    fetched.append(itm)
            except Exception:
                # final fallback - empty
                fetched = []
    except Exception as e:
        return {"ok": False, "verified": False, "reason": f"mission fetch failed: {e}"}

    # Convert fetched mission items to a simple comparable form (lat, lon, alt, frame, action)
    parsed = []
    for it in fetched:
        try:
            # many mission item objects expose attributes: latitude_deg, longitude_deg, relative_altitude_m
            lat = getattr(it, "latitude_deg", getattr(it, "lat", None))
            lon = getattr(it, "longitude_deg", getattr(it, "lon", None))
            alt = getattr(it, "relative_altitude_m", getattr(it, "alt", None))
            frame = getattr(it, "frame", None)
            cmd = getattr(it, "command", None)
            parsed.append({"lat": lat, "lon": lon, "alt": alt, "frame": frame, "cmd": cmd})
        except Exception:
            parsed.append({"raw": str(it)})

    # Compare expected vs parsed: compare counts and per-index lat/lon/alt within small tolerance
    diffs = []
    ok = True
    if len(parsed) != len(expected):
        ok = False
        diffs.append({"reason": "count_mismatch", "expected": len(expected), "got": len(parsed)})

    minlen = min(len(parsed), len(expected))
    for i in range(minlen):
        e = expected[i]
        p = parsed[i]
        # Compare numeric fields with tolerance
        def almost(a, b, tol=1e-6):
            try:
                return abs(float(a) - float(b)) <= tol
            except Exception:
                return a == b

        lat_ok = almost(e.get("lat"), p.get("lat"))
        lon_ok = almost(e.get("lon"), p.get("lon"))
        alt_ok = almost(e.get("alt"), p.get("alt"))
        if not (lat_ok and lon_ok and alt_ok):
            ok = False
            diffs.append({"index": i, "expected": e, "got": p})

    return {"ok": ok, "verified": ok, "diffs": diffs, "expected_count": len(expected), "fetched_count": len(parsed)}
