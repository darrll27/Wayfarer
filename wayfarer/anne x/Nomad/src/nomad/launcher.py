"""Launcher orchestration for staggered group launches.

This module schedules launches per group using multiprocessing to keep the
controller responsive. Launch steps are best-effort and currently invoke
`mav_templates` to generate command descriptors; wiring to mavsdk happens in
the runtime connector.
"""
import multiprocessing
import time
import os
from typing import List
from .config import load_config
from .mav_templates import set_mode, arm
from .state import set_latest

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _launch_group_proc(group_name: str):
    # Load config and iterate drone list in the order they were defined
    cfg = load_config()
    group = cfg.groups.get(group_name)
    if not group:
        return
    drone_ids = list(group.drones.keys())
    delay = group.launch_delay_seconds

    prev_flying = {}
    for idx, sysid in enumerate(drone_ids):
        # Wait configured delay between launches (skip before first)
        if idx != 0:
            time.sleep(delay)

        # Pre-launch: set mode to MISSION and arm
        cmd_mode = set_mode(sysid, "MISSION")
        cmd_arm = arm(sysid, force=False)

        # For now, record to state and logs as if sent
        set_latest(sysid, {"launch_step": "set_mode", "cmd": cmd_mode})
        set_latest(sysid, {"launch_step": "arm", "cmd": cmd_arm})

        # Simulate a short takeoff/flying state
        set_latest(sysid, {"status": "launched", "sysid": sysid, "ts": time.time()})
        prev_flying[sysid] = True

    # done


class Launcher:
    def __init__(self):
        self.process = None

    def start_group_launch(self, group_name: str):
        if self.process and self.process.is_alive():
            return False
        self.process = multiprocessing.Process(target=_launch_group_proc, args=(group_name,), daemon=True)
        self.process.start()
        return True

    def stop(self):
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(1.0)
        self.process = None
