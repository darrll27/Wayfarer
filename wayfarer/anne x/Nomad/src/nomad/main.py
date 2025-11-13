"""NOMAD FastAPI app (scaffold).

Design constraints (follow these early):

- Cross-platform: support macOS, Ubuntu, and other Linux distros for packaging/export.
- Thin router: a MAVLink router should forward raw bytes and tag sources; do not decode MAVLink in the router.
- MAV decoding: decode and interpret MAVLink only at API endpoints that need structured data (verification, structured logs, telemetry responses).
- Multiprocessing: use multiprocessing (process isolation) for long-running components (router, heartbeat, launcher) instead of threads where practical.

This file is a minimal FastAPI scaffold. The router and mavsdk connectors should be implemented in separate modules/processes and orchestrated from here.
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict, Any
from .config import load_config, save_config, generate_per_drone_waypoints_for_group, load_group_waypoints, list_group_names, get_group_sysids
from .mav_templates import arm, set_mode, set_hold_mode, set_offboard_mode, upload_mission
import yaml
from . import runner
from .mav_decoder import decoder
from .launcher import Launcher
from .state import set_latest, get_latest

app = FastAPI(title="NOMAD Backend Scaffold")

# Allow cross-origin requests from local dev servers and Electron renderer.
# In development it's convenient to allow all origins; adjust for production
# packaging if you want to lock this down.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory latest messages per sysid
latest_messages: Dict[int, Dict[str, Any]] = {}

# Ensure logs dir exists
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log_for_sysid(sysid: int, payload: Any) -> None:
    path = os.path.join(LOG_DIR, f"{sysid}.log")
    with open(path, "a") as fh:
        fh.write(yaml.safe_dump(payload, sort_keys=False))
        fh.write("\n---\n")


@app.get("/config")
async def read_config():
    try:
        cfg = load_config()
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # Return the validated canonical config as JSON
    return JSONResponse(content=cfg.dict())


@app.post("/config")
async def write_config(payload: Dict = Body(...)):
    try:
        cfg = load_config()
    except FileNotFoundError:
        cfg = None
    # Overwrite by saving a YAML from payload
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    with open(path, "w") as fh:
        fh.write(yaml.safe_dump(payload, sort_keys=False))
    return {"ok": True, "path": path}


@app.get("/configs")
async def list_configs():
    cfg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config"))
    files = []
    if os.path.exists(cfg_dir):
        for f in os.listdir(cfg_dir):
            files.append(f)
    return {"files": files}


@app.get("/groups")
async def groups():
    cfg = load_config()
    groups = {}
    for name, grp in cfg.groups.items():
        groups[name] = {"drones": grp.drones, "launch_delay_seconds": grp.launch_delay_seconds}
    return groups


@app.get("/groups/{group_name}/waypoints")
async def group_waypoints(group_name: str):
    cfg = load_config()
    raw = load_group_waypoints(group_name)
    per_drone = generate_per_drone_waypoints_for_group(cfg, group_name)
    return {"raw": raw, "per_drone": per_drone}


@app.post("/groups/{group_name}/waypoints")
async def save_group_waypoints(group_name: str, payload: Dict = Body(...)):
    """Save group waypoints (overwrites groups/<group_name>/waypoints.yaml)."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "groups", group_name))
    os.makedirs(base_dir, exist_ok=True)
    wp_path = os.path.join(base_dir, "waypoints.yaml")
    # Accept either JSON/YAML structure; write as YAML for readability
    with open(wp_path, "w") as fh:
        fh.write(yaml.safe_dump(payload, sort_keys=False))
    return {"ok": True, "path": wp_path}


@app.get("/{sysid}/msg")
async def get_latest_msg(sysid: int):
    msg = latest_messages.get(sysid)
    if msg is None:
        raise HTTPException(status_code=404, detail="No messages for sysid")
    return msg


@app.post("/{sysid}/cmd")
async def cmd_sysid(sysid: int, command: Dict[str, Any] = Body(...)):
    # Map known commands to mav_templates
    verb = command.get("cmd")
    payload = None
    if verb == "ARM":
        payload = arm(sysid, force=command.get("force", False))
    elif verb == "SET_MODE":
        payload = set_mode(sysid, command.get("mode", "MISSION"))
    elif verb == "HOLD":
        payload = set_hold_mode(sysid)
    elif verb == "OFFBOARD":
        payload = set_offboard_mode(sysid)
    elif verb == "UPLOAD_MISSION":
        wps = command.get("waypoints", [])
        payload = upload_mission(sysid, wps)
    else:
        # Raw passthrough
        payload = {"cmd": "RAW", "sysid": sysid, "raw": command}

    # record as latest message and log
    latest_messages[sysid] = {"from_cmd": True, "payload": payload}
    log_for_sysid(sysid, {"cmd_in": payload})

    return {"ok": True, "payload": payload}


@app.post("/decode")
async def decode_raw(payload: Dict[str, Any] = Body(...)):
    """Decode raw hex data at API level using pymavlink if available.

    payload: { data_hex: str }
    """
    data_hex = payload.get("data_hex")
    if not data_hex:
        raise HTTPException(status_code=400, detail="data_hex required")
    try:
        raw = bytes.fromhex(data_hex)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid hex")

    decoded = decoder.parse_bytes(raw)
    return {"decoded": decoded}


# Router control endpoints
_router_instance = None
_serial_bridges = {}
_heartbeat_instance = None
_launcher = Launcher()


@app.post("/router/start")
async def api_router_start():
    global _router_instance
    cfg = load_config()
    cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    _router_instance = runner.start_router_from_config(cfg_path)
    return {"ok": True, "started": True}


@app.post("/router/stop")
async def api_router_stop():
    global _router_instance
    if _router_instance:
        try:
            _router_instance.stop()
        except Exception:
            pass
        _router_instance = None
    return {"ok": True, "stopped": True}


@app.get("/router/status")
async def api_router_status():
    global _router_instance
    if not _router_instance:
        return {"running": False}
    alive = getattr(_router_instance.process, "is_alive", lambda: False)()
    return {"running": alive}


@app.post("/heartbeat/start")
async def api_heartbeat_start():
    global _heartbeat_instance
    if _heartbeat_instance and getattr(_heartbeat_instance.process, "is_alive", lambda: False)():
        return {"ok": True, "started": False, "reason": "already running"}
    cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    from .heartbeat import HeartbeatSender
    # read router bind target from canonical config
    cfg = load_config()
    rconf = getattr(cfg, "router", {}) or {}
    bind = rconf.get("bind", "0.0.0.0:14540")
    host, port = bind.split(":")
    target = (host, int(port))
    internal_sysid = getattr(cfg, "internal_gcs_sysid", 250)
    hb = HeartbeatSender(target, sysid=internal_sysid, interval=1.0)
    hb.start()
    _heartbeat_instance = hb
    return {"ok": True, "started": True}


@app.post("/heartbeat/stop")
async def api_heartbeat_stop():
    global _heartbeat_instance
    if _heartbeat_instance:
        try:
            _heartbeat_instance.stop()
        except Exception:
            pass
        _heartbeat_instance = None
    return {"ok": True, "stopped": True}


@app.get("/heartbeat/status")
async def api_heartbeat_status():
    global _heartbeat_instance
    if not _heartbeat_instance:
        return {"running": False}
    alive = getattr(_heartbeat_instance.process, "is_alive", lambda: False)()
    return {"running": alive}


@app.post("/serial/start")
async def api_serial_start(payload: Dict[str, Any] = Body(...)):
    """Start a serial bridge.

    payload: { id: str, serial_uri: str, udp_target: str }
    """
    bid = payload.get("id")
    serial_uri = payload.get("serial_uri")
    udp_target = payload.get("udp_target")
    if not bid or not serial_uri or not udp_target:
        raise HTTPException(status_code=400, detail="id, serial_uri and udp_target required")
    if bid in _serial_bridges:
        return {"ok": False, "reason": "already running"}
    from .serial_bridge import SerialBridge
    sb = SerialBridge(serial_uri, udp_target)
    sb.start()
    _serial_bridges[bid] = sb
    return {"ok": True, "started": True}


@app.post("/serial/stop")
async def api_serial_stop(payload: Dict[str, Any] = Body(...)):
    bid = payload.get("id")
    if not bid:
        raise HTTPException(status_code=400, detail="id required")
    sb = _serial_bridges.get(bid)
    if not sb:
        return {"ok": False, "reason": "not found"}
    sb.stop()
    del _serial_bridges[bid]
    return {"ok": True, "stopped": True}


@app.get("/serial/list")
async def api_serial_list():
    return {"bridges": list(_serial_bridges.keys())}


@app.post("/launch/{group_name}")
async def api_launch_group(group_name: str):
    started = _launcher.start_group_launch(group_name)
    return {"ok": True, "started": started}


@app.post("/launch/stop")
async def api_launch_stop():
    _launcher.stop()
    return {"ok": True, "stopped": True}


@app.get("/sysid/{sysid}/latest")
async def api_sysid_latest(sysid: int):
    v = get_latest(sysid)
    if not v:
        raise HTTPException(status_code=404, detail="no data")
    return v


@app.on_event("startup")
async def _startup():
    """Auto-start router and heartbeat on FastAPI startup."""
    global _router_instance, _heartbeat_instance
    cfg_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "config.yaml"))
    # start router
    try:
        _router_instance = runner.start_router_from_config(cfg_path)
    except Exception:
        _router_instance = None

    # start heartbeat
    try:
        from .heartbeat import HeartbeatSender
        cfg = load_config()
        rconf = getattr(cfg, "router", {}) or {}
        bind = rconf.get("bind", "0.0.0.0:14540")
        host, port = bind.split(":")
        target = (host, int(port))
        internal_sysid = getattr(cfg, "internal_gcs_sysid", 250)
        hb = HeartbeatSender(target, sysid=internal_sysid, interval=1.0)
        hb.start()
        _heartbeat_instance = hb
    except Exception:
        _heartbeat_instance = None

    # autostart serial bridges / transports defined in config (canonically via config.transports)
    try:
        cfg = load_config()
        transports = getattr(cfg, "transports", {}) or {}
        from .serial_bridge import SerialBridge
        # transports: mapping id -> TransportConfig (with uri and optional udp_target)
        for tid, tcfg in transports.items():
            # tcfg should be a pydantic TransportConfig or dict-like
            if tcfg is None:
                continue
            uri = None
            udp_target = None
            if hasattr(tcfg, "uri"):
                uri = getattr(tcfg, "uri")
                udp_target = getattr(tcfg, "udp_target", None)
            elif isinstance(tcfg, dict):
                uri = tcfg.get("uri")
                udp_target = tcfg.get("udp_target")

            if not uri or not isinstance(uri, str):
                continue

            if uri.startswith("serial://"):
                if not udp_target:
                    # explicit udp target required for autostart
                    continue
                if tid not in _serial_bridges:
                    sb = SerialBridge(uri, udp_target)
                    sb.start()
                    _serial_bridges[tid] = sb
    except Exception:
        pass


@app.on_event("shutdown")
async def _shutdown():
    """Stop router, heartbeat, and launcher on shutdown."""
    global _router_instance, _heartbeat_instance, _launcher
    try:
        if _router_instance:
            _router_instance.stop()
            _router_instance = None
    except Exception:
        pass

    try:
        if _heartbeat_instance:
            _heartbeat_instance.stop()
            _heartbeat_instance = None
    except Exception:
        pass

    try:
        if _launcher:
            _launcher.stop()
    except Exception:
        pass


@app.post("/groups/{group_name}/send_missions")
async def api_send_group_missions(group_name: str):
    """Send missions for all drones in a group (uses per-drone altitude-decremented waypoints)."""
    import asyncio as _asyncio
    from .waypoint_manager import send_mission
    cfg = load_config()
    per_drone = generate_per_drone_waypoints_for_group(cfg, group_name)
    if not per_drone:
        raise HTTPException(status_code=404, detail="group or waypoints not found")

    tasks = []
    for sysid, wp in per_drone.items():
        waypoints = wp.get("waypoints", [])
        tasks.append(_asyncio.create_task(send_mission(sysid, waypoints)))

    results = await _asyncio.gather(*tasks, return_exceptions=True)
    return {"results": results}


@app.post("/groups/{group_name}/verify_missions")
async def api_verify_group_missions(group_name: str):
    """Verify missions uploaded to all drones in a group."""
    import asyncio as _asyncio
    from .waypoint_manager import verify_mission
    cfg = load_config()
    drone_ids = get_group_sysids(cfg, group_name)
    if not drone_ids:
        raise HTTPException(status_code=404, detail="group not found")

    tasks = []
    for sysid in drone_ids:
        tasks.append(_asyncio.create_task(verify_mission(sysid)))

    results = await _asyncio.gather(*tasks, return_exceptions=True)
    return {"results": results}


@app.post("/restart")
async def restart_server():
    # Minimal: reload config and return ok. A full restart would be platform-specific.
    cfg = load_config()
    return {"ok": True, "groups": list(cfg.groups.keys())}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.nomad.main:app", host="0.0.0.0", port=8000, reload=True)
