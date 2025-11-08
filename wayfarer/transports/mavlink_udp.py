import time, logging
from pymavlink import mavutil
from .mavlink_general import MavlinkGeneral

class MavlinkUDP(MavlinkGeneral):
    """UDP-specific subclass using the generic MAVLink base transport."""

    def _open_connection(self):
        # Endpoint is already a pymavlink URL (e.g., udp:0.0.0.0:14550)
        return mavutil.mavlink_connection(self.endpoint)
