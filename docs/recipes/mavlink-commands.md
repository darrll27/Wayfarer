# MQTT command examples for MAVLink ✈️

This page shows practical MQTT payloads you can publish to control a MAVLink device through Wayfarer. It complements the main README with copy‑pasteable examples.

## Topic shape

- Base: `wayfarer/v1/devices/<device_id>/cmd/...`
- Only `<device_id>` is parsed (e.g., `mav_sys1`). The rest of the topic under `cmd/` is free‑form and purely for organization, e.g., `cmd/flight/arm`.

## Payload shape

- JSON object mapped to a Wayfarer `Packet` and then to pymavlink calls
- Required fields:
  - `schema`: "mavlink"
  - `msg_type`: e.g., "COMMAND_LONG", "SET_MODE"
- Common optional fields:
  - `command`: MAV_CMD name (e.g., `MAV_CMD_COMPONENT_ARM_DISARM`) or numeric ID
  - `params`: list of up to 7 numbers (missing items default to 0)
  - `target_sysid`, `target_compid` (default 1/1 if omitted)

## COMMAND_LONG: Arm

Topic:
```
wayfarer/v1/devices/mav_sys1/cmd/flight/arm
```

Payload:
```json
{
  "schema": "mavlink",
  "msg_type": "COMMAND_LONG",
  "command": "MAV_CMD_COMPONENT_ARM_DISARM",
  "params": [1, 0, 0, 0, 0, 0, 0],
  "target_sysid": 1,
  "target_compid": 1
}
```

Notes:
- You can also use `"COMPONENT_ARM_DISARM"` or the numeric ID `400`.
- `params[0] = 1` arms, `0` disarms.

## COMMAND_LONG: Disarm

```json
{
  "schema": "mavlink",
  "msg_type": "COMMAND_LONG",
  "command": "MAV_CMD_COMPONENT_ARM_DISARM",
  "params": [0, 0, 0, 0, 0, 0, 0],
  "target_sysid": 1,
  "target_compid": 1
}
```

## SET_MODE

```json
{
  "schema": "mavlink",
  "msg_type": "SET_MODE",
  "target_sysid": 1,
  "base_mode": 209,
  "custom_mode": 4
}
```

- `base_mode` is a bitmask; `209` is a common value for copters (ARMED | GUIDED | ...). Adjust to your stack.
- `custom_mode` is autopilot-specific (e.g., ArduPilot modes). Use values appropriate for your system.

## Tips

- If you don’t know your `<device_id>`, look at discovery topics under `wayfarer/v1/devices/*/telem/state/discovery`.
- When publishing via `mosquitto_pub`, you can keep payloads in a file:

```sh
# macOS / zsh example
mosquitto_pub -h localhost -t "wayfarer/v1/devices/mav_sys1/cmd/flight/arm" -f arm.json
```

- “Raw” byte writes are supported in transports when `fields.raw` is a bytes object, but over MQTT JSON you should prefer structured commands like above.

## Troubleshooting

- Error like `send_command() failed: 'MAV_CMD_...'` → ensure the command string is a valid MAV_CMD name or use the numeric ID. Wayfarer accepts both `MAV_CMD_*` and no‑prefix names (e.g., `COMPONENT_ARM_DISARM`).
- No effect on vehicle → verify `target_sysid/compid`, link state, and that your autopilot accepts the command in the current mode.

---

If you need more recipes (e.g., takeoff, RTL, DO_SET_MODE), open an issue or add a PR to extend this page.
