import argparse
from wayfarer.config.loader import load_config
from wayfarer.core.bridge import Bridge
from wayfarer.routers.mqtt_router import MQTTRouter
from wayfarer.transports.mavlink_udp import MavlinkUDP
from wayfarer.transports.mavlink_serial import MavlinkSerial

def main():
    p = argparse.ArgumentParser("wayfarer")
    p.add_argument("--config", "-c", required=True, help="Path to YAML config")
    args = p.parse_args()

    cfg = load_config(args.config)
    # build MQTT router
    mqtt_router = MQTTRouter("mqtt", cfg["mqtt"], on_cmd=None)  # on_cmd set below
    # build transports
    transports = {}

    # inside the loop creating transports:
    for name, tcfg in cfg["transports"].items():
        if tcfg["type"] == "mavlink_udp":
            transports[name] = MavlinkUDP(
                name=name,
                endpoint=tcfg["endpoint"],
                on_discover=None,
                on_packet=None
            )
        elif tcfg["type"] == "mavlink_serial":
            transports[name] = MavlinkSerial(
                name=name,
                endpoint=tcfg["endpoint"],
                on_discover=None,
                on_packet=None
            )


    # wire up bridge <-> components
    bridge = Bridge(cfg, transports, mqtt_router)
    mqtt_router.on_cmd = bridge.on_cmd
    for t in transports.values():
        t.on_discover = bridge.on_discover_mav
        t.on_packet = bridge.on_transport_packet

    bridge.start()
    try:
        import time
        while True: time.sleep(1)
    except KeyboardInterrupt:
        bridge.stop()
