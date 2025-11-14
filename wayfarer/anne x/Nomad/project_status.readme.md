Project Status — Nomad (snapshot)
================================

Date: 2025-11-14

Summary
-------
This document captures the current state of the Nomad repository (frontend + backend), what is implemented and working today, known issues, and recommended next steps for the next developer or GitHub agent.

How to run (development)
-------------------------
- Activate Python venv and run backend router (from repo root):

```markdown
Project Status — Nomad (snapshot)
================================

Date: 2025-11-15

Snapshot
--------
This document captures the current codebase state (frontend + backend), known issues, UX observations, and a prioritized next-steps roadmap. It reflects the code and documentation in the repository (notably `instructions.md`) and what a developer needs to pick up work quickly.

Quick dev run notes (dev-only)
------------------------------
- Recommended: create and activate the repo venv, install Python deps from `requirements.txt`, then run the router harness.

```bash
source .venv/bin/activate
python backend/mav_router/run_router.py
```

- Frontend dev (from `frontend/`):

```bash
cd frontend
npm install    # first time
npm run aedes  # starts local Aedes broker (tcp:1883, ws:1884)
npm run dev    # Vite dev server for the React UI
```

What exists now (technical)
---------------------------
- Frontend: a small React/Vite demo lives in `frontend/`. It connects via MQTT (ws) to the local Aedes broker and subscribes to a handful of topics.
- Backend: Python services under `backend/` implementing a MAVLink router skeleton, transports (UDP/Serial), MQTT adapter bridge, MAVLink encoder helpers, GCS heartbeat generator, and a waypoint validator skeleton.
- Broker: Aedes server used for local dev (TCP+WebSocket), invoked via helper scripts in `frontend/`.

What works (high level)
-----------------------
- Router and transports: UDP and serial transport skeletons and a routing core that extracts sysid/compid and applies forwarding rules with a dedupe cache.
- MQTT adapter: decodes MAVLink (using pymavlink where available), publishes structured `device/...` and `sources/...` topics, and listens to `command/<sysid>/<compid>/details` to translate into MAVLink messages (COMMAND_LONG, MISSION_ITEM_INT).
- Waypoint validator: a validator exists that reads YAML and computes a file hash; `load_waypoints` flows are validation-only (do not auto-run uploads).
- GCS heartbeat: generator built to emit a periodic HEARTBEAT with QGC-like defaults (1 Hz).

UX / User experience observations (important)
-------------------------------------------
The current UI is a functional demo but lacks a coherent user experience. To make the app usable by operators and testers we should address the following:

- Missing core flows: there is no clear primary navigation (no Mission Control, Telemetry, Waypoint Manager, or Command Panel). Users cannot complete end-to-end tasks (validate/upload waypoints, monitor heartbeats, select a drone and command it) without manual/topic-level work.
- Feedback & confirmations: commands from the UI need explicit success/failure acknowledgement (command ack UI, loader / progress / toast messages). Right now the UI fires topics but provides limited feedback.
- Map & mission visualization: waypoint preview on a map is required for user trust — this is referenced in `instructions.md` and currently missing.
- Broker & backend status: users must be informed when the MQTT broker or backend is unreachable. The frontend sometimes falls back silently; prefer a prominent banner with action (retry, show logs, provide instructions to start services).
- Message explorer: a simple MQTT topic explorer with counts and last message preview would greatly improve UX for debugging.
- Accessibility & polish: color contrast, keyboard navigation, and clear iconography will be needed for a production-feeling UI.

Known issues and troubleshooting hints
------------------------------------
- Per-field publishing inflation: `device/.../<MSG>/<field>` expansion can cause large numbers of MQTT messages; `mqtt.publish_fields` default is OFF to avoid this.
- Duplicate router starts: in dev, running uvicorn with `--reload` while also spawning the router caused duplicate router processes; orchestrator scripts now avoid `--reload`.
- Router state machine: the mission upload state machine is not fully implemented (MISSION_COUNT → MISSION_ITEM_INT → verification).

Files of interest
-----------------
- `backend/mav_router/router.py` — routing & dedupe logic
- `backend/mav_router/mqtt_adapter.py` — bridge, decode/encode, publishes `nomad/status`
- `backend/mav_router/mavlink_encoder.py` — MAVLink helpers
- `backend/mav_router/gcs_heartbeat.py` — GCS heartbeat generator
- `backend/waypoint_validator/validator.py` — waypoint YAML validation
- `frontend/src/App.jsx` — demo UI and places to add telemetry/commands
- `instructions.md` — authoritative topic schema, regexes, and design constraints (must follow)

Prioritized Next Steps (actionable roadmap)
------------------------------------------
The list below is ordered by impact: short quick wins first, then stability/features, then medium-term polish and packaging.

Immediate (next 1–3 days)
- Fix the demo button handler in `frontend/src/App.jsx` to prevent the runtime error (change `sendMissionTest` → `sendLoadWaypointsDemo` or rename consistently). Low risk, quick win.
- Add a visible broker/backend status banner in the UI showing: broker reachability (ws/tcp), API `/api/status` health, and router_running. When unreachable, disable GCS/drone controls and show a clear action button (Retry / Open docs).
- Make `nomad/status` publishing a visible heartbeat in the UI (small status tile) so the user sees the system is alive.

High priority (next 1–2 weeks)
- Implement mission upload state machine (MISSION_COUNT → MISSION_ITEM_INT → verify). Add unit tests for the sequence and edge cases (timeouts, NACKs).
- Add a small smoke test harness: run the router (or a harness of its core components) and assert one heartbeat packet produces both `device/.../HEARTBEAT` and `sources/...` MQTT publishes. Integrate this into CI.
- Add Router instrumentation: per-packet forward counters and publish these metrics periodically on `nomad/status` to help detect amplification loops.

Medium priority (2–6 weeks)
- UX work: implement core frontend pages: Fleet Dashboard, Telemetry Panel (per-drone telemetry stream + last value), Waypoint Manager (file upload + validation + map preview), and Command Panel (arm/disarm/takeoff/land with acks).
- Message explorer & topic inspector: UI to subscribe to arbitrary topics, filter, and display counts + last message.
- Packaging: design and implement a reproducible packaging strategy for the Python backend (packaged venv or pyinstaller artifacts) and integrate with Electron builds.

Longer term / nice-to-have
- Auth & security for Aedes (token/JWT) if deploying beyond local dev. Keep simple token-based auth initially.
- End-to-end integration tests with local Aedes and simulated UDP peers for CI.
- Documentation: developer onboarding README that includes `scripts/dev.sh` usage, how to package the Python runtime, and steps to reproduce common issues.

Assumptions & constraints
-----------------------
- We must preserve the authoritative topic schema and regexes in `instructions.md`.
- The router should not mutate sysid/compid — routing remains port-centric.
- The app will initially target local/dev usage; secure production deployment is a separate follow-up.

How I validated this update
---------------------------
- I read `instructions.md` (topic schema and contracts) and reviewed the current `project_status.readme.md` content. The Next Steps above derive from the repository state and the constraints written in `instructions.md`.

If you want, next I can:
- Apply the one-line frontend fix for the broken demo button and run a quick smoke test locally.
- Create the minimal smoke/integration test harness to catch regressions on heartbeat → MQTT publish.

End of status
```
