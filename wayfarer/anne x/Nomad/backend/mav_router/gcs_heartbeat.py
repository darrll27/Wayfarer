"""GCS heartbeat generator.

Periodically (1.0 Hz) emits a MAVLink HEARTBEAT from the configured GCS
(sysid/compid) into the router transports/endpoints. The generator prefers
sending to configured endpoints and last-seen peer addresses; for serial
transports it writes directly to the serial out queue (dest ignored).

This module is intentionally lightweight and starts a background thread so it
works inside the main run process.
"""
from __future__ import annotations

import threading
import time
from typing import Dict

from . import mavlink_encoder
from backend.config_manager import parse_endpoint_uri


def _collect_dest_for_port(port_name: str, cfg: dict, router) -> tuple | None:
    """Determine a destination (host,port) or None for a given port.

    Preference:
    1. If port is present in router.last_addr -> use that
    2. If port name corresponds to a configured endpoint -> use endpoint host/port
    3. For serial ports, return None and the serial transport will accept (None,outb)
    4. Otherwise return None (skip)
    """
    # 1: last seen address
    last = getattr(router, 'last_addr', {}) or {}
    if port_name in last and last.get(port_name) is not None:
        return last.get(port_name)

    # 2: endpoint configured explicitly in cfg
    endpoints = cfg.get('endpoints', {}) or {}
    if port_name in endpoints:
        parsed = parse_endpoint_uri(endpoints[port_name])
        if parsed:
            return (parsed.get('host'), int(parsed.get('port')))

    # 3: check transports for serial type
    for t in cfg.get('transports', []) or []:
        if t.get('name') == port_name and t.get('type') == 'serial':
            # serial: dest ignored but caller will still put (None, data)
            return None

    return None


def start_gcs_heartbeat(cfg: dict, ports: Dict[str, Dict], router):
    """Start a background thread that publishes heartbeat every 1.0s.

    It enqueues bytes into each port's out_q using the discovered destination
    (last_addr or endpoint mapping). For serial ports the dest is ignored by
    the transport process and we enqueue (None, bytes).
    """
    gcs_sys = int(cfg.get('gcs_sysid', 250))
    gcs_comp = int(cfg.get('gcs_compid', 1))
    interval = float(cfg.get('gcs_heartbeat_interval_s', 1.0))

    stop_event = threading.Event()
    debug = bool(cfg.get('gcs_heartbeat_debug', False))

    def _loop():
        last_ts = None
        while not stop_event.is_set():
            try:
                hb = mavlink_encoder.encode_heartbeat(gcs_sys, gcs_comp)
            except Exception:
                # if encoding fails, skip this tick
                time.sleep(interval)
                continue

            # debug: track timing between ticks
            if debug:
                now = time.time()
                if last_ts is not None:
                    elapsed = now - last_ts
                    if elapsed < (interval * 0.9):
                        try:
                            print(f"[gcs_heartbeat] WARNING: heartbeat tick interval too short: {elapsed:.4f}s")
                        except Exception:
                            pass
                last_ts = now

            # enqueue into all known ports
            for pname, meta in list(ports.items()):
                try:
                    dest = _collect_dest_for_port(pname, cfg, router)
                    # report decision for traceability
                    if debug:
                        try:
                            print(f"[gcs_heartbeat] eval port={pname} dest_resolved={dest is not None}")
                        except Exception:
                            pass

                    # if dest is explicitly None but port exists (serial), send (None, hb)
                    # if dest is tuple (host,port) send to that addr
                    if dest is None:
                        # check whether this was a serial mapping: if transport is serial we still want to write
                        # otherwise skip
                        is_serial = False
                        for t in cfg.get('transports', []) or []:
                            if t.get('name') == pname and t.get('type') == 'serial':
                                is_serial = True
                                break
                        if is_serial:
                            try:
                                ports[pname]['out_q'].put((None, hb))
                                if debug:
                                    try:
                                        print(f"[gcs_heartbeat] enqueued HEARTBEAT to serial port {pname} (dest=None)")
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        else:
                            # skip unknown/unresolved UDP listeners with no last_addr
                            if debug:
                                try:
                                    print(f"[gcs_heartbeat] skipping UDP port {pname} (no last_addr and not an endpoint)")
                                except Exception:
                                    pass
                            continue
                    else:
                        # dest is (host,port)
                        try:
                            ports[pname]['out_q'].put(((dest[0], int(dest[1])), hb))
                            if debug:
                                try:
                                    print(f"[gcs_heartbeat] enqueued HEARTBEAT to {pname} -> {dest}")
                                except Exception:
                                    pass
                        except Exception:
                            if debug:
                                try:
                                    print(f"[gcs_heartbeat] failed to enqueue HEARTBEAT to {pname} -> {dest}")
                                except Exception:
                                    pass
                            pass
                except Exception:
                    # per-port failures ignored for robustness
                    if debug:
                        try:
                            print(f"[gcs_heartbeat] unexpected error while handling port {pname}")
                        except Exception:
                            pass
                    continue

            # sleep until next heartbeat
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

    return stop_event
