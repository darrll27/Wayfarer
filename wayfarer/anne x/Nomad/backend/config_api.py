from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import socket
import contextlib

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
            from pathlib import Path

            repo_root = Path(__file__).resolve().parents[1]
            env = dict(os.environ)
            # ensure the router script can import backend modules from repo root
            env['PYTHONPATH'] = str(repo_root)
            # use same python executable as the running process
            python_exec = sys.executable or 'python3'
            cmd = [python_exec, str(repo_root / 'backend' / 'mav_router' / 'run_router.py')]
            router_proc = subprocess.Popen(cmd, cwd=str(repo_root), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            # forward stdout/stderr asynchronously is optional; keep pipes for logs
            print('[config_api] started router subprocess pid=', router_proc.pid)
    except Exception as e:
        print('[config_api] failed to start router subprocess:', e)


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
