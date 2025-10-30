# Houston — telemetry dashboard + broker

Houston is a minimal Anduril/SpaceX‑inspired multi‑page telemetry dashboard with a built‑in MQTT broker (Aedes). It’s designed to visualize Wayfarer/Pathfinder topics and let you manage per‑group config (alpha/beta/charlie) from the UI.

## Features
- React web UI (Vite) with multiple pages: Dashboard, Map, Groups, Config, Broker
- Built‑in MQTT broker (Aedes): TCP and WebSocket endpoints, served by the same Express server
- Map overlays: mission paths with numbered checkpoints, current checkpoint highlight
- Sysid picker on Map, plus auto‑fit to overlays by default
- Heartbeat‑only “alive” indicator with pulse on arrival (no flashing when missing)
- Mission cache in UI (kept for ~10 minutes) so overlays persist even if GPS hasn’t arrived
- Subscribes to Wayfarer device topics and root mission upload:
	- `wayfarer/v1/devices/mav_sys*/telem/raw/mavlink/*`
	- `wayfarer/v1/devices/mav_sys*/telem/state/heartbeat`
	- `wayfarer/v1/mission/upload` (root)

## Structure
- `config/houston.config.json` — groups and UI config
- `config/broker.config.json` — broker TCP/WS ports, options
- `server/` — Express server + Aedes broker + REST API
- `web/` — React UI (Vite)

## Quick start

1) Install deps (root uses npm workspaces):

```bash
cd houston
npm install
```

2) Start dev (runs web on :5173 and server + broker on :4000 with WS at `/mqtt`):

```bash
npm run dev
```

3) Build and run production:

```bash
npm run build
npm run start
```

- Web UI served from `http://localhost:4000` (static assets)
- WS MQTT at `ws://localhost:<ws_port>/mqtt` — default 9002
- TCP MQTT at `tcp://localhost:<tcp_port>` — default 1884
- All values are configurable via `config/broker.config.json`

## REST API
- `GET /api/config` → returns `houston.config.json`
- `PUT /api/config` → replace config; body: JSON
- `GET /api/broker` → broker status + broker config (ports, clients)

## Notes
- The UI connects to the broker via WebSocket (mqtt.js). If you change ports/paths, update `config/broker.config.json` or override using the UI settings.
- Mission overlays appear as soon as a root mission upload is received. GPS is optional for overlays but improves marker positioning. Heartbeats drive the alive pulse.
- Pathfinder publishes an aggregated state at `wayfarer/v1/pathfinder/sysid_<id>/state` to aid the UI.
