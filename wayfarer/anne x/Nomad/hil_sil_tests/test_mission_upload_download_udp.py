import os
import time
import traceback

import pytest
from pymavlink import mavutil

from . import reporter
from .mission_utils import canonicalize_mission, hash_mission

from backend.mav_router.mission_uploader import MissionUploader
from backend.mav_router.mission_downloader import MissionDownloader


RUN_HIL = os.getenv("RUN_HIL", "0") == "1"
QGC_UDP = os.getenv("QGC_UDP", "127.0.0.1:14550")


def test_mission_upload_download_udp():
    test_name = "test_mission_upload_download_udp"
    start = time.time()

    if not RUN_HIL:
        reporter.write_report(test_name, "SKIPPED", details="RUN_HIL not set; set RUN_HIL=1 to enable HIL tests")
        pytest.skip("HIL tests disabled; set RUN_HIL=1 to enable")

    host, port_s = QGC_UDP.split(":")
    port = int(port_s)

    mission = [
        {"seq": 0, "frame": 0, "command": 16, "lat": 11111111, "lon": 22222222, "alt": 10.0},
        {"seq": 1, "frame": 0, "command": 16, "lat": 33333333, "lon": 44444444, "alt": 20.0},
    ]

    conn = None
    try:
        conn = mavutil.mavlink_connection(f"udpout:{host}:{port}")

        # wait for heartbeat from the vehicle/router side
        hb = conn.wait_heartbeat(timeout=10)
        if hb is None:
            duration = time.time() - start
            reporter.write_report(test_name, "FAIL", details="no heartbeat seen on UDP", duration=duration)
            pytest.fail("No heartbeat from vehicle/router on UDP")

        target_sys = hb.get_srcSystem()
        target_comp = hb.get_srcComponent()

        # send a couple GCS heartbeats to stimulate routing
        try:
            for _ in range(3):
                conn.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
                time.sleep(0.05)
        except Exception:
            pass

        uploader = MissionUploader(conn)
        uploader.upload_mission(mission, target_sys=target_sys, target_comp=target_comp, timeout=30)

        downloader = MissionDownloader(conn)
        downloaded = downloader.download_mission(target_sys=target_sys, target_comp=target_comp, timeout=30)

        upl_canon = canonicalize_mission(mission)
        dl_canon = canonicalize_mission(downloaded)
        # normalize frames (some vehicles translate frames during upload/download)
        for it in upl_canon:
            it.pop("frame", None)
        for it in dl_canon:
            it.pop("frame", None)
        upl_hash = hash_mission(upl_canon)
        dl_hash = hash_mission(dl_canon)

        duration = time.time() - start
        if upl_hash != dl_hash:
            reporter.write_report(test_name, "FAIL", details=f"hash_mismatch upl={upl_hash} dl={dl_hash}", duration=duration)
            pytest.fail("Uploaded mission and downloaded mission hashes differ")
        else:
            reporter.write_report(test_name, "PASS", details=f"mission_hash={upl_hash}", duration=duration)
    except Exception as e:
        duration = time.time() - start
        tb = traceback.format_exc()
        reporter.write_report(test_name, "FAIL", details=f"Exception: {e}\n\nTraceback:\n{tb}", duration=duration)
        raise
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
