Notes (Nomad dev + telemetry)

- Backend is UDP-only for telemetry; MQTT bridge topics are not used.
- The data bridge uses udpBindPort=14552 for inbound and gcsPort=14551 for outbound.
- 0.0.0.0 is valid only for UDP bind/listen; outbound UDP must target a real host (local is 127.0.0.1).
- Backend must listen on the same UDP ports as the bridge and have a forward rule to send out.

Current config expectations (local bridge):
- bridge_in: 0.0.0.0:14552
- bridge_out: 127.0.0.1:14551
- forwards: bridge_in -> udp 127.0.0.1:14550

Quick health checks:
- http://localhost:8000/api/status (backend up)
- logs/router_stdout.log should show UDP binds for bridge_in/out
