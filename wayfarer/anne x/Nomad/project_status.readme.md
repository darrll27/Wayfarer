Project Status — Nomad (snapshot)
================================

Date: 2025-11-14

Summary
-------
This document captures the current state of the Nomad repository (frontend + backend), what is implemented and working today, known issues, and recommended next steps for the next developer or GitHub agent.

How to run (development)
-------------------------
- Activate Python venv and run backend router (from repo root):

```bash
source .venv/bin/activate
python backend/mav_router/run_router.py
```

- Start the frontend (dev server + Aedes broker) from `frontend/`:

```bash
cd frontend
npm install    # once
npm run aedes  # starts a local Aedes broker (ws on 1884)
npm run dev    # starts Vite dev server
```

Frontend status
---------------
What works:
- Small React/Vite demo app exists in `frontend/`.
- It connects to a local Aedes websocket broker (ws://localhost:1884) using the `mqtt` package.
- Subscribes to key topics: `device/+/+/HEARTBEAT/#`, `device/+/+/RAW`, `nomad/status`, `Nomad/config` and displays recent messages.
- Demo action: publishes a `command/<sysid>/<compid>/load_waypoints` payload (see `sendLoadWaypointsDemo`) to exercise backend waypoint validation.

Known frontend issues / TODOs:
- UI bug: the demo button in `frontend/src/App.jsx` currently calls `sendMissionTest`, which is undefined and will throw when clicked. It should call `sendLoadWaypointsDemo` (or wire a properly named handler).
- The UI is a lightweight demo and needs further pages (fleet dashboard, telemetry panels, waypoint manager, command panel) to be feature-complete.
- No automated UI tests exist yet.

Backend status
--------------
What works (implemented):
- MAVLink transport processes: UDP listener and Serial listener skeletons implemented under `backend/mav_router/transport.py`. They enqueue inbound packets into the router and publish copies to the MQTT publisher queue for the adapter.
- Router (`backend/mav_router/router.py`): parses MAVLink v1/v2 headers to extract sysid/compid, maintains `observed_sysids` and `last_addr`, implements forwarding rules and a global per-packet dedupe cache to reduce forwarding loops.
- MQTT adapter (`backend/mav_router/mqtt_adapter.py`):
  - Decodes MAVLink messages using `pymavlink` when available and publishes structured MQTT topics: `device/sysid_<n>/compid_<m>/<MSG>` plus (optional) per-field topics under `device/.../<MSG>/<field>`, and a `sources/.../<port>` view.
  - Fallback to RAW hex topics when parsing unavailable or when message fails parsing.
  - Supports receiving `command/<sysid>/<compid>/details` and encoding `COMMAND_LONG` and `MISSION_ITEM_INT` to inject into transport out queues.
  - New config toggles: `mqtt.publish_fields` (defaults OFF) to avoid per-field expansions that inflate device/# message counts; `mqtt.debug_publish_counts` to help diagnose publish rates.
- MAVLink encoder (`backend/mav_router/mavlink_encoder.py`): helper functions encode COMMAND_LONG, MISSION_ITEM_INT, and encode HEARTBEAT. The GCS heartbeat defaults were aligned to match QGC: `base_mode=192` and `system_status=4`.
- GCS heartbeat generator (`backend/mav_router/gcs_heartbeat.py`): background thread that injects a periodic (1 Hz) HEARTBEAT into transports. Optional debug with `gcs_heartbeat_debug` added to detect unexpected fast ticks.
- Waypoint validator skeleton exists at `backend/waypoint_validator/validator.py` (validates YAML, computes hash) and is used by MQTTAdapter when receiving `load_waypoints` commands (validation-only behavior — does not auto-run uploads).
- `run_router.py` is a dev harness to start transports, router, and the MQTT adapter and heartbeat generator.

Known backend issues / notes:
- There was an observed issue where `device/` topics appeared at much higher rates than `sources/` topics; root cause was mainly per-field publishes (1 + N fields) inflating device counts. A config toggle `mqtt.publish_fields` was added to disable per-field publishing by default.
- A prior attempted change to avoid sending heartbeats to local endpoints was reverted after user requested local listeners still receive heartbeats; ensure heartbeat loops are monitored (use `gcs_heartbeat_debug: true` and `mqtt.debug_publish_counts: true` for troubleshooting).
- The router's dedupe and forwarding logic exists but complex forwarding graphs may still produce loops; instrumenting counters in Router and transports is recommended when debugging.

Files of interest
-----------------
- backend/mav_router/router.py — routing, dedupe logic
- backend/mav_router/mqtt_adapter.py — MQTT bridge, decoding, encoding
- backend/mav_router/mavlink_encoder.py — encode_heartbeat, encode_command_long, mission encoders
- backend/mav_router/gcs_heartbeat.py — heartbeat generator
- backend/mav_router/transport.py — UDP and serial transports
- backend/waypoint_validator/validator.py — waypoint validation
- frontend/src/App.jsx — demo React UI
- frontend/package.json — scripts and aedes helper

Next steps for the incoming GitHub agent / developer
--------------------------------------------------
High priority (to make the project handover-ready):
1. Fix the frontend demo button: change `sendMissionTest` to `sendLoadWaypointsDemo` (or rename the handler consistently) so the demo button works.
2. Add a small smoke/integration test that:
   - Starts the router (in a test harness or with mocked queues), injects a raw heartbeat packet, and asserts the MQTTAdapter publishes a single `device/.../HEARTBEAT` and `sources/...` message.
3. Add Router instrumentation to count per-packet forwards and expose intermittent metrics on `nomad/status` (helpful to detect amplification loops).

Medium priority (stability & features):
1. Expand the frontend: implement telemetry panels, heartbeat-driven drone list, waypoint upload UI, command panel, and config editor.
2. Implement mission upload state machine (MISSION_COUNT → MISSION_ITEM_INT → verification) and associated unit tests.
3. Add basic auth or token support to Aedes if the app will run on untrusted networks.

Low priority / nice-to-have:
1. Add end-to-end tests with a local Aedes broker, a simulated UDP peer, and assertions on MQTT topics.
2. Add CI checks to run lints and basic unit tests.
3. Add a packaged venv or Dockerfile for reproducible backend runs.

Contact notes for handover
-------------------------
- The authoritative topic schema and conventions are in `instructions.md` (follow exact regexes for topic parsing and publishing).
- GCS sysid convention: 250 (used across the codebase).
- Keep forwarding semantics port-centric — don't mutate sysid/compid when forwarding.

If you want, I can also create:
- A small frontend fix patch (1-line) to make the demo button work now.
- A minimal smoke test that encodes a heartbeat, feeds it into the adapter loop, and asserts MQTT publishes.

End of status
