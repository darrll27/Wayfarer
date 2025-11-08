import time, threading, queue, logging
from typing import Optional
from pymavlink import mavutil
from wayfarer.core.packet import Packet
from wayfarer.core.command_mapper import send_command
from .mavlink_general import MavlinkGeneral


class MavlinkSerial(MavlinkGeneral):
    """Serial-specific subclass using the generic MAVLink base transport."""

    def __init__(self, name: str, endpoint: str, on_discover, on_packet):
        super().__init__(name, endpoint, on_discover, on_packet)
        self._port = None
        self._baud = None

    # inherit set_source_identity from base

    def _open_connection(self):
        # Parse endpoint like serial:/dev/ttyUSB0:115200
        parts = self.endpoint.split(":")
        if len(parts) < 3:
            raise ValueError(f"Invalid serial endpoint: {self.endpoint}")
        self._port, self._baud = parts[1], int(parts[2])
        return mavutil.mavlink_connection(self._port, baud=self._baud)

    # stop inherited

    # connect loop inherited

    # rx loop inherited

    # tx loop inherited

    # write inherited
