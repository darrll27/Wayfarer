"""MQTT adapter bridging router/transports with the MQTT broker.

Publishes incoming raw packets (from mqtt_pub_q) to `sources/.../RAW/<port>`
and `device/.../RAW` topics and subscribes to `command/+/+/details` and
`command/+/+/load_waypoints` to inject commands into transport out queues.
"""
from __future__ import annotations

import json
import threading
import time
import warnings
from multiprocessing import Queue
from typing import Dict, Any

import paho.mqtt.client as mqtt
# pymavlink parser will be used to decode messages for rich MQTT topics
try:
    from pymavlink import mavutil
    _MAVLINK_PARSER_AVAILABLE = True
except Exception:
    mavutil = None
    _MAVLINK_PARSER_AVAILABLE = False

from . import mavlink_encoder
from backend.waypoint_validator import validator as waypoint_validator


class MQTTAdapter:
    def __init__(self, cfg: dict, ports: Dict[str, Dict], router, mqtt_pub_q: Queue):
        self.cfg = cfg
        self.ports = ports
        self.router = router
        self.mqtt_pub_q = mqtt_pub_q
        self.client = mqtt.Client()
        if cfg["mqtt"].get("username"):
            self.client.username_pw_set(cfg["mqtt"].get("username"), cfg["mqtt"].get("password"))

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        self._stop = threading.Event()
        # track when adapter started to report uptime
        self._start_time = time.time()
        # pending commands keyed by target_sys -> list of tuples (topic, out_bytes)
        self.pending_commands: Dict[int, list] = {}
        self._status_thread = None
        # publish fields control: per-field publishes under device/<MSG>/<field>
        # This can inflate device-topic counts relative to sources; default OFF.
        self._publish_fields = bool(self.cfg.get("mqtt", {}).get("publish_fields", False))
        # debug flag to print per-packet publish counts (very verbose when enabled)
        self._debug_publish_counts = bool(self.cfg.get("mqtt", {}).get("debug_publish_counts", False))
        # simple publish counters
        self._total_publishes = 0
        # MAVLink parser factory (we create a fresh parser per-packet later)
        if _MAVLINK_PARSER_AVAILABLE:
            try:
                self._mav_parser_factory = mavutil.mavlink.MAVLink
            except Exception:
                self._mav_parser_factory = None
        else:
            self._mav_parser_factory = None

    def start(self):
        self.client.connect(self.cfg["mqtt"]["host"], self.cfg["mqtt"]["port"], self.cfg["mqtt"].get("keepalive", 60))
        # start MQTT network loop in a background thread
        t = threading.Thread(target=self.client.loop_forever, daemon=True)
        t.start()
        # start publisher loop
        self.pub_thread = threading.Thread(target=self._pub_loop, daemon=True)
        self.pub_thread.start()
        # start pending delivery thread
        self.pending_thread = threading.Thread(target=self._pending_loop, daemon=True)
        self.pending_thread.start()
        # start status publisher thread
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

    def stop(self):
        self._stop.set()
        try:
            self.client.disconnect()
        except Exception:
            pass

    def on_connect(self, client, userdata, flags, rc):
        print("[mqtt_adapter] connected to broker, subscribing to command topics")
        client.subscribe("command/+/+/details")
        client.subscribe("command/+/+/load_waypoints")
        # publish a summary of loaded config so UIs can pick it up
        try:
            cfg_summary = {
                "mqtt": self.cfg.get("mqtt", {}),
                "transports": self.cfg.get("transports", []),
                "gcs_sysid": self.cfg.get("gcs_sysid"),
                "gcs_compid": self.cfg.get("gcs_compid"),
            }
            client.publish("Nomad/config", json.dumps(cfg_summary))
        except Exception:
            pass

    def on_message(self, client, userdata, msg):
        # route commands into transport out queues
        topic = msg.topic
        parts = topic.split("/")
        if len(parts) >= 4 and parts[0] == "command":
            try:
                target_sys = int(parts[1])
                target_comp = int(parts[2])
            except Exception:
                return
            payload = msg.payload.decode("utf-8")
            try:
                data = json.loads(payload)
            except Exception:
                data = payload

            # special action: load_waypoints -> validate waypoint file and publish validation result
            if isinstance(data, dict) and data.get("action") == "load_waypoints":
                filename = data.get("filename") or data.get("name") or "unnamed.yaml"
                waypoints = data.get("waypoints") or data.get("mission")
                ok, details, norm = waypoint_validator.validate_waypoints(waypoints)
                # compute a lightweight hash of the normalized canonical form
                try:
                    import json as _json

                    norm_bytes = _json.dumps(norm, sort_keys=True).encode("utf-8")
                    h = waypoint_validator.compute_hash_bytes(norm_bytes)
                except Exception:
                    h = ""

                val_topic = f"Nomad/waypoints/{filename}/validation"
                val_payload = json.dumps({"ok": ok, "details": details, "hash": h, "filename": filename})
                try:
                    self.client.publish(val_topic, val_payload)
                except Exception:
                    pass
                # ACK back to command topic with validation result (do not run tests or initiate uploads automatically)
                try:
                    client.publish(f"command/{parts[1]}/{parts[2]}/ack", json.dumps({"status": "validated", "ok": ok, "details": details, "hash": h}))
                except Exception:
                    pass
                return

            # find port where target sysid was observed
            dest_port = None
            for p, seen in self.router.observed_sysids.items():
                if target_sys in seen:
                    dest_port = p
                    break

            if dest_port is None:
                # no known port for target; queue for later delivery
                print(f"[mqtt_adapter] no transport port known for target sysid {target_sys}; queueing")
                self.pending_commands.setdefault(target_sys, []).append((topic, data))
                return

            dest_addr = self.router.last_addr.get(dest_port)
            if dest_addr is None:
                print(f"[mqtt_adapter] no last_addr for port {dest_port}; cannot send")
                return

            # if payload is a JSON command describing a MAVLink message, try encoding
            out_bytes = None
            try:
                if isinstance(data, dict) and (data.get("msg") == "COMMAND_LONG" or data.get("type") == "COMMAND_LONG"):
                    # expected schema: {"msg":"COMMAND_LONG","target_sys":1,"target_comp":1,"command":400,"params":[...]} 
                    tgt_sys = int(data.get("target_sys", target_sys))
                    tgt_comp = int(data.get("target_comp", target_comp))
                    cmd = int(data.get("command"))
                    params = data.get("params", [])
                    out_bytes = mavlink_encoder.encode_command_long(tgt_sys, tgt_comp, cmd, params)
                    print(f"[mqtt_adapter] encoded COMMAND_LONG -> {len(out_bytes)} bytes")
                    # after encoding, publish an ACK to the command topic
                    try:
                        ack_topic = f"command/{tgt_sys}/{tgt_comp}/ack"
                        ack_payload = json.dumps({"status": "encoded", "msg": "COMMAND_LONG", "bytes": len(out_bytes)})
                        self.client.publish(ack_topic, ack_payload)
                    except Exception:
                        pass
                elif isinstance(data, dict) and (data.get("msg") == "MISSION_ITEM_INT" or data.get("type") == "MISSION_ITEM_INT"):
                    # expected schema: {"msg":"MISSION_ITEM_INT","target_sys":1,"target_comp":1,"seq":0,"frame":0,"command":16,"x":...,"y":...,"z":...,"params":[...]} 
                    tgt_sys = int(data.get("target_sys", target_sys))
                    tgt_comp = int(data.get("target_comp", target_comp))
                    seq = int(data.get("seq", 0))
                    frame = int(data.get("frame", 0))
                    cmd = int(data.get("command", 16))
                    x = int(data.get("x", 0))
                    y = int(data.get("y", 0))
                    z = float(data.get("z", 0.0))
                    params = data.get("params", [])
                    out_bytes = mavlink_encoder.encode_mission_item_int(tgt_sys, tgt_comp, seq, frame, cmd, params=params, x=x, y=y, z=z)
                    print(f"[mqtt_adapter] encoded MISSION_ITEM_INT -> {len(out_bytes)} bytes")
                    try:
                        ack_topic = f"command/{tgt_sys}/{tgt_comp}/ack"
                        ack_payload = json.dumps({"status": "encoded", "msg": "MISSION_ITEM_INT", "bytes": len(out_bytes), "seq": seq})
                        self.client.publish(ack_topic, ack_payload)
                    except Exception:
                        pass
                else:
                    # fallback: encode as JSON bytes and let transports handle it
                    out_bytes = json.dumps({"topic": topic, "payload": data}).encode("utf-8")
            except Exception as e:
                print(f"[mqtt_adapter] failed to encode MAVLink message: {e}; falling back to JSON payload")
                out_bytes = json.dumps({"topic": topic, "payload": data}).encode("utf-8")
            try:
                self.ports[dest_port]["out_q"].put((dest_addr, out_bytes))
                print(f"[mqtt_adapter] injected command for {target_sys} into port {dest_port} -> {dest_addr}")
            except Exception as e:
                print("[mqtt_adapter] failed to inject into out_q:", e)

    def _pub_loop(self):
        # Publish incoming packets from transports to MQTT topics
        while not self._stop.is_set():
            try:
                name, addr, data = self.mqtt_pub_q.get(timeout=0.5)
            except Exception:
                continue
            # try to decode MAVLink properly (use pymavlink parser if available)
            src_sys = None
            src_comp = None
            decoded_any = False
            try:
                if self._mav_parser_factory is not None and data:
                    # create a fresh parser for this packet and feed bytes until a message is produced
                    try:
                        parser = self._mav_parser_factory(None)
                    except Exception:
                        parser = None
                    msg_obj = None
                    if parser is not None:
                        for b in data:
                            try:
                                # parser.parse_char in some pymavlink builds expects a bytes object
                                m = parser.parse_char(bytes([b]))
                            except Exception:
                                m = None
                            if m is not None:
                                msg_obj = m
                                break

                    if msg_obj is not None:
                        # basic sanity checks: ensure parser returned a useful message
                        msg_type_probe = getattr(msg_obj, 'get_type', lambda: None)()
                        # try to obtain a fields dict; many pymavlink message objects expose to_dict()
                        try:
                            probe_fields = msg_obj.to_dict() if hasattr(msg_obj, 'to_dict') else {k: v for k, v in vars(msg_obj).items() if not k.startswith('_')}
                        except Exception:
                            probe_fields = {}

                        if not msg_type_probe or msg_type_probe == 'UNKNOWN' or not probe_fields:
                            # treat as parse failure so we fall back to header extraction and RAW publish
                            # one-time debug print to help diagnose unexpected parser returns
                            if getattr(self, '_warned_parser_empty', False) is False:
                                try:
                                    print(f"[mqtt_adapter] pymavlink parser returned an empty/unknown message for packet from {addr}; falling back to RAW publish. sample_bytes={data[:16].hex()}")
                                except Exception:
                                    pass
                                self._warned_parser_empty = True
                            msg_obj = None
                        else:
                            decoded_any = True
                        # obtain src sys/comp from the message header when available
                        try:
                            src_sys = int(getattr(msg_obj, 'srcSystem', None) or getattr(msg_obj, 'get_srcSystem', lambda: None)() or 0)
                        except Exception:
                            src_sys = None
                        try:
                            src_comp = int(getattr(msg_obj, 'srcComponent', None) or getattr(msg_obj, 'get_srcComponent', lambda: None)() or 0)
                        except Exception:
                            src_comp = None

                        # fallback: try to read header bytes for v1/v2
                        if src_sys is None or src_comp is None:
                            if len(data) >= 7 and mavlink_encoder.is_mavlink2_packet(data):
                                src_sys = src_sys or data[5]
                                src_comp = src_comp or data[6]
                            elif len(data) >= 6 and data[0] == 0xFE:
                                src_sys = src_sys or data[3]
                                src_comp = src_comp or data[4]

                        # convert message fields to a plain dict
                        try:
                            if hasattr(msg_obj, 'to_dict'):
                                fields = msg_obj.to_dict()
                            else:
                                # generic fallback: take public attrs
                                fields = {k: v for k, v in vars(msg_obj).items() if not k.startswith('_')}
                        except Exception:
                            fields = {}

                        msg_type = getattr(msg_obj, 'get_type', lambda: None)()
                        if msg_type is None:
                            msg_type = getattr(msg_obj, 'name', 'UNKNOWN')

                        # determine destination system/component if present in payload fields
                        dest_sys = int(fields.get('target_system', 0) or fields.get('target_sys', 0) or 0)
                        dest_comp = int(fields.get('target_component', 0) or fields.get('target_comp', 0) or 0)

                        # publish full JSON document for this msg using labeled topic segments
                        sus = src_sys or 0
                        suc = src_comp or 0
                        dus = dest_sys or 0
                        duc = dest_comp or 0
                        device_topic_base = f"device/sysid_{sus}/compid_{suc}/{msg_type}"
                        device_publishes = 0
                        source_publishes = 0
                        try:
                            self.client.publish(device_topic_base, json.dumps({"fields": fields, "src_addr": addr, "port": name}))
                            device_publishes += 1
                        except Exception:
                            pass

                        # publish each field individually as device/sysid_<n>/compid_<m>/<MSG>/<field>
                        if self._publish_fields:
                            for k, v in (fields or {}).items():
                                try:
                                    self.client.publish(f"{device_topic_base}/{k}", json.dumps(v))
                                    device_publishes += 1
                                except Exception:
                                    pass

                        # publish the source-oriented topic using labeled segments
                        source_topic = f"sources/source_sysid_{sus}/source_compid_{suc}/dest_sysid_{dus}/dest_compid_{duc}/{msg_type}/{name}"
                        try:
                            self.client.publish(source_topic, json.dumps({"fields": fields, "src_addr": addr}))
                            source_publishes += 1
                        except Exception:
                            pass

                        # debug: optionally log per-packet publish counts
                        if self._debug_publish_counts:
                            try:
                                print(f"[mqtt_adapter] packet from {addr} (port={name}) msg={msg_type} -> device_publishes={device_publishes} source_publishes={source_publishes}")
                            except Exception:
                                pass
                        self._total_publishes += device_publishes + source_publishes

                # if parser not available or decode failed, fall back to old RAW topics
            except Exception:
                decoded_any = False

            if not _MAVLINK_PARSER_AVAILABLE:
                # quick info to help debugging when pymavlink isn't present
                # (avoid spamming logs every packet)
                if hasattr(self, '_warned_no_parser') is False:
                    print("[mqtt_adapter] pymavlink not available; publishing RAW packets only")
                    self._warned_no_parser = True

            if not decoded_any:
                # try to minimally parse sysid/compid from raw header
                src_sys = None
                src_comp = None
                if data and len(data) >= 6:
                    if mavlink_encoder.is_mavlink2_packet(data):
                        if len(data) >= 7:
                            src_sys = data[5]
                            src_comp = data[6]
                    elif data[0] == 0xFE and len(data) >= 6:
                        src_sys = data[3]
                        src_comp = data[4]
                        warnings.warn("Received MAVLink v1 packet; this system prefers v2 — some features may not work", UserWarning)
                    else:
                        warnings.warn("Received packet that does not appear to be MAVLink v2 or v1; payload will be published as hex", UserWarning)
                # attempt minimal manual decode for common messages (HEARTBEAT) when parser failed
                try:
                    manual_decoded = False
                    if data and data[0] == 0xFE and len(data) >= 6:
                        payload_len = data[1]
                        # v1 header: [0]=0xFE,[1]=len,[2]=seq,[3]=sysid,[4]=compid,[5]=msgid
                        if len(data) >= 6 + payload_len:
                            msgid = data[5]
                            if msgid == 0 and payload_len >= 9:
                                # HEARTBEAT v1: custom_mode (uint32), type (uint8), autopilot (uint8), base_mode (uint8), system_status (uint8), mavlink_version (uint8)
                                payload = data[6 : 6 + payload_len]
                                try:
                                    custom_mode = int.from_bytes(payload[0:4], 'little', signed=False)
                                    hb_type = payload[4]
                                    hb_autopilot = payload[5]
                                    hb_base_mode = payload[6]
                                    hb_system_status = payload[7] if len(payload) > 7 else 0
                                    # build fields dict
                                    fields = {
                                        'custom_mode': custom_mode,
                                        'type': int(hb_type),
                                        'autopilot': int(hb_autopilot),
                                        'base_mode': int(hb_base_mode),
                                        'system_status': int(hb_system_status),
                                    }
                                    sus = src_sys or data[3]
                                    suc = src_comp or data[4]
                                    device_topic_base = f"device/sysid_{sus}/compid_{suc}/HEARTBEAT"
                                    device_publishes = 0
                                    source_publishes = 0
                                    try:
                                        self.client.publish(device_topic_base, json.dumps({"fields": fields, "src_addr": addr, "port": name}))
                                        device_publishes += 1
                                    except Exception:
                                        pass
                                    if self._publish_fields:
                                        for k, v in fields.items():
                                            try:
                                                self.client.publish(f"{device_topic_base}/{k}", json.dumps(v))
                                                device_publishes += 1
                                            except Exception:
                                                pass
                                    source_topic = f"sources/source_sysid_{sus}/source_compid_{suc}/0/0/HEARTBEAT/{name}"
                                    try:
                                        self.client.publish(source_topic, json.dumps({"fields": fields, "src_addr": addr}))
                                        source_publishes += 1
                                    except Exception:
                                        pass
                                    if self._debug_publish_counts:
                                        try:
                                            print(f"[mqtt_adapter] manual HEARTBEAT from {addr} (port={name}) -> device_publishes={device_publishes} source_publishes={source_publishes}")
                                        except Exception:
                                            pass
                                    self._total_publishes += device_publishes + source_publishes
                                    manual_decoded = True
                                except Exception:
                                    manual_decoded = False

                    if not manual_decoded:
                        topic_sources = f"sources/source_sysid_{src_sys or 0}/source_compid_{src_comp or 0}/0/0/RAW/{name}"
                        topic_device = f"device/sysid_{src_sys or 0}/compid_{src_comp or 0}/RAW"
                        payload = data.hex()
                        try:
                            self.client.publish(topic_sources, payload)
                            self.client.publish(topic_device, payload)
                        except Exception:
                            pass
                except Exception:
                    # on any unexpected error, ensure we still publish raw
                    try:
                        topic_sources = f"sources/source_sysid_{src_sys or 0}/source_compid_{src_comp or 0}/0/0/RAW/{name}"
                        topic_device = f"device/sysid_{src_sys or 0}/compid_{src_comp or 0}/RAW"
                        payload = data.hex()
                        self.client.publish(topic_sources, payload)
                        self.client.publish(topic_device, payload)
                    except Exception:
                        pass
                else:
                    # for readability in the branch where decoded_any is False but above logic not used
                    pass

    def _pending_loop(self):
        """Background loop that attempts to deliver pending commands when their
        target sysid becomes observed on a port.
        """
        while not self._stop.is_set():
            try:
                # snapshot keys to avoid mutation during iteration
                keys = list(self.pending_commands.keys())
                for target_sys in keys:
                    # find a port that has seen this sysid
                    dest_port = None
                    for p, seen in getattr(self.router, "observed_sysids", {}).items():
                        if target_sys in seen:
                            dest_port = p
                            break
                    if dest_port is None:
                        continue
                    dest_addr = getattr(self.router, "last_addr", {}).get(dest_port)
                    if dest_addr is None:
                        continue
                    items = list(self.pending_commands.get(target_sys, []))
                    for topic, data in items:
                        try:
                            # reuse the adapter encoding logic by constructing a fake msg
                            # but we already stored raw data dict; re-encode as needed
                            if isinstance(data, dict) and (data.get("msg") == "COMMAND_LONG" or data.get("type") == "COMMAND_LONG"):
                                tgt_sys = int(data.get("target_sys", target_sys))
                                tgt_comp = int(data.get("target_comp", 1))
                                cmd = int(data.get("command"))
                                params = data.get("params", [])
                                out_bytes = mavlink_encoder.encode_command_long(tgt_sys, tgt_comp, cmd, params)
                            elif isinstance(data, dict) and (data.get("msg") == "MISSION_ITEM_INT" or data.get("type") == "MISSION_ITEM_INT"):
                                tgt_sys = int(data.get("target_sys", target_sys))
                                tgt_comp = int(data.get("target_comp", 1))
                                seq = int(data.get("seq", 0))
                                frame = int(data.get("frame", 0))
                                cmd = int(data.get("command", 16))
                                x = int(data.get("x", 0))
                                y = int(data.get("y", 0))
                                z = float(data.get("z", 0.0))
                                params = data.get("params", [])
                                out_bytes = mavlink_encoder.encode_mission_item_int(tgt_sys, tgt_comp, seq, frame, cmd, params=params, x=x, y=y, z=z)
                            else:
                                out_bytes = json.dumps({"topic": topic, "payload": data}).encode("utf-8")

                            self.ports[dest_port]["out_q"].put((dest_addr, out_bytes))
                            # publish ACK
                            try:
                                ack_topic = f"command/{target_sys}/{data.get('target_comp', 0)}/ack"
                                ack_payload = json.dumps({"status": "delivered", "topic": topic})
                                self.client.publish(ack_topic, ack_payload)
                            except Exception:
                                pass
                        except Exception:
                            # leave it pending for next attempt
                            continue
                    # after attempting all, remove pending entry
                    if target_sys in self.pending_commands:
                        del self.pending_commands[target_sys]
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)

    def _status_loop(self):
        """Periodically publish a small status message on `nomad/status` so the UI
        can observe backend liveness and basic metadata.
        """
        while not self._stop.is_set():
            try:
                uptime = time.time() - self._start_time
                payload = {
                    "status": "ok",
                    "ts": int(time.time()),
                    "uptime_s": int(uptime),
                    "observed_ports": list(getattr(self.router, 'observed_sysids', {}).keys()),
                    "total_publishes": int(getattr(self, '_total_publishes', 0)),
                }
                try:
                    self.client.publish("nomad/status", json.dumps(payload))
                except Exception:
                    # broker may be temporarily unavailable; ignore
                    pass
            except Exception:
                pass
            # publish every 2 seconds
            time.sleep(2.0)


__all__ = ["MQTTAdapter"]
