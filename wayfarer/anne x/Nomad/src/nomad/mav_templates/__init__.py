"""MAV templates for NOMAD - stubs that return structured command descriptors.

These functions return simple dicts describing the intended MAV action and parameters.
They are intentionally lightweight and meant to be translated to actual mavsdk/mavlink calls
in the runtime implementation.
"""

from .commandname import arm, set_mode, set_hold_mode, set_offboard_mode, upload_mission

__all__ = ["arm", "set_mode", "set_hold_mode", "set_offboard_mode", "upload_mission"]
