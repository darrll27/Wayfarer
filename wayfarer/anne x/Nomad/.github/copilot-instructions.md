## GitHub Copilot / AI agent instructions for Nomad (summary)

Purpose: quick, actionable guidance so an AI coding agent is immediately productive in this repo.

Key idea (big picture)
- This repository implements an MQTT-backed MAVLink router and UI (Electron + React). Major pieces:
  - `aedes_broker/` (Node.js) — the MQTT broker used by frontend and services.
  - `backend/` (Python, embedded in Electron) — contains `api_server.py`, `mav_router/` (router.py, mavlink_io.py, mission_uploader.py, sysid_tracker.py), and `waypoint_validator/`.
  - `mav_template/` — Python templates for common MAV actions (arm, mission_upload, offboard, etc.).
  - `groups/`, `config/Config.yaml`, and `Files/waypoints/` — fleet/group configs and waypoint YAML files.
  - `frontend/` — React app bundled by Electron (connects to Aedes via WS).

Essential rules and conventions (do not change these):
- MQTT topic schema is authoritative and must be followed exactly. Examples:
  - Device view: `device/<sysid>/<compid>/<MAV_MSG_NAME>/<field>`
    - e.g. `device/1/1/HEARTBEAT/type`
  - Source view: `sources/<src_sysid>/<src_compid>/<dest_sysid>/<dest_compid>/<MSG>/<port>`
  - Command input: `command/<target_sysid>/<target_compid>/details` (JSON payload)
- GCS sysid is fixed to `250` in conventions.
- Router must not mutate sysid/compid — only unwrap/republish MAVLink fields into JSON topics.

Required regexes (copy exactly from `instructions.md` when matching topics):
- Device topic: `^device\/([0-9]+)\/([0-9]+)\/([A-Z0-9_]+)\/?(.*)$`
- Source topic: `^sources\/([0-9]+)\/([0-9]+)\/([0-9]+)\/([0-9]+)\/([A-Z0-9_]+)\/([a-zA-Z0-9_]+)$`
- Command topic: `^command\/([0-9]+)\/([0-9]+)\/details$`

Important flows and examples to implement/observe
- MAVLink → MQTT: publish both `device/<sysid>/<compid>/<msg>/*` and `sources/<src>/<srccomp>/<dst>/<dstcomp>/<msg>/<port>` for each incoming packet.
- MQTT → MAVLink: listen for `command/<sysid>/<compid>/details` and translate payload to the correct MAVLink message (e.g., `COMMAND_LONG`, `MISSION_ITEM_INT`).
- Waypoint upload contract: validate `Files/waypoints/*.yaml` with `waypoint_validator/`, compute file hash, publish validation to `Nomad/waypoints/<filename>/validation`, then publish `command/<sysid>/<compid>/load_waypoints` to trigger upload (router will handle MISSION_COUNT → MISSION_ITEM_INT sequence).

Developer workflows & quick-start (discoverable commands)
- Frontend (React):
  - cd into `frontend/` then `npm install` and `npm start` (logs in your context show these commands used).
- Python backend (development):
  - Create venv: `python -m venv .venv` then `source .venv/bin/activate` on macOS.
  - Install: `pip install -r requirements.txt` (repo root contains `requirements.txt`).
  - Run: `python backend/api_server.py` (the `api_server` starts the Python services used by Electron).
- Aedes broker: check `aedes_broker/` for `broker.js` or `package.json` scripts. Typical run: `node aedes_broker/broker.js` or `cd aedes_broker && npm start` depending on project scripts.

Project-specific patterns and gotchas
- Waypoint files: `waypoints:` array with `lat`, `lon`, `alt`, `frame`, `action`; per-drone waypoint variants live under `groups/<group>/drones/waypoints.<drone_id>.yaml` and altitude offsets are applied by the loader.
- Logs: per-device logs are stored under `logs/<sysid>.log` — the router must include src/dest metadata in every log line.
- Statefulness: the router should be stateless except for the mission upload state machine (IDLE, REQUESTING, UPLOADING, VERIFYING). Keep state minimal and explicit.
- Process model: prefer multiprocessing over threading in Python (codebase encourages processes + joins). Follow existing patterns in `backend/` modules.

What to change vs. what to preserve
- Preserve: MQTT topic structure, regexes, `GCS=sysid 250` convention, and the MISSION_COUNT → MISSION_ITEM_INT mission upload flow.
- Reasonable edits: refactors that keep public behavior (topics, REST/MQTT contracts) intact; small docs, tests, and validator improvements.

Where to look first (most useful files to read):
- `instructions.md` (root) — authoritative design doc and intended source-of-truth.
- `backend/api_server.py` — entry point for Python services.
- `backend/mav_router/router.py` and `backend/mav_router/mavlink_io.py` — message translation and IO.
- `backend/waypoint_validator/validator.py` — YAML parsing, validation rules, and hash generation.
- `aedes_broker/` and `frontend/` — to understand how services connect (MQTT WS and topics).

When asking the user for clarification, prefer these targeted questions:
- Which runtime should we assume for local dev (system Python vs packaged venv)?
- Are there any custom package scripts in `aedes_broker/` or `frontend/` I should use instead of generic `node`/`npm` commands?
- Which logs or test data files (if any) contain representative MAVLink traffic to use for integration tests?

If you want me to iterate on this file: tell me any missing files, commands, or conventions you rely on and I'll update the doc to include them.
