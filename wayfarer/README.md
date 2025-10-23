# Wayfarer — MAVLink ⇄ MQTT bridge

Wayfarer bridges MAVLink vehicles to MQTT topics and exposes a retained manifest so controllers (e.g., Pathfinder) and UIs (Houston) can discover canonical topics.

What it does
- Subscribes to transports (UDP/serial) and parses MAVLink packets
- Publishes telemetry under device topics: `.../devices/mav_sys<sysid>/telem/...`
- Listens for commands: `.../devices/mav_sys<sysid>/cmd/...` and system‑wide `.../cmd/...`
- Handles mission uploads from a single, root topic: `{prefix}/mission/upload`
- Publishes a retained bridge manifest at `{prefix}/bridge/manifest`

Key topics
- Bridge manifest (retained)
  - `{prefix}/bridge/manifest` → JSON with patterns: `mission_upload`, `device_cmd`, `global_cmd`, `discovery`, `heartbeat`

- Device telemetry
  - Heartbeat: `{prefix}/devices/mav_sys<sysid>/telem/state/heartbeat`
  - Raw MAVLink: `{prefix}/devices/mav_sys<sysid>/telem/raw/mavlink/<MSG_NAME>`

- Commands
  - Per device: `{prefix}/devices/mav_sys<sysid>/cmd/<verb>`
  - Command‑long: `{prefix}/devices/mav_sys<sysid>/cmd/command_long`
  - Global/system: `{prefix}/cmd/<verb>`

- Mission upload (root)
  - Topic: `{prefix}/mission/upload`
  - Payload: `{ sysid: <number>, mission_items: [ { lat, lon, alt, ... }, ... ] }`

Config
- Use the example at `examples/config.min.yaml` or `examples/wayfarer.config.yaml`
- Most deployments run Wayfarer against the Houston broker defaults (HTTP 4000, WS 9002, TCP 1884). If you use Houston, point Wayfarer to those ports.

CLI
- Install: `pip install -e .`
- Run: `wayfarer -c examples/config.min.yaml`

Notes
- The manifest is retained and should be available before Pathfinder starts.
- If you need different topic prefixes, set `topic_prefix` consistently across Wayfarer, Pathfinder, and Houston.
