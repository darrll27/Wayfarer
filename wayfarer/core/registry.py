import time
from typing import Dict, Set

class DeviceRegistry:
    def __init__(self):
        self._store: Dict[str, dict] = {}

    def device_id_for_mav(self, sysid: int) -> str:
        return f"mav_sys{sysid}"

    def upsert_mav(self, sysid: int, origin_transport: str, compid: int = None) -> str:
        """Register or update a MAV device by sysid. Optionally record component id (compid).

        Returns the canonical device_id (mav_sys<N>)."""
        did = self.device_id_for_mav(sysid)
        now = time.time()
        dev = self._store.get(did, {
            "schema": "mavlink",
            "sysid": sysid,
            "compid": compid,
            "transports": set(),  # type: Set[str]
            "first_seen": now,
        })
        dev["last_seen"] = now
        # Update compid if provided (prefer latest non-None)
        if compid is not None:
            dev["compid"] = compid
        dev["transports"].add(origin_transport)
        self._store[did] = dev
        return did

    def transports_for(self, device_id: str) -> Set[str]:
        dev = self._store.get(device_id)
        return set(dev["transports"]) if dev else set()

    def snapshot(self) -> Dict[str, dict]:
        # return JSON-friendly snapshot
        out = {}
        for k, v in self._store.items():
            out[k] = {**v, "transports": list(v["transports"])}
        return out

    def sysid_for_device(self, device_id: str):
        """Return sysid for a given device_id, or None if not known."""
        dev = self._store.get(device_id)
        if not dev:
            return None
        return dev.get("sysid")

    def compid_for_device(self, device_id: str):
        """Return component id for a given device_id, or None if not known."""
        dev = self._store.get(device_id)
        if not dev:
            return None
        return dev.get("compid")
