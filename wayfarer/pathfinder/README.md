# Pathfinder — mission controller (sister module to Wayfarer)

What is Pathfinder
- Pathfinder groups vehicles by sysid and uploads/starts missions via MQTT.
- It relies on a Wayfarer bridge to expose canonical MQTT topics; Pathfinder discovers those topics via a retained manifest published by Wayfarer at {topic_prefix}/bridge/manifest.

Key files
- pathfinder.config.yaml — controller config (groups, default waypoints_folder, global waypoint_type, optional mqtt settings).
- waypoints/ — contains subfolders for waypoint types (e.g. `absolute/` and `relative/`) with files named `<base>.yaml` (e.g. `alpha.yaml`, `beta.yaml`).
- mission_api.py — the mission runner: resolves waypoint files, fetches the Wayfarer manifest, uploads missions and issues commands.
- launch_missions.py — spawns one process per group and runs mission_api in parallel.

Config basics (pathfinder.config.yaml)
- waypoints_folder: default folder for waypoint files (relative to the pathfinder folder).
- waypoint_type: global default ("absolute" or "relative"), group-level `waypoint_type` overrides.
- groups:
  - each group entry maps to a waypoint filename derived from the group name (base = part before first underscore).
  - groups must list sysids.

Waypoints layout (convention)
- pathfinder/waypoints/absolute/<base>.yaml — GPS (lat/lon/alt) waypoints.
- pathfinder/waypoints/relative/<base>.yaml — local NED (x,y,z) waypoints.
- Each file must include a top-level `waypoints:` array (mission_api expects that).

Manifest dependency (how Pathfinder chooses topics)
- Pathfinder requires the Wayfarer bridge manifest (retained) at {topic_prefix}/bridge/manifest.
- The manifest includes canonical topic patterns (mission_upload, device_cmd, command_long, global_cmd, discovery, heartbeat).
- mission_api will fetch the manifest on startup, cache it to `.cache/wayfarer_manifest.json`, and use the manifest to format topics.
- If a live manifest is fetched and differs from the cache, the cache is updated and a message is printed.

Mission upload API (root‑level)
- Topic: `{topic_prefix}/mission/upload` (root; not per‑sysid)
- Payload: `{ sysid: <number>, mission_items: [ { lat, lon, alt, ... }, ... ] }`
- Reasoning: Houston (the UI) subscribes once at the root to render overlays for all vehicles. Wayfarer consumes the root topic and routes per device.

Behavior summary
- On startup mission_api:
  - loads pathfinder.config.yaml
  - fetches and validates the Wayfarer manifest (abort if missing required patterns)
  - resolves waypoint file for each group (waypoints_folder + waypoint_type + <base>.yaml)
  - uploads mission to the root mission topic (one publish per sysid in the group)
  - issues preflight/arm/takeoff/start commands (per sysid), with a small stagger (~1s) between vehicles to avoid bursts
  - continues publishing an aggregated state for UI convenience (group, sysid, checkpoint, lat/lon/alt, t)

Running Pathfinder (example)
- From the repo:
  - python pathfinder/launch_missions.py
  - or run the processes programmatically; launch_missions reads pathfinder.config.yaml and starts each group in its own process.

Example logs you will see
- "[alpha] bridge manifest fetched and cache updated at .../.cache/wayfarer_manifest.json"
- "[alpha] mission_upload topic (root): wayfarer/v1/mission/upload"
- "[alpha] using device_cmd for takeoff: wayfarer/v1/devices/mav_sys1/cmd/takeoff"

Quickstart
- Ensure Houston is running (broker + UI) on localhost (HTTP 4000, WS MQTT 9002/mqtt, TCP MQTT 1884)
- Start Wayfarer
- Run Pathfinder with your config:
  - `python pathfinder/main.py -c pathfinder/pathfinder.config.yaml --run`
  - Or: `python pathfinder/launch_missions.py`

UI integration (Houston)
- Houston auto‑renders overlays upon receiving the root mission uploads; it keeps a mission cache (~10 minutes) so overlays persist without inbound GPS.
- Heartbeats (from Wayfarer device topics) drive the alive pulse; GPS and MISSION_CURRENT refine position and checkpoint highlighting.

Troubleshooting
- If mission_api aborts with "bridge manifest not found", ensure Wayfarer is running and publishing a retained manifest at {topic_prefix}/bridge/manifest.
- Check `.cache/wayfarer_manifest.json` for a cached manifest used as fallback.
- Confirm waypoint files exist at pathfinder/waypoints/<type>/<base>.yaml and contain top-level `waypoints:`.

Notes / Recommendations
- Wayfarer and Pathfinder are separate APIs. Keep Wayfarer responsible for bridge/transport concerns and publishing the canonical manifest. Pathfinder should not hardcode topics — it should use the manifest.
- If you want tolerant fallback behavior, run Wayfarer first so Pathfinder caches the manifest before missions are started.
- Prefer absolute missions (lat/lon/alt) if you want overlays in the UI; relative paths can be supported via a configured origin transform.

