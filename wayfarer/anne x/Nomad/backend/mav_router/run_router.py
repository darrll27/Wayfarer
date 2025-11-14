"""Run script to start transports and router for local development.

Starts UDP ports defined in a small list (default 14550) and runs the router
in the main process. This is a lightweight development harness.
"""
from __future__ import annotations

import time
from multiprocessing import Queue
from backend.mav_router.transport import UDPPort, SerialPort
from backend.mav_router.router import Router
from backend.mav_router.mqtt_adapter import MQTTAdapter
from backend.config_manager import load_config, parse_endpoint_uri, resolve_endpoint
import json
from pathlib import Path


def main():
    # central inbound queue that transports will push into
    router_in_q: Queue = Queue()
    # queue for transports to also publish raw packets to MQTT
    mqtt_pub_q: Queue = Queue()

    cfg = load_config()
    # debug: show loaded config sections for visibility
    try:
        print(f"[run_router] loaded transports: {cfg.get('transports')}")
        print(f"[run_router] loaded endpoints: {cfg.get('endpoints')}")
        print(f"[run_router] loaded forwards: {cfg.get('forwards')}")
        print(f"[run_router] verbose: {cfg.get('verbose')}")
    except Exception:
        pass

    # configure ports here or load from config
    # config supports: cfg['transports'] = [ { 'type': 'udp', 'name': 'udp_14550', 'host': '0.0.0.0', 'port': 14550 },
    #                                      { 'type': 'serial', 'name': 'serial0', 'device': '/dev/ttyUSB0', 'baud': 57600 } ]
    transports = cfg.get("transports") or [
        {"type": "udp", "name": "udp_14550", "host": "0.0.0.0", "port": 14550},
    ]

    ports = {}
    udp_objects = {}
    serial_objects = {}
    for t in transports:
        if t.get("type") == "udp":
            name = t.get("name")
            host = t.get("host", "0.0.0.0")
            port = int(t.get("port", 14550))
            udp = UDPPort(name, host, port, router_in_q, mqtt_pub_q=mqtt_pub_q)
            udp.start()
            udp_objects[name] = udp
            ports[name] = {"out_q": udp.out_q}
        elif t.get("type") == "serial":
            name = t.get("name")
            device = t.get("device")
            baud = int(t.get("baud", 57600))
            serialp = SerialPort(name, device, baud, router_in_q, mqtt_pub_q=mqtt_pub_q)
            serialp.start()
            serial_objects[name] = serialp
            ports[name] = {"out_q": serialp.out_q}
        else:
            print(f"[run_router] unknown transport type: {t.get('type')}")

    # pass any configured forwarding rules to the router
    forwards = cfg.get("forwards", [])
    verbose = bool(cfg.get("verbose", False))

    # Optionally create local UDP transports for endpoints that look local (loopback)
    endpoints = cfg.get("endpoints", {}) or {}
    for name, uri in endpoints.items():
        parsed = parse_endpoint_uri(uri)
        if not parsed:
            continue
        host = parsed.get("host")
        port = parsed.get("port")
        # create a local listener transport if endpoint is on localhost and not already present
        if host in ("127.0.0.1", "0.0.0.0", "localhost"):
            ep_name = name
            if ep_name not in ports:
                # bind to the host:port so other local apps can connect
                try:
                    print(f"[run_router] creating local endpoint transport {ep_name} -> {host}:{port}")
                except Exception:
                    pass
                udp = UDPPort(ep_name, host, port, router_in_q, mqtt_pub_q=mqtt_pub_q)
                udp.start()
                udp_objects[ep_name] = udp
                ports[ep_name] = {"out_q": udp.out_q}

    # resolve forwards entries: allow 'to' items to reference endpoint names
    resolved_forwards = []
    for fr in forwards:
        new_fr = dict(fr)
        tos = fr.get("to", [])
        new_tos = []
        for t in tos:
            # if t is a string, treat it as endpoint name
            if isinstance(t, str):
                r = resolve_endpoint(t, cfg)
                if r:
                    # if endpoint is local and we created a transport for it, forward into that port
                    host = r.get("host")
                    port = r.get("port")
                    if host in ("127.0.0.1", "0.0.0.0", "localhost") and t in ports:
                        new_tos.append({"type": "to_port", "port_name": t})
                    else:
                        new_tos.append({"type": "udp", "host": host, "port": port})
                else:
                    # keep as-is if cannot resolve
                    new_tos.append(t)
            else:
                new_tos.append(t)
        new_fr["to"] = new_tos
        resolved_forwards.append(new_fr)

    dedupe_window = float(cfg.get('dedupe_window', 0.2))
    router = Router(ports, forwards=resolved_forwards, verbose=verbose, dedupe_window=dedupe_window)

    # startup summary for observability
    try:
        print("[run_router] transports:")
        for p in ports.keys():
            print(f"  - {p}")
        print("[run_router] endpoints:")
        for name, uri in endpoints.items():
            print(f"  - {name} -> {uri}")
        print("[run_router] resolved forwards:")
        for fr in resolved_forwards:
            print(f"  - from: {fr.get('from')} -> to: {fr.get('to')}")
    except Exception:
        pass

    # start MQTT adapter (optional) to bridge transports<->broker
    mqtt_adapter = MQTTAdapter(cfg, ports, router, mqtt_pub_q)
    try:
        mqtt_adapter.start()
    except Exception as e:
        print("[run_router] MQTT adapter failed to start:", e)

    # start an internal GCS heartbeat generator (1 Hz) that injects a HEARTBEAT
    # into transports/endpoints so UIs and devices can observe the GCS presence.
    try:
        from backend.mav_router.gcs_heartbeat import start_gcs_heartbeat

        hb_stop = start_gcs_heartbeat(cfg, ports, router)
    except Exception as e:
        print("[run_router] failed to start gcs heartbeat:", e)

    try:
        print("Started transports. Router and MQTT adapter running. Press Ctrl-C to stop.")
        router.run(router_in_q)
    finally:
        for u in udp_objects.values():
            u.stop()
        try:
            mqtt_adapter.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
