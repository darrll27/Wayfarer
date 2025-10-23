# Wayfarer — MQTT bridge, Pathfinder mission controller, and Houston dashboard

This repo contains three pieces that work together:

- Wayfarer: Lightweight discovery‑driven MAVLink⇄MQTT bridge (Python)
- Pathfinder: Mission controller that uploads missions and issues commands via MQTT (Python)
- Houston: Web telemetry dashboard with a built‑in MQTT broker (Node/React)

Highlights
- Device‑first topics (auto‑discovery; no per‑device config)
- Clean topic model: `telem/` for telemetry, `cmd/` for commands
- Canonical mission upload API at the root: `{topic_prefix}/mission/upload`
- Map overlays in Houston: mission paths, current checkpoint, labels (group · sysid), and a sysid picker with a mission debug panel

## Quick start

1) Start Houston (broker + UI)

```bash
cd Houston
npm install
npm run build
npm run start    # HTTP:4000, WS MQTT:9002/mqtt, TCP MQTT:1884
```

Open http://localhost:4000

2) Start Wayfarer (bridge)

```bash
pip install -e .
wayfarer -c examples/wayfarer.config.houston.yaml
```

3) Launch Pathfinder (mission controller)

```bash
python pathfinder/main.py -c pathfinder/pathfinder.config.yaml --run
```

## Topics (minimal)

- Mission upload (root, required for overlays)
    - Topic: `{prefix}/mission/upload`
    - Payload: `{ sysid: <number>, mission_items: [ { lat, lon, alt, ... }, ... ] }`

- Heartbeat (alive)
    - Topic: `{prefix}/devices/mav_sys<sysid>/telem/state/heartbeat`
    - Payload: `{}`

- GPS (any of):
    - `{prefix}/devices/mav_sys<sysid>/telem/raw/mavlink/GLOBAL_POSITION_INT`
    - `{prefix}/devices/mav_sys<sysid>/telem/raw/mavlink/GPS_RAW_INT`
    - `{prefix}/devices/mav_sys<sysid>/telem/raw/mavlink/GPS2_RAW`

- Current checkpoint (optional)
    - `{prefix}/devices/mav_sys<sysid>/telem/raw/mavlink/MISSION_CURRENT`
    - `{ seq: <number> }`

- Aggregated Pathfinder state (optional visual aid)
    - `{prefix}/pathfinder/sysid_<sysid>/state`
    - `{ group, sysid, checkpoint, lat, lon, alt, t }`

## Simulate telemetry quickly

Publish these while Houston is open to see a localized, alive drone with overlays:

- Mission upload
    - Topic: `wayfarer/v1/mission/upload`
    - Payload:
        ```json
        { "sysid": 6, "mission_items": [
            { "lat": 37.412545, "lon": -121.998,   "alt": 52 },
            { "lat": 37.413045, "lon": -121.9982, "alt": 57 },
            { "lat": 37.413545, "lon": -121.9984, "alt": 61 },
            { "lat": 37.414045, "lon": -121.9986, "alt": 54 }
        ]}
        ```

- Heartbeat
    - Topic: `wayfarer/v1/devices/mav_sys6/telem/state/heartbeat`
    - Payload: `{}`

- GPS
    - Topic: `wayfarer/v1/devices/mav_sys6/telem/raw/mavlink/GLOBAL_POSITION_INT`
    - Payload: `{ "lat": 37.4219999, "lon": -122.0840575, "alt": 32.1 }`

- Current checkpoint (optional)
    - Topic: `wayfarer/v1/devices/mav_sys6/telem/raw/mavlink/MISSION_CURRENT`
    - Payload: `{ "seq": 0 }`

## Component docs

- Houston: `houston/README.md` — broker ports, pages, and UI details (Map overlays, sysid picker, debug panel)
- Wayfarer: `wayfarer/README.md` — bridge topics and config
- Pathfinder: `pathfinder/README.md` — groups, waypoints, mission upload behavior

## Notes
- Mission uploads are not retained by default; keep Houston open to cache overlays (Houston keeps mission cache for 10 minutes).
- Overlays require absolute waypoints (lat/lon). Relative‑only missions won’t draw yet; can be enabled with an origin transform.
