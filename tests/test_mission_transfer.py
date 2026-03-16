import io
from pymavlink import mavutil


def make_mav_writer():
    buf = io.BytesIO()
    mav = mavutil.mavlink.MAVLink(buf)
    return mav, buf


def test_mission_upload_sequence():
    """Simulate a mission upload sequence: GCS sends MISSION_COUNT then MISSION_ITEM_INTs.

    This test constructs the expected messages and verifies sequence numbers and counts.
    """
    mav, _ = make_mav_writer()

    # Example mission: two items
    mission = [
        {"seq": 0, "frame": 0, "command": 16, "x": 0, "y": 0, "z": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "x": 0, "y": 0, "z": 20.0},
    ]

    # GCS would send MISSION_COUNT first
    count_msg = mav.mission_count_encode(255, 0, len(mission))
    assert hasattr(count_msg, "count") and count_msg.count == len(mission)

    # Then GCS sends each MISSION_ITEM_INT
    items = []
    for it in mission:
        msg = mav.mission_item_int_encode(
            255,
            0,
            int(it["seq"]),
            int(it["frame"]),
            int(it["command"]),
            0,
            1,
            0.0,
            0.0,
            0.0,
            0.0,
            int(it["x"]),
            int(it["y"]),
            float(it["z"]),
        )
        items.append(msg)

    # Verify sequence numbers
    assert [m.seq for m in items] == [0, 1]


def test_mission_download_sequence():
    """Simulate vehicle -> GCS mission download: vehicle sends MISSION_COUNT then MISSION_ITEM_INTs.

    Verify that a receiver can reconstruct the mission list from the sequence of items.
    """
    mav, _ = make_mav_writer()

    vehicle_mission = [
        {"seq": 0, "frame": 0, "command": 16, "x": 11111111, "y": 22222222, "z": 30.0},
        {"seq": 1, "frame": 0, "command": 16, "x": 33333333, "y": 44444444, "z": 40.0},
    ]

    count_msg = mav.mission_count_encode(1, 1, len(vehicle_mission))
    assert count_msg.count == 2

    recv = {}
    for it in vehicle_mission:
        msg = mav.mission_item_int_encode(
            1,
            1,
            int(it["seq"]),
            int(it["frame"]),
            int(it["command"]),
            0,
            1,
            0.0,
            0.0,
            0.0,
            0.0,
            int(it["x"]),
            int(it["y"]),
            float(it["z"]),
        )
        # receiver would store by seq
        recv[msg.seq] = {"x": msg.x, "y": msg.y, "z": msg.z}

    # Reconstruct mission ordered by seq
    reconstructed = [recv[i] for i in sorted(recv.keys())]
    assert reconstructed[0]["z"] == 30.0 and reconstructed[1]["z"] == 40.0
