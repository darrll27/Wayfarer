# Nomad backend CLI — quick guide

This CLI is a lightweight tool to exercise backend functionality without the Electron UI.

Dependencies
- Python 3.8+
- Install packages (recommended in a venv):

```bash
python -m venv .venv
source .venv/bin/activate
pip install paho-mqtt PyYAML
```

Files
- `backend/cli.py` — main CLI. Commands: `arm`, `set-mode`, `get-mission`, `load-waypoints`, `listen`.
- `backend/config_manager.py` — loads `config/Config.yaml` if present and provides defaults.

Examples

Publish an arm command (arm):

```bash
python backend/cli.py arm --target 3:1 --arm
```

Request mission list from a vehicle:

```bash
python backend/cli.py get-mission --target 3:1
```

Load waypoints (reads YAML and publishes `command/<sysid>/<compid>/load_waypoints`):

```bash
python backend/cli.py load-waypoints --target 3:1 --file groups/teamA/waypoints.yaml
```

Listen to device topics (helpful for observing `device/...` messages):

```bash
python backend/cli.py listen --topic "device/+/+/HEARTBEAT/#"
```

Notes
- The CLI publishes messages following the project's MQTT topic contract (see `instructions.md`).
- It assumes an MQTT broker is reachable at the address in `config/Config.yaml` or on `localhost:1883` by default.
- This is intentionally lightweight: the CLI's job is to generate the same MQTT messages the UI would, so you can troubleshoot the router and validator without the frontend.

If you'd like, I can extend the CLI to also support direct UDP MAVLink send (using pymavlink) so tests can run without an MQTT broker.
