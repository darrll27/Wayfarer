"""MQTT adapter bridging router/transports with the MQTT broker.

Publishes incoming raw packets (from mqtt_pub_q) to `sources/.../RAW/<port>`
and `device/.../RAW` topics and subscribes to `command/+/+/details` and
`command/+/+/load_waypoints` to inject commands into transport out queues.
"""
from __future__ import annotations

import json
import os
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
from backend.config_manager import resolve_endpoint


class MissionManager:
    """Handles mission upload/download operations with proper state management and verification."""

    # Seconds to wait for a response before retrying
    _ITEM_TIMEOUT = 2.0
    # Max retries per item request before falling back to non-INT, then giving up
    _MAX_RETRIES = 3

    def __init__(self, cfg: dict, router, ports: Dict[str, Dict], mqtt_client):
        self.cfg = cfg
        self.router = router
        self.ports = ports
        self.mqtt_client = mqtt_client

        # Upload states: sysid -> {'state', 'mission', 'sent', 'start_time', 'target_comp', 'expected_hash'}
        self.upload_states: Dict[int, Dict] = {}
        # Download states: sysid -> {'state', 'mission', 'start_time', 'target_comp'}
        self.download_states: Dict[int, Dict] = {}

        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def _watchdog_loop(self):
        """Background thread: retry stalled active downloads."""
        while True:
            time.sleep(1.0)
            try:
                self._check_stalled_downloads()
            except Exception as e:
                print(f"[mission_manager] watchdog error: {e}")

    def _check_stalled_downloads(self):
        now = time.time()
        src_sys = self.cfg.get("gcs_sysid", 255)
        src_comp = self.cfg.get("gcs_compid", 1)

        for sysid, state in list(self.download_states.items()):
            if state.get('mode') != 'active':
                continue
            if state.get('state') not in ('requesting_list', 'downloading'):
                continue

            last_activity = float(state.get('last_activity_ts') or state.get('start_time') or 0)
            if (now - last_activity) < self._ITEM_TIMEOUT:
                continue

            retries = int(state.get('retries', 0))
            compid = int(state.get('target_comp', 1))

            if state['state'] == 'requesting_list':
                # No MISSION_COUNT received — resend MISSION_REQUEST_LIST
                if retries >= self._MAX_RETRIES:
                    print(f"[mission_manager] giving up on download from {sysid} after {retries} retries (no MISSION_COUNT)")
                    self._publish_download_status(sysid, compid, 'failed', {'phase': 'mission_request_list', 'reason': 'timeout'})
                    state['state'] = 'failed'
                    continue
                print(f"[mission_manager] retry {retries+1}: resending MISSION_REQUEST_LIST to {sysid}")
                out_bytes = mavlink_encoder.encode_mission_request_list(sysid, compid, src_sys=src_sys, src_comp=src_comp)
                if self._send_to_drone(sysid, out_bytes):
                    state['retries'] = retries + 1
                    state['last_activity_ts'] = now
                    self._publish_download_status(sysid, compid, 'request_sent', {'phase': 'mission_request_list', 'retry': retries + 1})

            elif state['state'] == 'downloading':
                # Find the lowest seq we're still waiting for
                mission = state.get('mission') or []
                pending_seq = next((i for i, item in enumerate(mission) if item is None), None)
                if pending_seq is None:
                    continue  # all received, completion handled elsewhere

                use_non_int = retries >= self._MAX_RETRIES
                if retries >= self._MAX_RETRIES * 2:
                    print(f"[mission_manager] giving up on download from {sysid} seq={pending_seq} after {retries} retries")
                    self._publish_download_status(sysid, compid, 'failed', {'phase': 'mission_request_int', 'seq': pending_seq, 'reason': 'timeout'})
                    state['state'] = 'failed'
                    continue

                if use_non_int:
                    print(f"[mission_manager] retry {retries+1}: falling back to MISSION_REQUEST (non-INT) for {sysid} seq={pending_seq}")
                    out_bytes = mavlink_encoder.encode_mission_request(sysid, compid, pending_seq, src_sys=src_sys, src_comp=src_comp)
                    phase = 'mission_request'
                else:
                    print(f"[mission_manager] retry {retries+1}: resending MISSION_REQUEST_INT to {sysid} seq={pending_seq}")
                    out_bytes = mavlink_encoder.encode_mission_request_int(sysid, compid, pending_seq, src_sys=src_sys, src_comp=src_comp)
                    phase = 'mission_request_int'

                if self._send_to_drone(sysid, out_bytes):
                    state['retries'] = retries + 1
                    state['last_activity_ts'] = now
                    self._publish_download_status(sysid, compid, 'request_sent', {'phase': phase, 'seq': pending_seq, 'retry': retries + 1})

    def _publish_download_status(self, sysid: int, compid: int, status: str, extra: Dict[str, Any] | None = None):
        payload = {
            'sysid': sysid,
            'compid': compid,
            'status': status,
            'ts': time.time(),
        }
        if extra:
            payload.update(extra)
        try:
            self.mqtt_client.publish(f"Nomad/missions/downloaded/{sysid}/status", json.dumps(payload))
        except Exception as e:
            print(f"[mission_manager] failed to publish download status ({status}) for {sysid}: {e}")

    def start_mission_upload(self, sysid: int, compid: int, mission: list, expected_hash: str = None):
        """Start mission upload with optional hash verification."""
        self.upload_states[sysid] = {
            'state': 'sending_count',
            'mission': mission,
            'sent': set(),
            'start_time': time.time(),
            'target_comp': compid,
            'expected_hash': expected_hash
        }

        count = len(mission)
        src_sys = self.cfg.get("gcs_sysid", 255)
        src_comp = self.cfg.get("gcs_compid", 1)
        out_bytes = mavlink_encoder.encode_mission_count(sysid, compid, count, src_sys=src_sys, src_comp=src_comp)

        if self._send_to_drone(sysid, out_bytes):
            print(f"[mission_manager] sent MISSION_COUNT {count} to {sysid}")
            self.upload_states[sysid]['state'] = 'sending_items'
            return True
        return False

    def start_mission_download(self, sysid: int, compid: int):
        """Start mission download from drone."""
        now = time.time()
        self.download_states[sysid] = {
            'state': 'requesting_list',
            'mode': 'active',
            'mission': [],
            'start_time': now,
            'last_activity_ts': now,
            'retries': 0,
            'target_comp': compid
        }

        src_sys = self.cfg.get("gcs_sysid", 255)
        src_comp = self.cfg.get("gcs_compid", 1)
        out_bytes = mavlink_encoder.encode_mission_request_list(sysid, compid, src_sys=src_sys, src_comp=src_comp)

        if self._send_to_drone(sysid, out_bytes):
            print(f"[mission_manager] requested mission list from {sysid}")
            self._publish_download_status(sysid, compid, 'request_sent', {'phase': 'mission_request_list'})
            return True
        self._publish_download_status(sysid, compid, 'request_send_failed', {'phase': 'mission_request_list'})
        return False

    def observe_external_mission_request(self, requester_sysid: int | None, requester_compid: int | None, target_sysid: int | None, target_compid: int | None, request_type: str):
        """Record mission requests initiated by other GCS clients (e.g. QGC)."""
        if target_sysid is None:
            return
        try:
            target_sysid = int(target_sysid)
        except Exception:
            return
        # External mission download requests should target vehicles (sysid < 250).
        if target_sysid >= 250:
            return
        try:
            target_compid = int(target_compid) if target_compid is not None else 1
        except Exception:
            target_compid = 1

        state = self.download_states.get(target_sysid)
        if not state or state.get('mode') != 'active':
            self.download_states[target_sysid] = {
                'state': 'requesting_list',
                'mode': 'passive',
                'mission': [],
                'start_time': time.time(),
                'target_comp': target_compid
            }

        self._publish_download_status(
            target_sysid,
            target_compid,
            'request_observed',
            {
                'phase': str(request_type or 'mission_request').lower(),
                'source': 'passive',
                'requester_sysid': requester_sysid,
                'requester_compid': requester_compid
            }
        )
        try:
            print(
                f"[mission_manager] observed external mission request type={request_type} "
                f"requester={requester_sysid}/{requester_compid} target={target_sysid}/{target_compid}"
            )
        except Exception:
            pass

    def handle_mission_ack(self, sysid: int, compid: int):
        """Handle MISSION_ACK - verify upload completion."""
        state = self.upload_states.get(sysid)
        if state and state['state'] == 'sending_items':
            state['state'] = 'completed'
            duration = time.time() - state['start_time']
            print(f"[mission_manager] mission upload completed for {sysid} in {duration:.1f}s")

            # Publish completion status
            try:
                status_payload = json.dumps({
                    'sysid': sysid,
                    'compid': compid,
                    'status': 'completed',
                    'duration': duration,
                    'item_count': len(state['mission'])
                })
                self.mqtt_client.publish(f"Nomad/missions/uploaded/{sysid}/status", status_payload)
            except Exception as e:
                print(f"[mission_manager] failed to publish upload status: {e}")

    def handle_mission_request(self, sysid: int, compid: int, seq: int):
        """Handle MISSION_REQUEST from vehicle during upload."""
        state = self.upload_states.get(sysid)
        if not state or state['state'] != 'sending_items':
            return

        mission = state['mission']
        if seq < 0 or seq >= len(mission):
            return

        item = mission[seq]
        # send MISSION_ITEM_INT
        src_sys = self.cfg.get("gcs_sysid", 255)
        src_comp = self.cfg.get("gcs_compid", 1)
        out_bytes = mavlink_encoder.encode_mission_item_int(
            sysid, compid, seq, item['frame'], item['command'],
            params=item.get('params', []), x=item['x'], y=item['y'], z=item['z'],
            src_sys=src_sys, src_comp=src_comp
        )

        if self._send_to_drone(sysid, out_bytes):
            state['sent'].add(seq)
            print(f"[mission_manager] sent MISSION_ITEM_INT seq {seq} to {sysid}")



    def handle_mission_item(self, sysid: int, compid: int, seq: int, item_data: dict):
        """Handle MISSION_ITEM during download."""
        state = self.download_states.get(sysid)
        if not state or state.get('state') not in ('downloading', 'passive_observing'):
            # If interception starts late, we may miss MISSION_REQUEST/MISSION_COUNT.
            # Capture orphan mission items in passive mode so UI can still build a partial plan.
            inferred_len = max(int(seq) + 1, 1)
            state = {
                'state': 'passive_observing',
                'mode': 'passive',
                'mission': [None] * inferred_len,
                'start_time': time.time(),
                'target_comp': compid,
                'inferred_count': True,
            }
            self.download_states[sysid] = state
            self._publish_download_status(
                sysid,
                compid,
                'passive_observing',
                {'phase': 'mission_item_orphan', 'seq': int(seq), 'count': inferred_len, 'source': 'passive'}
            )
        print(f"[mission_manager] received mission item seq={seq} from {sysid}")
        now = time.time()
        # Any incoming item means the drone is alive and responding — reset watchdog
        state['last_activity_ts'] = now
        state['retries'] = 0
        if seq < len(state['mission']):
            was_empty = state['mission'][seq] is None
            state['mission'][seq] = item_data

            if was_empty and state.get('mode') == 'passive':
                captured_count = sum(1 for item in state['mission'] if item is not None)
                self._publish_download_status(
                    sysid,
                    compid,
                    'passive_observing',
                    {'phase': 'mission_item', 'seq': int(seq), 'count': len(state['mission']), 'captured_count': captured_count, 'source': 'passive'}
                )
                # Publish periodic partial snapshots so UI can build mission plans from interceptions.
                last_snapshot_ts = float(state.get('last_snapshot_ts') or 0.0)
                if (now - last_snapshot_ts) >= 0.25:
                    try:
                        partial_payload = json.dumps({
                            'sysid': sysid,
                            'compid': compid,
                            'mission': [item for item in state['mission'] if item is not None],
                            'count': len(state['mission']),
                            'captured_count': captured_count,
                            'download_duration': now - state['start_time'],
                            'source': 'passive',
                            'complete': False,
                            'partial': True
                        })
                        self.mqtt_client.publish(f"Nomad/missions/downloaded/{sysid}", partial_payload)
                        print(f"[mission_manager] published partial mission snapshot for {sysid} captured={captured_count}/{len(state['mission'])}")
                        state['last_snapshot_ts'] = now
                    except Exception as e:
                        print(f"[mission_manager] failed to publish partial mission snapshot for {sysid}: {e}")

            # Check if download is complete
            if all(item is not None for item in state['mission']):
                print(f"[mission_manager] all items received for {sysid}, completing download")
                self._complete_download(sysid, compid, state)
            else:
                # Passive background observe mode should never drive the transfer.
                if state.get('mode') == 'passive':
                    return
                # Request next item
                next_seq = seq + 1
                if next_seq < len(state['mission']):
                    print(f"[mission_manager] requesting next mission item seq={next_seq} for {sysid}")
                    src_sys = self.cfg.get("gcs_sysid", 255)
                    src_comp = self.cfg.get("gcs_compid", 1)
                    out_bytes = mavlink_encoder.encode_mission_request_int(sysid, compid, next_seq, src_sys=src_sys, src_comp=src_comp)
                    if not self._send_to_drone(sysid, out_bytes):
                        print(f"[mission_manager] failed to request next item seq={next_seq} for {sysid} — target not observed or send failed")
                        self._publish_download_status(sysid, compid, 'request_send_failed', {'phase': 'mission_request_int', 'seq': next_seq})
        else:
            # Some stacks can emit out-of-order items; keep buffer large enough.
            if state.get('mode') == 'passive':
                missing = (seq + 1) - len(state['mission'])
                if missing > 0:
                    state['mission'].extend([None] * missing)
                state['mission'][seq] = item_data
                captured_count = sum(1 for item in state['mission'] if item is not None)
                self._publish_download_status(
                    sysid,
                    compid,
                    'passive_observing',
                    {'phase': 'mission_item', 'seq': int(seq), 'count': len(state['mission']), 'captured_count': captured_count, 'source': 'passive'}
                )

    def _complete_download(self, sysid: int, compid: int, state: dict):
        """Complete mission download and publish results."""
        state['state'] = 'completed'
        duration = time.time() - state['start_time']
        mission_items = state.get('mission') or []
        if any(item is None for item in mission_items):
            mission_items = [item for item in mission_items if item is not None]

        try:
            mission_payload = json.dumps({
                'sysid': sysid,
                'compid': compid,
                'mission': mission_items,
                'count': len(state.get('mission') or []),
                'captured_count': len(mission_items),
                'download_duration': duration,
                'source': state.get('mode', 'active'),
                'complete': len(mission_items) == len(state.get('mission') or []),
                'partial': len(mission_items) != len(state.get('mission') or [])
            })
            self.mqtt_client.publish(f"Nomad/missions/downloaded/{sysid}", mission_payload)
            print(f"[mission_manager] published downloaded mission from {sysid} ({len(mission_items)}/{len(state.get('mission') or [])} items) in {duration:.1f}s")
        except Exception as e:
            print(f"[mission_manager] failed to publish downloaded mission: {e}")

    def _send_to_drone(self, sysid: int, data: bytes) -> bool:
        """Send data to drone via appropriate transport port."""
        dest_port = None
        forced_port = self.cfg.get("command_out_port")
        if forced_port:
            dest_port = forced_port
        else:
            for p, seen in self.router.observed_sysids.items():
                if sysid in seen:
                    dest_port = p
                    break

        # Debug: report routing decision
        try:
            print(f"[mission_manager] routing lookup for sysid={sysid} -> dest_port={dest_port}; observed_sysids_keys={list(getattr(self.router, 'observed_sysids', {}).keys())}")
        except Exception:
            pass

        if dest_port and dest_port in self.ports:
            dest_addr = self._resolve_dest_addr(dest_port)
            if dest_addr:
                try:
                    # show a short preview of bytes being sent
                    try:
                        s_preview = data[:32].hex()
                    except Exception:
                        s_preview = f"<{len(data)} bytes>"
                    print(f"[mission_manager] sending {len(data)} bytes to {sysid} via port={dest_port} addr={dest_addr} preview={s_preview}")
                    self.ports[dest_port]["out_q"].put((dest_addr, data))
                    return True
                except Exception as e:
                    print(f"[mission_manager] failed to send to {sysid}: {e}")
        else:
            # give helpful debugging: show last_addr mapping and which ports observed the sysid
            try:
                print(f"[mission_manager] cannot send to {sysid}: dest_port={dest_port}, last_addr_map={getattr(self.router, 'last_addr', {})}")
            except Exception:
                pass
        return False

    def _resolve_dest_addr(self, port_name: str):
        dest_addr = getattr(self.router, "last_addr", {}).get(port_name)
        if dest_addr:
            return dest_addr
        try:
            ep = resolve_endpoint(port_name, self.cfg)
            if ep and ep.get("host") and ep.get("port"):
                return (ep.get("host"), int(ep.get("port")))
        except Exception:
            pass
        return None

    def handle_mission_count(self, sysid: int, compid: int, count: int):
        """Handle MISSION_COUNT received from vehicle to start download state."""
        print(f"[mission_manager] received MISSION_COUNT={count} from {sysid}/{compid}")
        existing = self.download_states.get(sysid)
        is_active_request = bool(existing and existing.get('mode') == 'active' and existing.get('state') in ('requesting_list', 'downloading'))
        existing_len = len(existing.get('mission') or []) if existing else 0
        if existing and existing.get('state') in ('downloading', 'passive_observing') and existing_len == int(count):
            # Duplicate MISSION_COUNT is common when multiple listeners are present.
            # Keep in-progress buffer to avoid losing already captured items.
            if existing.get('mode') == 'passive':
                self._publish_download_status(
                    sysid,
                    compid,
                    'passive_observing',
                    {'phase': 'mission_count', 'count': int(count), 'source': 'passive', 'note': 'duplicate_count_ignored'}
                )
                print(f"[mission_manager] duplicate MISSION_COUNT ignored for passive intercept sysid={sysid} count={count}")
                return
            if existing.get('mode') == 'active':
                print(f"[mission_manager] duplicate MISSION_COUNT ignored for active download sysid={sysid} count={count}")
                return
        if count == 0:
            # nothing to download
            self.download_states[sysid] = {
                'state': 'completed',
                'mode': 'active' if is_active_request else 'passive',
                'mission': [],
                'start_time': time.time(),
                'target_comp': compid,
            }
            print(f"[mission_manager] remote reports 0 mission items for {sysid}; marked completed")
            self._publish_download_status(
                sysid,
                compid,
                'completed',
                {'phase': 'mission_count', 'count': 0, 'source': 'active' if is_active_request else 'passive'}
            )
            try:
                self.mqtt_client.publish(
                    f"Nomad/missions/downloaded/{sysid}",
                    json.dumps({
                        'sysid': sysid,
                        'compid': compid,
                        'mission': [],
                        'count': 0,
                        'captured_count': 0,
                        'download_duration': 0.0,
                        'source': 'active' if is_active_request else 'passive',
                        'complete': True,
                        'partial': False
                    })
                )
            except Exception:
                pass
            return

        # initialize/refresh download state with placeholder list, preserving captured items when possible
        merged_mission = [None] * int(count)
        if existing and existing.get('mode') == 'passive':
            prev = existing.get('mission') or []
            for idx, item in enumerate(prev):
                if idx >= int(count):
                    break
                if item is not None:
                    merged_mission[idx] = item

        now = time.time()
        self.download_states[sysid] = {
            'state': 'downloading' if is_active_request else 'passive_observing',
            'mode': 'active' if is_active_request else 'passive',
            'mission': merged_mission,
            'start_time': existing.get('start_time', now) if existing else now,
            'last_activity_ts': now,
            'retries': 0,
            'target_comp': compid,
        }

        if not is_active_request:
            self._publish_download_status(
                sysid,
                compid,
                'passive_observing',
                {'phase': 'mission_count', 'count': int(count), 'source': 'passive'}
            )
            return

        # request first item (prefer INT)
        src_sys = self.cfg.get("gcs_sysid", 255)
        src_comp = self.cfg.get("gcs_compid", 1)
        try:
            out_bytes = mavlink_encoder.encode_mission_request_int(sysid, compid, 0, src_sys=src_sys, src_comp=src_comp)
        except Exception:
            out_bytes = mavlink_encoder.encode_mission_request_list(sysid, compid, src_sys=src_sys, src_comp=src_comp)

        if self._send_to_drone(sysid, out_bytes):
            print(f"[mission_manager] requested mission item seq=0 for {sysid}")
            self._publish_download_status(sysid, compid, 'request_sent', {'phase': 'mission_request_int', 'seq': 0, 'source': 'active'})
        else:
            print(f"[mission_manager] failed to send mission request for {sysid} (no observed port or send error)")
            self._publish_download_status(sysid, compid, 'request_send_failed', {'phase': 'mission_request_int', 'seq': 0, 'source': 'active'})


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
        # Persistent MAVLink parsers per transport for proper stream parsing
        self._mav_parsers = {}  # transport_name -> parser instance
        # Mission manager for handling upload/download operations
        self.mission_manager = MissionManager(cfg, router, ports, self.client)

    def _source_topic(self, src_sys: int | None, src_comp: int | None, dest_sys: int | None, dest_comp: int | None, msg_type: str, port_name: str) -> str:
        return (
            f"sources/source_sysid_{src_sys or 0}/"
            f"source_compid_{src_comp or 0}/"
            f"dest_sysid_{dest_sys or 0}/"
            f"dest_compid_{dest_comp or 0}/"
            f"{msg_type}/{port_name}"
        )

    def _publish_decoded_message(self, name: str, addr, msg_type: str, fields: Dict[str, Any], src_sys: int | None, src_comp: int | None):
        dest_sys = int(fields.get("target_system", 0) or fields.get("target_sys", 0) or 0)
        dest_comp = int(fields.get("target_component", 0) or fields.get("target_comp", 0) or 0)
        sus = src_sys or 0
        suc = src_comp or 0
        device_topic_base = f"device/sysid_{sus}/compid_{suc}/{msg_type}"
        device_publishes = 0
        source_publishes = 0

        try:
            self.client.publish(device_topic_base, json.dumps({"fields": fields, "src_addr": addr, "port": name}))
            device_publishes += 1
        except Exception:
            pass

        if self._publish_fields:
            for k, v in (fields or {}).items():
                try:
                    self.client.publish(f"{device_topic_base}/{k}", json.dumps(v))
                    device_publishes += 1
                except Exception:
                    pass

        try:
            self.client.publish(
                self._source_topic(sus, suc, dest_sys, dest_comp, msg_type, name),
                json.dumps({"fields": fields, "src_addr": addr}),
            )
            source_publishes += 1
        except Exception:
            pass

        if self._debug_publish_counts:
            try:
                print(f"[mqtt_adapter] packet from {addr} (port={name}) msg={msg_type} -> device_publishes={device_publishes} source_publishes={source_publishes}")
            except Exception:
                pass
        self._total_publishes += device_publishes + source_publishes

    def _encode_uplink(self, topic: str, data: Any, target_sys: int, target_comp: int) -> tuple[bytes, int, int, dict | None]:
        out_bytes = None
        ack_payload = None
        if isinstance(data, dict) and (data.get("command") == "SET_MODE" or data.get("msg") == "SET_MODE" or data.get("type") == "SET_MODE"):
            tgt_sys = int(data.get("target_sys", target_sys))
            tgt_comp = int(data.get("target_comp", target_comp))
            base_mode = int(data.get("base_mode", 1))
            custom_mode = data.get("custom_mode")
            if custom_mode is None:
                custom_mode = self._px4_custom_mode_from_label(data.get("mode"))
            if custom_mode is None:
                raise ValueError(f"unknown mode label for SET_MODE: {data.get('mode')}")
            params = [base_mode, int(custom_mode), 0, 0, 0, 0, 0]
            src_sys, src_comp = self._resolve_src_ids(data)
            out_bytes = mavlink_encoder.encode_command_long(
                tgt_sys,
                tgt_comp,
                176,
                params,
                src_sys=src_sys,
                src_comp=src_comp,
            )
            ack_payload = {
                "status": "encoded",
                "msg": "SET_MODE",
                "bytes": len(out_bytes),
                "base_mode": base_mode,
                "custom_mode": int(custom_mode),
            }
        elif isinstance(data, dict) and (
            data.get("msg") == "COMMAND_LONG"
            or data.get("type") == "COMMAND_LONG"
            or data.get("command") is not None
        ):
            tgt_sys = int(data.get("target_sys", target_sys))
            tgt_comp = int(data.get("target_comp", target_comp))
            cmd = self._mav_cmd_name_to_id(data.get("command"))
            if cmd is None:
                raise ValueError(f"unknown COMMAND_LONG command: {data.get('command')}")
            params = data.get("params", [])
            src_sys, src_comp = self._resolve_src_ids(data)
            out_bytes = mavlink_encoder.encode_command_long(tgt_sys, tgt_comp, cmd, params, src_sys=src_sys, src_comp=src_comp)
            ack_payload = {"status": "encoded", "msg": "COMMAND_LONG", "bytes": len(out_bytes), "command": cmd}
        elif isinstance(data, dict) and (data.get("msg") == "MISSION_ITEM_INT" or data.get("type") == "MISSION_ITEM_INT"):
            tgt_sys = int(data.get("target_sys", target_sys))
            tgt_comp = int(data.get("target_comp", target_comp))
            seq = int(data.get("seq", 0))
            frame = int(data.get("frame", 0))
            cmd = int(data.get("command", 16))
            x = int(data.get("x", 0))
            y = int(data.get("y", 0))
            z = float(data.get("z", 0.0))
            params = data.get("params", [])
            src_sys, src_comp = self._resolve_src_ids(data)
            out_bytes = mavlink_encoder.encode_mission_item_int(tgt_sys, tgt_comp, seq, frame, cmd, params=params, x=x, y=y, z=z, src_sys=src_sys, src_comp=src_comp)
            ack_payload = {"status": "encoded", "msg": "MISSION_ITEM_INT", "bytes": len(out_bytes), "seq": seq}
        else:
            out_bytes = json.dumps({"topic": topic, "payload": data}).encode("utf-8")
            tgt_sys = target_sys
            tgt_comp = target_comp
        return out_bytes, tgt_sys, tgt_comp, ack_payload

    def _publish_command_ack(self, target_sys: int, target_comp: int, payload: dict):
        try:
            self.client.publish(f"command/{target_sys}/{target_comp}/ack", json.dumps(payload))
        except Exception:
            pass

    def _resolve_command_route(self, target_sys: int) -> tuple[str | None, tuple[str, int] | None]:
        """Resolve the outbound transport for uplink commands.

        UI-originated uplink must always exit through the configured
        command_out_port. Do not infer the route from observed target traffic.
        """
        forced_port = self.cfg.get("command_out_port")
        if not forced_port:
            return None, None
        return forced_port, self._resolve_dest_addr(forced_port)

    def _parse_device_topic_ids(self, topic: str) -> tuple[int | None, int | None]:
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != "device":
            return None, None
        try:
            return int(parts[1]), int(parts[2])
        except Exception:
            pass
        try:
            sysid = int(str(parts[1]).removeprefix("sysid_"))
            compid = int(str(parts[2]).removeprefix("compid_"))
            return sysid, compid
        except Exception:
            return None, None

    def _parse_device_topic(self, topic: str) -> tuple[int | None, int | None, str | None]:
        parts = topic.split("/")
        if len(parts) < 4 or parts[0] != "device":
            return None, None, None
        sysid, compid = self._parse_device_topic_ids(topic)
        msg_type = parts[3] if len(parts) > 3 else None
        return sysid, compid, msg_type

    def _resolve_src_ids(self, data: Dict[str, Any] | None) -> tuple[int, int]:
        """Resolve MAVLink source IDs with payload override support.

        Frontend commands may include src_sysid/src_compid. Fall back to config.
        """
        src_sys = int(self.cfg.get("gcs_sysid", 255))
        src_comp = int(self.cfg.get("gcs_compid", 1))
        if not isinstance(data, dict):
            return src_sys, src_comp
        try:
            if data.get("src_sysid") is not None:
                src_sys = int(data.get("src_sysid"))
            elif data.get("src_sys") is not None:
                src_sys = int(data.get("src_sys"))
        except Exception:
            pass
        try:
            if data.get("src_compid") is not None:
                src_comp = int(data.get("src_compid"))
            elif data.get("src_comp") is not None:
                src_comp = int(data.get("src_comp"))
        except Exception:
            pass
        return src_sys, src_comp

    def _mav_cmd_name_to_id(self, command_value: Any) -> int | None:
        """Convert MAV_CMD string or numeric value to int command id."""
        if command_value is None:
            return None
        # accept direct numeric command ids
        try:
            if isinstance(command_value, (int, float)):
                return int(command_value)
            cmd_str = str(command_value).strip()
            if cmd_str.isdigit():
                return int(cmd_str)
        except Exception:
            pass

        # common command names used by frontend/control panels
        cmd_map = {
            "MAV_CMD_COMPONENT_ARM_DISARM": 400,
            "MAV_CMD_NAV_TAKEOFF": 22,
            "MAV_CMD_NAV_LAND": 21,
            "MAV_CMD_NAV_RETURN_TO_LAUNCH": 20,
            "MAV_CMD_DO_SET_MODE": 176,
        }
        try:
            return cmd_map.get(str(command_value).strip().upper())
        except Exception:
            return None

    def _px4_custom_mode_from_label(self, mode_label: str) -> int | None:
        if not mode_label:
            return None
        label = str(mode_label).strip().upper().replace(" ", "_").replace("-", "_")
        label = label.replace("PX4_CUSTOM_MAIN_MODE_", "")
        label = label.replace("PX4_CUSTOM_SUB_MODE_AUTO_", "AUTO_")
        label = label.replace("PX4_CUSTOM_SUB_MODE_POSCTL_", "POSCTL_")

        main_modes = {
            "MANUAL": 1,
            "ALTCTL": 2,
            "ALTITUDE": 2,
            "POSCTL": 3,
            "POSITION": 3,
            "AUTO": 4,
            "ACRO": 5,
            "OFFBOARD": 6,
            "STABILIZED": 7,
            "STABILIZE": 7,
            "RATTITUDE": 8,
            "RATTITUDE_LEGACY": 8,
            "SIMPLE": 9,
            "TERMINATION": 10,
            "ALTITUDE_CRUISE": 11,
        }

        auto_sub_modes = {
            "AUTO_READY": 1,
            "AUTO_TAKEOFF": 2,
            "AUTO_LOITER": 3,
            "AUTO_MISSION": 4,
            "AUTO_RTL": 5,
            "AUTO_LAND": 6,
            "AUTO_RESERVED_DO_NOT_USE": 7,
            "AUTO_FOLLOW_TARGET": 8,
            "AUTO_PRECLAND": 9,
            "AUTO_VTOL_TAKEOFF": 10,
            "AUTO_EXTERNAL1": 11,
            "AUTO_EXTERNAL2": 12,
            "AUTO_EXTERNAL3": 13,
            "AUTO_EXTERNAL4": 14,
            "AUTO_EXTERNAL5": 15,
            "AUTO_EXTERNAL6": 16,
            "AUTO_EXTERNAL7": 17,
            "AUTO_EXTERNAL8": 18,
            "HOLD": 3,
            "LOITER": 3,
            "MISSION": 4,
            "RTL": 5,
            "RETURN": 5,
            "TAKEOFF": 2,
            "LAND": 6,
            "FOLLOW_TARGET": 8,
            "PRECLAND": 9,
            "VTOL_TAKEOFF": 10,
        }

        posctl_sub_modes = {
            "POSCTL_POSCTL": 0,
            "POSCTL_ORBIT": 1,
            "POSCTL_SLOW": 2,
            "ORBIT": 1,
            "SLOW": 2,
        }

        if ":" in label:
            main_label, sub_label = label.split(":", 1)
        else:
            main_label, sub_label = label, ""

        if main_label == "AUTO" or main_label == "PX4_CUSTOM_MAIN_MODE_AUTO":
            main_mode = 4
            sub_mode = auto_sub_modes.get(sub_label or "AUTO_READY")
        elif main_label == "POSCTL" or main_label == "POSITION":
            main_mode = 3
            sub_mode = posctl_sub_modes.get(sub_label)
        else:
            main_mode = main_modes.get(main_label)
            sub_mode = None

        if main_mode is None:
            return None
        if main_mode not in (3, 4):
            return (main_mode << 16)
        if sub_mode is None:
            return (main_mode << 16)
        return (main_mode << 16) | (sub_mode << 24)

    def start(self):
        host = self.cfg["mqtt"]["host"]
        port = self.cfg["mqtt"]["port"]
        print(f"[mqtt_adapter] attempting to connect to MQTT broker at {host}:{port}")
        max_attempts = int(os.environ.get("NOMAD_MQTT_CONNECT_RETRY", "0") or "0")
        delay_s = float(os.environ.get("NOMAD_MQTT_CONNECT_DELAY_S", "1.0") or "1.0")
        attempt = 0
        while True:
            try:
                self.client.connect(host, port, self.cfg["mqtt"].get("keepalive", 60))
                print(f"[mqtt_adapter] successfully connected to MQTT broker at {host}:{port}")
                break
            except Exception as e:
                attempt += 1
                if max_attempts > 0 and attempt >= max_attempts:
                    print(f"[mqtt_adapter] FAILED to connect to MQTT broker at {host}:{port} after {attempt} attempts")
                    print(f"[mqtt_adapter] Error details: {type(e).__name__}: {e}")
                    print(f"[mqtt_adapter] This usually means the MQTT broker is not running or not accepting connections")
                    print(f"[mqtt_adapter] Check that Aedes broker is started and listening on {host}:{port}")
                    raise e
                print(f"[mqtt_adapter] connect failed (attempt {attempt}{'/' + str(max_attempts) if max_attempts > 0 else ''}); retrying in {delay_s:.1f}s: {type(e).__name__}: {e}")
                time.sleep(delay_s)
        
        # start MQTT network loop in a background thread
        print("[mqtt_adapter] starting MQTT network loop thread")
        t = threading.Thread(target=self.client.loop_forever, daemon=True)
        t.start()
        # start publisher loop
        print("[mqtt_adapter] starting publisher thread")
        self.pub_thread = threading.Thread(target=self._pub_loop, daemon=True)
        self.pub_thread.start()
        # start pending delivery thread
        print("[mqtt_adapter] starting pending thread")
        self.pending_thread = threading.Thread(target=self._pending_loop, daemon=True)
        self.pending_thread.start()
        # start status publisher thread
        print("[mqtt_adapter] starting status thread")
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()
        print("[mqtt_adapter] all threads started successfully")

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
        client.subscribe("command/+/+/download_mission")
        client.subscribe("device/+/+/MISSION_REQUEST")
        client.subscribe("device/+/+/MISSION_REQUEST_INT")
        client.subscribe("device/+/+/MISSION_REQUEST_LIST")
        client.subscribe("device/+/+/MISSION_ACK")
        client.subscribe("device/+/+/MISSION_COUNT")
        client.subscribe("device/+/+/MISSION_ITEM_INT")
        client.subscribe("device/+/+/MISSION_ITEM")
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
        if self._debug_publish_counts:
            try:
                raw_preview = msg.payload[:256].decode('utf-8', errors='replace')
            except Exception:
                raw_preview = '<binary payload>'
            print(f"[mqtt_adapter] on_message topic={topic} payload_preview={raw_preview}")
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
            data_dict = data if isinstance(data, dict) else {}

            is_load_waypoints = topic.endswith("/load_waypoints") or data_dict.get("action") == "load_waypoints"
            if is_load_waypoints:
                print(f"[mqtt_adapter] load_waypoints request for target={target_sys}/{target_comp} filename={data_dict.get('filename')} items={len(data_dict.get('waypoints') or [])}")
                filename = data_dict.get("filename") or data_dict.get("name") or "unnamed.yaml"
                waypoints = data_dict.get("waypoints") or data_dict.get("mission")
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
                if ok:
                    # start mission upload
                    mission_items = waypoint_validator.waypoints_to_mission_items(norm)
                    self.mission_manager.start_mission_upload(target_sys, target_comp, mission_items, expected_hash=h)
                    status = "validated and uploading"
                else:
                    status = "validated"
                # ACK back to command topic with validation result
                try:
                    client.publish(f"command/{parts[1]}/{parts[2]}/ack", json.dumps({"status": status, "ok": ok, "details": details, "hash": h}))
                except Exception:
                    pass
                return

            is_download_mission = topic.endswith("/download_mission") or data_dict.get("action") == "download_mission"
            if is_download_mission:
                print(f"[mqtt_adapter] download_mission request for target={target_sys}/{target_comp}")
                started = self.mission_manager.start_mission_download(target_sys, target_comp)
                # ACK back to command topic
                try:
                    client.publish(
                        f"command/{parts[1]}/{parts[2]}/ack",
                        json.dumps({
                            "status": "download_started" if started else "download_request_failed",
                            "sysid": target_sys,
                            "compid": target_comp,
                        })
                    )
                except Exception:
                    pass
                return

            dest_port, dest_addr = self._resolve_command_route(target_sys)

            if dest_port is None:
                # no known port for target; queue for later delivery
                try:
                    observed = {k: sorted(list(v)) for k, v in getattr(self.router, 'observed_sysids', {}).items()}
                except Exception:
                    observed = {}
                print(f"[mqtt_adapter] no transport port known for target sysid {target_sys}; queueing (observed_sysids={observed})")
                self.pending_commands.setdefault(target_sys, []).append((topic, data))
                return

            if dest_addr is None:
                try:
                    last_addr = getattr(self.router, 'last_addr', {})
                except Exception:
                    last_addr = {}
                print(f"[mqtt_adapter] no dest_addr for port {dest_port}; queueing command until route resolves (last_addr={last_addr})")
                self.pending_commands.setdefault(target_sys, []).append((topic, data))
                return

            # if payload is a JSON command describing a MAVLink message, try encoding
            try:
                out_bytes, ack_sys, ack_comp, ack_payload = self._encode_uplink(topic, data, target_sys, target_comp)
                if ack_payload:
                    self._publish_command_ack(ack_sys, ack_comp, ack_payload)
            except Exception as e:
                print(f"[mqtt_adapter] failed to encode MAVLink message: {e}; falling back to JSON payload")
                out_bytes = json.dumps({"topic": topic, "payload": data}).encode("utf-8")
            try:
                self.ports[dest_port]["out_q"].put((dest_addr, out_bytes))
                print(f"[mqtt_adapter] injected command for {target_sys} into port {dest_port} -> {dest_addr} (len={len(out_bytes)})")
            except Exception as e:
                print("[mqtt_adapter] failed to inject into out_q:", e)

        # handle mission upload/download responses
        sysid, compid, msg_type = self._parse_device_topic(topic) if topic.startswith("device/") else (None, None, None)
        if sysid is not None and compid is not None and msg_type in ("MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_REQUEST_LIST"):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                fields = payload.get("fields", {}) or {}
                target_sys = fields.get("target_system")
                target_comp = fields.get("target_component")
                try:
                    target_sys_int = int(target_sys) if target_sys is not None else None
                except Exception:
                    target_sys_int = None
                # MISSION_REQUEST(_INT) aimed at a GCS sysid is part of upload handshake;
                # don't classify it as an external mission download request.
                if msg_type in ("MISSION_REQUEST", "MISSION_REQUEST_INT") and target_sys_int is not None and target_sys_int >= 250:
                    seq = fields.get("seq", 0)
                    self.mission_manager.handle_mission_request(sysid, compid, seq)
                else:
                    self.mission_manager.observe_external_mission_request(sysid, compid, target_sys_int, target_comp, msg_type)
            except Exception:
                pass
        elif topic.startswith("device/") and "MISSION_ACK" in topic:
            sysid, compid = self._parse_device_topic_ids(topic)
            if sysid is not None and compid is not None:
                try:
                    self.mission_manager.handle_mission_ack(sysid, compid)
                except Exception:
                    pass
        elif topic.startswith("device/") and "MISSION_COUNT" in topic:
            sysid, compid = self._parse_device_topic_ids(topic)
            if sysid is not None and compid is not None:
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    count = payload.get("fields", {}).get("count", 0)
                    self.mission_manager.handle_mission_count(sysid, compid, count)
                except Exception:
                    pass
        elif topic.startswith("device/") and "MISSION_ITEM_INT" in topic:
            sysid, compid = self._parse_device_topic_ids(topic)
            if sysid is not None and compid is not None:
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    fields = payload.get("fields", {})
                    seq = fields.get("seq", 0)
                    item_data = {
                        'seq': seq,
                        'frame': fields.get('frame', 0),
                        'command': fields.get('command', 0),
                        'x': fields.get('x', 0),
                        'y': fields.get('y', 0),
                        'z': fields.get('z', 0),
                        'params': [
                            fields.get('param1', 0),
                            fields.get('param2', 0),
                            fields.get('param3', 0),
                            fields.get('param4', 0),
                        ]
                    }
                    self.mission_manager.handle_mission_item(sysid, compid, seq, item_data)
                except Exception:
                    pass
        elif topic.startswith("device/") and "MISSION_ITEM" in topic:
            sysid, compid = self._parse_device_topic_ids(topic)
            if sysid is not None and compid is not None:
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    fields = payload.get("fields", {})
                    seq = fields.get("seq", 0)
                    item_data = {
                        'seq': seq,
                        'frame': fields.get('frame', 0),
                        'command': fields.get('command', 0),
                        'x': fields.get('x', 0),
                        'y': fields.get('y', 0),
                        'z': fields.get('z', 0),
                        'params': [
                            fields.get('param1', 0),
                            fields.get('param2', 0),
                            fields.get('param3', 0),
                            fields.get('param4', 0),
                        ]
                    }
                    self.mission_manager.handle_mission_item(sysid, compid, seq, item_data)
                except Exception:
                    pass

    def _pub_loop(self):
        """Process incoming raw packets from transports and publish to MQTT."""
        while not self._stop.is_set():
            try:
                # Get next packet from queue (blocking)
                name, addr, data = self.mqtt_pub_q.get(timeout=0.1)

                # try to decode MAVLink properly (use pymavlink parser if available)
                src_sys = None
                src_comp = None
                decoded_any = False
                try:
                    if self._mav_parser_factory is not None and data:
                        # Get or create persistent parser for this transport
                        transport_name = name
                        if transport_name not in self._mav_parsers:
                            try:
                                self._mav_parsers[transport_name] = self._mav_parser_factory(None)
                            except Exception:
                                self._mav_parsers[transport_name] = None
                        
                        parser = self._mav_parsers[transport_name]
                        if parser is not None:
                            messages = []
                            try:
                                parsed = parser.parse_buffer(data)
                                if parsed:
                                    messages.extend(parsed)
                            except Exception:
                                pass
                            
                            # Process any complete messages
                            for msg_obj in messages:
                                # basic sanity checks: ensure parser returned a useful message
                                msg_type_probe = getattr(msg_obj, 'get_type', lambda: None)()
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
                                    continue
                                decoded_any = True
                                try:
                                    src_sys = int(getattr(msg_obj, 'srcSystem', None) or getattr(msg_obj, 'get_srcSystem', lambda: None)() or 0)
                                except Exception:
                                    src_sys = None
                                try:
                                    src_comp = int(getattr(msg_obj, 'srcComponent', None) or getattr(msg_obj, 'get_srcComponent', lambda: None)() or 0)
                                except Exception:
                                    src_comp = None

                                if src_sys is None or src_comp is None:
                                    if len(data) >= 7 and mavlink_encoder.is_mavlink2_packet(data):
                                        src_sys = src_sys or data[5]
                                        src_comp = src_comp or data[6]
                                    elif len(data) >= 6 and data[0] == 0xFE:
                                        src_sys = src_sys or data[3]
                                        src_comp = src_comp or data[4]

                                fields = probe_fields
                                msg_type = msg_type_probe or getattr(msg_obj, 'name', 'UNKNOWN')
                                self._publish_decoded_message(name, addr, msg_type, fields, src_sys, src_comp)

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
                                        source_topic = self._source_topic(sus, suc, 0, 0, "HEARTBEAT", name)
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
                            topic_sources = self._source_topic(src_sys or 0, src_comp or 0, 0, 0, "RAW", name)
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
                            topic_sources = self._source_topic(src_sys or 0, src_comp or 0, 0, 0, "RAW", name)
                            topic_device = f"device/sysid_{src_sys or 0}/compid_{src_comp or 0}/RAW"
                            payload = data.hex()
                            self.client.publish(topic_sources, payload)
                            self.client.publish(topic_device, payload)
                        except Exception:
                            pass
            except Exception:
                # Queue timeout or other error, continue loop
                continue

    def _resolve_dest_addr(self, port_name: str):
        dest_addr = getattr(self.router, "last_addr", {}).get(port_name)
        if dest_addr:
            return dest_addr
        try:
            ep = resolve_endpoint(port_name, self.cfg)
            if ep and ep.get("host") and ep.get("port"):
                return (ep.get("host"), int(ep.get("port")))
        except Exception:
            pass
        return None

    def _pending_loop(self):
        """Background loop that attempts to deliver pending commands when their
        target sysid becomes observed on a port.
        """
        while not self._stop.is_set():
            try:
                # snapshot keys to avoid mutation during iteration
                keys = list(self.pending_commands.keys())
                for target_sys in keys:
                    dest_port, dest_addr = self._resolve_command_route(target_sys)
                    if dest_port is None:
                        continue
                    if dest_addr is None:
                        continue
                    items = list(self.pending_commands.get(target_sys, []))
                    for topic, data in items:
                        try:
                            out_bytes, ack_sys, ack_comp, _ = self._encode_uplink(topic, data, target_sys, int(data.get("target_comp", 1) if isinstance(data, dict) else 1))

                            self.ports[dest_port]["out_q"].put((dest_addr, out_bytes))
                            # publish ACK
                            self._publish_command_ack(ack_sys, ack_comp, {"status": "delivered", "topic": topic})
                            try:
                                print(f"[mqtt_adapter][_pending_loop] re-injected pending topic={topic} to port={dest_port} dest={dest_addr} len={len(out_bytes)}")
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
                
                # Get mission manager status
                mission_status = {
                    "active_uploads": list(self.mission_manager.upload_states.keys()),
                    "active_downloads": list(self.mission_manager.download_states.keys()),
                }
                
                payload = {
                    "status": "ok",
                    "ts": int(time.time()),
                    "uptime_s": int(uptime),
                    "observed_ports": list(getattr(self.router, 'observed_sysids', {}).keys()),
                    "total_publishes": int(getattr(self, '_total_publishes', 0)),
                    "mission_status": mission_status,
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
