import os
import sys

# Make sure src is discoverable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from nomad.config import load_config, generate_per_drone_waypoints_for_group


def test_altitude_decrement():
    cfg = load_config()
    per = generate_per_drone_waypoints_for_group(cfg, "example_group")
    assert isinstance(per, dict)
    ids = sorted(per.keys())
    # Need at least two drones in example to validate decrement
    if len(ids) >= 2:
        first_alt = per[ids[0]]["waypoints"][0]["alt"]
        second_alt = per[ids[1]]["waypoints"][0]["alt"]
        assert first_alt == second_alt + 1
