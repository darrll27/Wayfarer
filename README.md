# wayfarer
MQTT universal bridge to hardware

# Wayfarer

**Wayfarer** is a lightweight, discovery-driven hardware bridge for software telemetry.
- MAVLink ⇄ MQTT (two-way)
- Device-first (no per-device config; auto discovery)
- Topic model with `telem/` and `cmd/` separation
- Minimal dependencies

## Quickstart

```bash
pip install -e .
wayfarer --config examples/config.min.yaml


# Filetree
```
wayfarer/
├─ pyproject.toml
├─ README.md
├─ LICENSE
├─ examples/
│  └─ config.min.yaml
└─ wayfarer/
    ├─ __init__.py
    ├─ cli/
    │  └─ main.py
    ├─ core/
    │  ├─ bridge.py
    │  ├─ registry.py
    │  ├─ packet.py
    │  ├─ router.py
    │  ├─ constants.py
    │  └─ metrics.py
    ├─ config/
    │  └─ loader.py
    ├─ transports/
    │  ├─ base.py
    │  └─ mavlink_udp.py
    └─ routers/
        ├─ base.py
        └─ mqtt_router.py
```

## Pathfinder (mission launcher)

The repository includes a small mission launcher under the `pathfinder/` folder. This is a lightweight CLI that loads a `pathfinder` YAML config, injects sensible MQTT defaults when the config doesn't include an `mqtt:` section, and then launches group missions.

Usage examples

- Print the effective config (merged with defaults):

```bash
python pathfinder/main.py -c pathfinder/pathfinder.config_single.yaml
```

- Run missions immediately (explicit run flag):

```bash
python pathfinder/main.py -c pathfinder/pathfinder.config_single.yaml --run
```

- Run using the default `pathfinder/pathfinder.config.yaml` (no args):

```bash
python pathfinder/main.py
```

Notes
- If you pass `-c <file>` the CLI will print the effective config (merged with in-memory defaults) unless you also pass `--run`. This was intentional to make it simple to inspect the merged configuration before launching.
- When a config is missing an `mqtt:` block, `main.py` injects defaults (host: `localhost`, port: `1883`, topic_prefix: `wayfarer/v1`, `client_id: pathfinder-controller`, `qos: 0`). In some versions `main.py` writes a local `pathfinder/.effective_pathfinder.yaml` file; it is safe to remove and can be added to `.gitignore` if you don't want it in the working tree.
- `launch_missions.py` launches one process per configured group and reads the given config file path. If you need customized behavior (in-memory merging or temporary overrides) those are handled by `main.py` before delegating to `launch_missions.main()`.

If you want, I can (a) change `main.py` so `-c` implies `--run`, (b) stop writing `.effective_pathfinder.yaml` and use a system temp file instead, or (c) add a short troubleshooting section showing common errors (manifest missing, MQTT connect issues). Tell me which you prefer and I'll apply it.
