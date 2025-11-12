import argparse
import logging
from wayfarer.config.loader import load_config
from wayfarer.core.bridge import Bridge
from wayfarer.routers.mqtt_router import MQTTRouter
from wayfarer.transports.mavlink_udp import MavlinkUDP
from wayfarer.transports.mavlink_serial import MavlinkSerial
from wayfarer.transports.mavlink_general import MavlinkGeneral

def main():
    p = argparse.ArgumentParser("wayfarer")
    p.add_argument("--config", "-c", required=True, help="Path to YAML config")
    args = p.parse_args()

    cfg = load_config(args.config)

    # build MQTT router (be tolerant to different constructor signatures)
    try:
        # common signature used elsewhere: MQTTRouter(name, mqtt_cfg, on_cmd=None)
        mqtt_router = MQTTRouter("mqtt", cfg["mqtt"], on_cmd=None)
    except TypeError:
        try:
            # alternate signature: MQTTRouter(mqtt_cfg)
            mqtt_router = MQTTRouter(cfg["mqtt"])
        except TypeError:
            # fallback: try (name, mqtt_cfg)
            mqtt_router = MQTTRouter("mqtt", cfg["mqtt"])

    # build transports (no callbacks yet; will wire to bridge after it's created)
    transports = {}
    for name, tcfg in cfg.get("transports", {}).items():
        ttype = tcfg.get("type")
        endpoint = tcfg.get("endpoint")
        if ttype == "mavlink_udp":
            transports[name] = MavlinkUDP(name=name, endpoint=endpoint, on_discover=None, on_packet=None)
        elif ttype == "mavlink_serial":
            transports[name] = MavlinkSerial(name=name, endpoint=endpoint, on_discover=None, on_packet=None)
        elif ttype == "mavlink_general":
            transports[name] = MavlinkGeneral(name=name, endpoint=endpoint, on_discover=None, on_packet=None)
        else:
            # unknown transport type; skip or log as needed
            print(f"[WARN] Unknown transport type for {name}: {ttype}")

    # Apply GCS source identity (if configured) to transports at startup.
    # This ensures outbound MAVLink frames originate from the configured GCS sysid/compid.
    gcs_cfg = cfg.get("gcs") or {}
    gcs_sysid = gcs_cfg.get("sysid")
    gcs_compid = gcs_cfg.get("compid")
    if gcs_sysid is not None or gcs_compid is not None:
        for tname, t in transports.items():
            try:
                if hasattr(t, "set_source_identity"):
                    sysid = int(gcs_sysid) if gcs_sysid is not None else None
                    compid = int(gcs_compid) if gcs_compid is not None else None
                    t.set_source_identity(sysid, compid)
                    logging.info(f"transport {tname}: set_source_identity(sysid={sysid}, compid={compid})")
            except Exception:
                # best-effort; don't abort startup on failure
                pass

    # wire up bridge <-> components
    bridge = Bridge(cfg, transports, mqtt_router)

    # connect router callbacks to bridge
    try:
        mqtt_router.on_cmd = bridge.on_cmd
    except Exception:
        # if router expects callback setter method, try common names
        if hasattr(mqtt_router, "set_on_cmd"):
            mqtt_router.set_on_cmd(bridge.on_cmd)

    # wire transports to bridge callbacks
    for t in transports.values():
        t.on_discover = bridge.on_discover_mav
        t.on_packet = bridge.on_transport_packet

    # start bridge (starts mqtt_router and transports)
    bridge.start()
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()

if __name__ == "__main__":
    main()
