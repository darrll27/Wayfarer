from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import socket
import subprocess
import contextlib
from pathlib import Path
import yaml
from typing import List
import time
import threading

# waypoint validator from backend package
try:
    from backend.waypoint_validator.validator import validate_waypoints, compute_hash_bytes
except Exception:
    # fallback if module import path differs during direct script runs
    from waypoint_validator.validator import validate_waypoints, compute_hash_bytes
import paho.mqtt.client as mqtt

app = FastAPI(title='Nomad Config API')

# Allow the frontend dev server to call this API during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'broker.json')
REPO_ROOT = Path(__file__).resolve().parents[1]
WAYPOINTS_DIR = REPO_ROOT / 'missions'
WAYPOINTS_DIR.mkdir(parents=True, exist_ok=True)

# MQTT subscriber client used to capture onboard missions published by the router
mqtt_sub_client = None

def _start_mission_subscriber():
    """Start a background MQTT client that listens for Nomad/missions/downloaded/+ and
    saves the mission payload into WAYPOINTS_DIR/temp as a temporary waypoint YAML file.
    """
    global mqtt_sub_client
    try:
        broker = _read_broker_json()
        host = broker.get('host', 'localhost')
        port = int(broker.get('tcp_port', 1883))
    except Exception:
        return

    def _on_message(client, userdata, msg):
        # Parse payload as JSON and extract mission items
        try:
            payload = msg.payload.decode('utf-8')
            obj = json.loads(payload)
        except Exception:
            return

        sysid = obj.get('sysid') or obj.get('target_sys') or 'unknown'
        mission_items = obj.get('mission') or obj.get('mission_items') or obj.get('items') or []
        waypoints = []
        for it in mission_items:
            try:
                x = it.get('x')
                y = it.get('y')
                z = it.get('z', 0)
                if x is None or y is None:
                    continue
                lat = float(y) / 1e7
                lon = float(x) / 1e7
                waypoints.append({
                    'lat': lat,
                    'lon': lon,
                    'alt': z,
                    'frame': int(it.get('frame', 0)) if it.get('frame') is not None else 0,
                    'action': 'waypoint'
                })
            except Exception:
                continue

        if not waypoints:
            return

        temp_dir = WAYPOINTS_DIR / 'temp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        fn = f"{sysid}_onboard_{int(time.time())}.yaml"
        dst = temp_dir / fn
        try:
            with open(dst, 'w', encoding='utf-8') as f:
                yaml.safe_dump({'waypoints': waypoints}, f)
        except Exception as e:
            print(f'[config_api] failed to write onboard mission file: {e}')
            return

        # validate and publish validation result
        try:
            ok, details, normalized = validate_waypoints(waypoints)
            payload_out = json.dumps({'filename': f'temp/{fn}', 'valid': ok, 'details': details, 'count': len(normalized), 'sysid': sysid})
            _mqtt_publish(f'Nomad/waypoints/temp/{sysid}/validation', payload_out)
            print(f'[config_api] saved onboard mission for sysid={sysid} -> {dst}')
        except Exception as e:
            print(f'[config_api] onboard validation/publish failed: {e}')

    try:
        mqtt_sub_client = mqtt.Client(client_id=f'nomad-api-subscriber-{int(time.time())}')
        mqtt_sub_client.on_message = _on_message
        mqtt_sub_client.connect(host, port, keepalive=10)
        mqtt_sub_client.subscribe('Nomad/missions/downloaded/+')
        mqtt_sub_client.loop_start()
        print(f'[config_api] started mission subscriber to Nomad/missions/downloaded/+ on {host}:{port}')
    except Exception as e:
        print(f'[config_api] failed to start mission subscriber: {e}')


def _read_broker_json():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='broker.json not found')
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f'invalid JSON: {e}')


def _tcp_port_open(host, port, timeout_s=0.6):
    try:
        with contextlib.closing(socket.create_connection((host, int(port)), timeout=timeout_s)):
            return True
    except Exception:
        return False


@app.get('/api/config')
def get_config():
    """Return the centralized broker.json content."""
    data = _read_broker_json()
    return JSONResponse(content=data)


@app.get('/api/status')
def get_status():
    """Basic handshake/status endpoint. Returns whether the config is readable and broker reachability.

    This performs a fast TCP probe to the configured broker ports (short timeout) and reports reachability.
    """
    try:
        broker = _read_broker_json()
        host = broker.get('host')
        tcp_port = broker.get('tcp_port')
        ws_port = broker.get('ws_port')

        tcp_ok = False
        ws_ok = False
        if host and tcp_port:
            tcp_ok = _tcp_port_open(host, tcp_port)
        if host and ws_port:
            ws_ok = _tcp_port_open(host, ws_port)

        # indicate whether the router process was started by this API
        router_alive = False
        try:
            router_alive = bool(router_proc is not None and getattr(router_proc, 'poll', lambda: 1)() is None)
        except Exception:
            router_alive = False
        return {
            'ok': True,
            'broker_present': True,
            'broker_host': host,
            'broker_tcp_port': tcp_port,
            'broker_ws_port': ws_port,
            'broker_tcp_reachable': tcp_ok,
            'broker_ws_reachable': ws_ok,
            'router_running': router_alive,
        }
    except HTTPException as e:
        return {'ok': False, 'broker_present': False, 'error': e.detail}


def _read_waypoint_file(path: Path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            # expect top-level `waypoints:` or raw list
            if isinstance(data, dict) and 'waypoints' in data:
                w = data['waypoints']
            else:
                w = data
            return w
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to read waypoint file: {e}')


@app.get('/api/waypoints')
def list_waypoints():
    """List waypoint YAML files and return lightweight metadata + parsed waypoint counts.
    
    Supports nested structure: missions/{mission_name}/{group_name}/{sysid}_waypoints.yaml
    """
    out = []

    # First, scan for files in the nested structure (including missions/temp)
    for p in sorted(WAYPOINTS_DIR.rglob('*.y*ml')):
        try:
            # relative path under WAYPOINTS_DIR, e.g. 'temp/1_onboard_*.yaml' or 'demo_mission/alpha/1_waypoints.yaml'
            rel_path = p.relative_to(WAYPOINTS_DIR)
            parts = rel_path.parts
            is_temp = (len(parts) > 0 and parts[0] == 'temp')

            data = _read_waypoint_file(p)
            ok, details, normalized = validate_waypoints(data if data is not None else [])
            file_bytes = p.read_bytes()
            h = compute_hash_bytes(file_bytes)

            # Interpret mission/group/filename where appropriate
            if is_temp:
                mission_name = None
                group_name = 'temp'
                filename = str(rel_path)
            elif len(parts) == 1:
                mission_name = None
                group_name = None
                filename = parts[0]
            elif len(parts) == 3:
                mission_name, group_name, filename = parts
            else:
                mission_name = None
                group_name = None
                filename = str(rel_path)

            out.append({
                'filename': str(rel_path),
                'mission_name': mission_name,
                'group_name': group_name,
                'hash': h,
                'count': len(normalized),
                'valid': ok,
                'details': details,
                'temp': bool(is_temp),
            })
        except Exception as e:
            try:
                rel_path = p.relative_to(WAYPOINTS_DIR)
            except Exception:
                rel_path = p
            out.append({
                'filename': str(rel_path),
                'mission_name': None,
                'group_name': None,
                'error': str(e),
            })

    # Sort results with temp files first, then by filename
    out.sort(key=lambda x: (0 if x.get('temp') else 1, x.get('filename', '')))

    return {'ok': True, 'files': out}

@app.get('/api/waypoints/{filename:path}')
def get_waypoint_file(filename: str):
    p = WAYPOINTS_DIR / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail='file not found')
    data = _read_waypoint_file(p)
    return {'ok': True, 'filename': filename, 'waypoints': data}

@app.post('/api/waypoints')
def upload_waypoints(payload: dict):
    """Save a waypoint file. Payload: {filename, waypoints: [ ... ]}

    Validates using the waypoint_validator and returns the result. Also writes YAML to Files/waypoints.
    """
    filename = payload.get('filename')
    waypoints = payload.get('waypoints')
    print(f"[config_api] upload_waypoints called filename={filename} count={(len(waypoints) if isinstance(waypoints, list) else 'N/A')}")
    if not filename or not isinstance(waypoints, list):
        raise HTTPException(status_code=400, detail='expected payload {filename, waypoints: [...]}')
    # validate
    ok, details, normalized = validate_waypoints(waypoints)
    # write YAML
    dst = WAYPOINTS_DIR / filename
    try:
        content = {'waypoints': waypoints}
        with open(dst, 'w', encoding='utf-8') as f:
            yaml.safe_dump(content, f)
        h = compute_hash_bytes(yaml.safe_dump(content).encode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to write file: {e}')
    # publish validation to MQTT topic Nomad/waypoints/<filename>/validation
    try:
        payload = json.dumps({'filename': filename, 'valid': ok, 'details': details, 'count': len(normalized), 'hash': h})
        _mqtt_publish(f'Nomad/waypoints/{filename}/validation', payload)
    except Exception:
        # non-fatal for the API response
        pass
    return {'ok': True, 'filename': filename, 'valid': ok, 'details': details, 'hash': h}


@app.post('/api/waypoints/upload_raw')
def upload_waypoints_raw(payload: dict):
    """Accept raw YAML text and a filename. Payload: {filename: str, raw: str}

    Parses YAML, validates, writes file and returns validation result.
    """
    filename = payload.get('filename')
    raw = payload.get('raw')
    print(f"[config_api] upload_waypoints_raw called filename={filename} size={(len(raw) if isinstance(raw, str) else 'N/A')}")
    if not filename or not isinstance(raw, str):
        raise HTTPException(status_code=400, detail='expected {filename, raw}')
    try:
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict) and 'waypoints' in parsed:
            waypoints = parsed['waypoints']
        else:
            waypoints = parsed
        ok, details, normalized = validate_waypoints(waypoints if waypoints is not None else [])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'yaml parse/validation error: {e}')
    # write file
    dst = WAYPOINTS_DIR / filename
    try:
        with open(dst, 'w', encoding='utf-8') as f:
            f.write(raw)
        h = compute_hash_bytes(raw.encode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to write: {e}')
    # publish validation via MQTT
    try:
        payload = json.dumps({'filename': filename, 'valid': ok, 'details': details, 'count': len(normalized), 'hash': h})
        _mqtt_publish(f'Nomad/waypoints/{filename}/validation', payload)
    except Exception:
        pass
    return {'ok': True, 'filename': filename, 'valid': ok, 'details': details, 'hash': h}


def _mqtt_publish(topic: str, payload: str, qos: int = 0, retain: bool = False, timeout_s: float = 2.0):
    """Publish a single MQTT message to the configured broker (TCP).

    Uses paho-mqtt to perform a synchronous publish. Returns True on success.
    """
    broker = _read_broker_json()
    host = broker.get('host', 'localhost')
    port = broker.get('tcp_port', 1883)
    client = mqtt.Client()
    try:
        client.connect(host, int(port), keepalive=10)
        client.loop_start()
        try:
            print(f"[config_api] publishing MQTT topic={topic} host={host}:{port} payload_preview={payload[:200]}")
        except Exception:
            pass
        info = client.publish(topic, payload, qos=qos, retain=retain)
        # wait for publish
        waited = 0.0
        while not info.is_published() and waited < timeout_s:
            time.sleep(0.05)
            waited += 0.05
        client.loop_stop()
        client.disconnect()
        return info.is_published()
    except Exception as e:
        try:
            client.disconnect()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f'mqtt publish failed: {e}')


@app.post('/api/waypoints/send')
def send_waypoints_to_drone(payload: dict):
    """Trigger a load_waypoints command to a target drone.

    Payload: {sysid: int, compid: int, filename: str}
    This reads the waypoint file, validates it, and publishes a command payload to topic
    `command/<sysid>/<compid>/load_waypoints` with the file contents embedded.
    """
    sysid = payload.get('sysid')
    compid = payload.get('compid', 1)
    filename = payload.get('filename')
    print(f"[config_api] send_waypoints_to_drone called sysid={sysid} compid={compid} filename={filename}")
    if not sysid or not filename:
        raise HTTPException(status_code=400, detail='expected {sysid, compid, filename}')
    path = WAYPOINTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail='waypoint file not found')
    waypoints = _read_waypoint_file(path)
    ok, details, normalized = validate_waypoints(waypoints if waypoints is not None else [])
    if not ok:
        return {'ok': False, 'detail': 'validation failed', 'validation': details}
    topic = f'command/{int(sysid)}/{int(compid)}/load_waypoints'
    payload_out = json.dumps({'filename': filename, 'waypoints': waypoints})
    published = _mqtt_publish(topic, payload_out)
    return {'ok': published, 'topic': topic, 'filename': filename}


@app.post('/api/waypoints/download')
def download_mission_from_drone(payload: dict):
    """Trigger a download_mission command to a target drone.

    Payload: {sysid: int, compid: int}
    This publishes a command to topic `command/<sysid>/<compid>/download_mission`
    and the router will handle downloading the mission and publishing it back.
    """
    sysid = payload.get('sysid')
    compid = payload.get('compid', 1)
    print(f"[config_api] download_mission_from_drone called sysid={sysid} compid={compid}")
    if not sysid:
        raise HTTPException(status_code=400, detail='expected {sysid, compid}')
    topic = f'command/{int(sysid)}/{int(compid)}/download_mission'
    payload_out = json.dumps({'action': 'download_mission', 'sysid': sysid, 'compid': compid})
    published = _mqtt_publish(topic, payload_out)
    return {'ok': published, 'topic': topic}


@app.post('/api/waypoints/onboard')
def save_onboard_waypoints(payload: dict):
    """Save an onboard (downloaded) mission into a temp waypoint YAML file.

    Payload: {sysid: int, mission: [ {x,y,z,frame,...}, ... ], filename?: str}
    The saved file will be placed under missions/temp/<filename> or a generated name.
    """
    sysid = payload.get('sysid')
    mission_items = payload.get('mission') or payload.get('items') or []
    filename = payload.get('filename')
    if not sysid or not isinstance(mission_items, list):
        raise HTTPException(status_code=400, detail='expected {sysid, mission:list, filename?}')

    # convert mission items to waypoint format
    waypoints = []
    for it in mission_items:
        try:
            x = it.get('x')
            y = it.get('y')
            z = it.get('z', 0)
            if x is None or y is None:
                continue
            lat = float(y) / 1e7
            lon = float(x) / 1e7
            waypoints.append({'lat': lat, 'lon': lon, 'alt': z, 'frame': int(it.get('frame', 0)), 'action': 'waypoint'})
        except Exception:
            continue

    temp_dir = WAYPOINTS_DIR / 'temp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    if not filename:
        filename = f"{sysid}_onboard_{int(time.time())}.yaml"
    dst = temp_dir / filename
    try:
        with open(dst, 'w', encoding='utf-8') as f:
            yaml.safe_dump({'waypoints': waypoints}, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to write onboard file: {e}')

    # validate and publish validation via MQTT
    try:
        ok, details, normalized = validate_waypoints(waypoints)
        payload_out = json.dumps({'filename': f'temp/{filename}', 'valid': ok, 'details': details, 'count': len(normalized), 'sysid': sysid})
        _mqtt_publish(f'Nomad/waypoints/temp/{sysid}/validation', payload_out)
    except Exception:
        pass

    return {'ok': True, 'filename': f'temp/{filename}', 'count': len(waypoints)}


@app.post('/api/waypoints/promote')
def promote_temp_waypoint(payload: dict):
    """Promote a temp onboard waypoint file into the main waypoints directory.

    Payload: {temp_filename: 'temp/<name>.yaml', dest_filename: 'group/name.yaml'}
    """
    temp_filename = payload.get('temp_filename')
    dest_filename = payload.get('dest_filename')
    if not temp_filename or not dest_filename:
        raise HTTPException(status_code=400, detail='expected {temp_filename, dest_filename}')
    # locate source and destination
    if temp_filename.startswith('temp/'):
        src = WAYPOINTS_DIR / temp_filename.replace('temp/', '')
    else:
        src = WAYPOINTS_DIR / 'temp' / temp_filename
    dst = WAYPOINTS_DIR / dest_filename
    if not src.exists():
        raise HTTPException(status_code=404, detail='temp file not found')
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, 'r', encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
            d.write(s.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'failed to promote file: {e}')
    return {'ok': True, 'promoted': str(dst)}


@app.get('/api/routes')
def list_routes():
    """Return a simple list of API routes (path and methods) for debugging."""
    out = []
    try:
        for r in app.routes:
            methods = []
            try:
                methods = list(r.methods) if getattr(r, 'methods', None) else []
            except Exception:
                methods = []
            out.append({'path': getattr(r, 'path', str(r)), 'name': getattr(r, 'name', None), 'methods': methods})
    except Exception:
        pass
    return {'ok': True, 'routes': out}


@app.get('/api/router/status')
def get_router_status():
    """Get detailed router process status."""
    global router_proc
    status = {
        'router_process_exists': router_proc is not None,
        'router_pid': router_proc.pid if router_proc else None,
        'router_running': False,
        'router_exit_code': None,
    }
    
    if router_proc:
        try:
            exit_code = router_proc.poll()
            status['router_running'] = exit_code is None
            status['router_exit_code'] = exit_code
        except Exception as e:
            status['error'] = str(e)
    
    return status


@app.post('/api/router/restart')
def restart_router():
    """Restart the router process."""
    global router_proc
    try:
        # Stop existing router if running
        if router_proc:
            try:
                router_proc.terminate()
                router_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                router_proc.kill()
                router_proc.wait()
            router_proc = None
        
        # Start new router process
        _start_router_process()
        
        return {'ok': True, 'message': 'Router restarted successfully'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def create_demo_mission():
    # center around Mountain View / Baylands approximate coords
    base_lat = 37.4680
    base_lon = -122.0870
    files = []
    
    # Create mission directory structure
    mission_dir = WAYPOINTS_DIR / 'demo_mission'
    alpha_dir = mission_dir / 'alpha'
    bravo_dir = mission_dir / 'bravo'
    alpha_dir.mkdir(parents=True, exist_ok=True)
    bravo_dir.mkdir(parents=True, exist_ok=True)
    
    # create 6 parallel lines with small offsets (meters -> approx degrees)
    # roughly convert meters to degrees (~1e-5 deg ~ 1.11m) is approximate; use 1e-5 per meter
    offset_deg = 0.00009  # ~10m
    
    # Alpha group: drones 1-3
    for drone in range(1, 4):
        offset = (drone - 1) * offset_deg
        waypoints = []
        for i in range(6):
            lat = base_lat + (i * 0.00012)  # step north
            lon = base_lon + offset
            alt = 30 + (i % 2) * 5
            waypoints.append({'lat': lat, 'lon': lon, 'alt': alt, 'frame': 6, 'action': 'waypoint'})
        filename = f'{drone}_waypoints.yaml'
        dst = alpha_dir / filename
        with open(dst, 'w', encoding='utf-8') as f:
            yaml.safe_dump({'waypoints': waypoints}, f)
        files.append(f'demo_mission/alpha/{filename}')
    
    # Bravo group: drones 4-6
    for drone in range(4, 7):
        offset = (drone - 1) * offset_deg
        waypoints = []
        for i in range(6):
            lat = base_lat + (i * 0.00012)  # step north
            lon = base_lon + offset
            alt = 30 + (i % 2) * 5
            waypoints.append({'lat': lat, 'lon': lon, 'alt': alt, 'frame': 6, 'action': 'waypoint'})
        filename = f'{drone}_waypoints.yaml'
        dst = bravo_dir / filename
        with open(dst, 'w', encoding='utf-8') as f:
            yaml.safe_dump({'waypoints': waypoints}, f)
        files.append(f'demo_mission/bravo/{filename}')
    
    # publish validation for each created file
    try:
        for filename in files:
            p = WAYPOINTS_DIR / filename
            data = _read_waypoint_file(p)
            ok, details, normalized = validate_waypoints(data if data is not None else [])
            h = compute_hash_bytes(p.read_bytes())
            payload = json.dumps({'filename': filename, 'valid': ok, 'details': details, 'count': len(normalized), 'hash': h})
            _mqtt_publish(f'Nomad/waypoints/{filename}/validation', payload)
    except Exception:
        pass
    return {'ok': True, 'files': files}


# Optionally start the main router process when the API starts so the backend
# and the config/status API live in the same application lifecycle. This helps
# the Electron dev flow where uvicorn is started by the main process and we
# want the router to be available without a separate manual step.
router_proc = None


@app.on_event('startup')
def _start_router_process():
    """Start the router as a subprocess so module import semantics match running
    the script directly (this avoids multiprocessing.spawn import issues).
    """
    global router_proc
    try:
        if router_proc is None or router_proc.poll() is not None:
            import subprocess
            import sys
            import threading
            from pathlib import Path

            repo_root = Path(__file__).resolve().parents[1]
            env = dict(os.environ)
            # ensure the router script can import backend modules from repo root
            env['PYTHONPATH'] = str(repo_root)
            # use same python executable as the running process
            python_exec = sys.executable or 'python3'
            cmd = [python_exec, str(repo_root / 'backend' / 'mav_router' / 'run_router.py')]
            
            # Create log files for router output
            log_dir = repo_root / 'logs'
            log_dir.mkdir(exist_ok=True)
            stdout_log = log_dir / 'router_stdout.log'
            stderr_log = log_dir / 'router_stderr.log'
            
            print(f'[config_api] starting router, logs: {stdout_log}, {stderr_log}')
            router_proc = subprocess.Popen(cmd, cwd=str(repo_root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            # Start a thread to read and log router output
            def monitor_router_output():
                try:
                    with open(stdout_log, 'w') as stdout_f, open(stderr_log, 'w') as stderr_f:
                        while router_proc.poll() is None:
                            if router_proc.stdout:
                                line = router_proc.stdout.readline()
                                if line:
                                    stdout_f.write(f'{line}')
                                    stdout_f.flush()
                            if router_proc.stderr:
                                line = router_proc.stderr.readline()
                                if line:
                                    stderr_f.write(f'{line}')
                                    stderr_f.flush()
                            time.sleep(0.1)
                except Exception as e:
                    print(f'[config_api] error monitoring router output: {e}')

            monitor_thread = threading.Thread(target=monitor_router_output, daemon=True)
            monitor_thread.start()

            print(f'[config_api] started router subprocess pid={router_proc.pid}')
            # Start a lightweight MQTT subscriber to capture onboard missions published by the router
            try:
                _start_mission_subscriber()
            except Exception as e:
                print(f'[config_api] failed to start mission subscriber: {e}')
    except Exception as e:
        print(f'[config_api] failed to start router subprocess: {e}')


@app.on_event('shutdown')
def _stop_router_process():
    global router_proc
    try:
        if router_proc is not None and router_proc.poll() is None:
            router_proc.terminate()
            try:
                router_proc.wait(timeout=2.0)
            except Exception:
                router_proc.kill()
    except Exception:
        pass
