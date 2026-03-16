# Nomad

Nomad is an MQTT-backed MAVLink router with a Python backend and an Electron/React frontend. This repository has been reduced to the Nomad project only.

## Repository layout

- `backend/` — FastAPI config API, MAVLink router, transport layer, mission upload/download logic, waypoint validation
- `frontend/` — Vite/Electron React app and local Aedes broker helper scripts
- `config/` — broker and runtime configuration
- `missions/` — mission and waypoint YAML files used by the backend and tests
- `tests/` and `backend/tests/` — unit and integration-oriented Python tests
- `hil_sil_tests/` — HIL/SIL test harness and reports

## Development

Python requirement:

- `python3` must be installed on the machine.
- For normal root dev flows, manual virtualenv activation is optional.

Root dev startup:

- `npm start`, `npm run dev`, and `npm run dev:desktop` go through `scripts/dev.sh`.
- That script creates `./.venv` if needed, installs or refreshes `requirements.txt`, and launches the backend with `./.venv/bin/python`.

If you just want to start the full stack, use:

```bash
npm start
```

Manual Python setup is only needed if you want to run backend commands yourself outside the root dev script:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

Useful variants:

```bash
npm run dev
npm run dev:desktop
npm run build
npm run start:build
npm run backend+broker
bash ./scripts/dev.sh desktop
bash ./scripts/dev.sh backend-only
.venv/bin/python -m uvicorn backend.config_api:app --reload --port 8000
.venv/bin/python backend/mav_router/run_router.py
```

## Broker settings

Broker configuration is stored in `config/broker.json` and can be edited from the **Settings** workspace in the UI.

Change timing:

- Config values are saved immediately.
- Router reconnect/restart is attempted immediately.
- Broker mode changes, and whether the local Aedes broker is spawned, should be treated as taking full effect on the next app restart.

Expected shape:

```json
{
	"mode": "internal",
	"host": "localhost",
	"tcp_port": 1883,
	"ws_port": 1884,
	"username": null,
	"password": null,
	"notes": "mode: internal => spawn local Aedes; external => do not spawn (assume external broker at host:tcp_port/ws_port)"
}
```

Port usage:

- `tcp_port`: native MQTT TCP port used by backend services and router-side MQTT clients.
- `ws_port`: MQTT-over-WebSocket port used by the frontend renderer client.

Mode behavior:

- `internal`: local Aedes broker is started by the dev stack.
- `external`: local Aedes is not started; Nomad connects to the configured external broker.

## Notes

- The previous nested Nomad virtual environment was intentionally not moved. Python virtual environments embed absolute paths, so use the new root `.venv`.
- The authoritative MQTT topic schema and project constraints are documented in `.github/copilot-instructions.md`.
- Additional project state and roadmap notes remain in `project_status.readme.md`.
