# NOMAD (backend scaffold)

This folder contains an initial scaffold for the NOMAD backend (FastAPI + mavsdk stubs). It implements:

- Config loader (`src/nomad/config.py`) with `config/config.yaml` sample
- FastAPI app (`src/nomad/main.py`) with endpoints for listing configs, reading/writing config, group waypoints, per-sysid message/command endpoints
- `mav_templates` stubs for mapping API commands to MAVLink/mavsdk actions
- A sample `groups/example_group` with `waypoints.yaml` and templates

Design notes:

- Cross-platform: the project is intended to build and export on macOS, Ubuntu and other Linux distributions. Keep platform-specific paths and packaging (binaries, installers) minimal and documented here.
- Thin backend: the router should be thin — it should forward raw MAVLink bytes between birds and GCS and perform minimal tagging and buffering. Do NOT decode MAVLink in the router.
- MAVLink decode: decoding/parsing MAVLink messages should be done at the API interface where an endpoint needs to interpret messages (for verification, structured logs, or API responses). This keeps routing low-latency and simple.
- Multiprocessing: prefer multiprocessing (process isolation) for the router, heartbeat sender, and other long-running pipeline components rather than threads to avoid GIL contention and to provide easy process lifecycle control across platforms.

How to run (development):

1. Create a virtualenv and install requirements:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Start the API server:

```bash
uvicorn src.nomad.main:app --reload --port 8000
```

This is an initial scaffold to iterate on. Next steps: implement mavsdk connections, the MAVLink router (using multiprocessing and forwarding raw bytes), waypoint upload/verify (with MAV decode at API layer), frontend integration, and robust tests.

Frontend:

- A minimal React + Vite frontend scaffold is under `frontend/` with a simple Mission Control page that calls the `/groups/{group}/verify_missions` API. Start it with `npm run dev` inside `frontend/`.

Development startup:

- Use `./run.sh` to start the backend and (optionally) the frontend in dev mode. The script will create and use the `.venv` Python environment if present.
