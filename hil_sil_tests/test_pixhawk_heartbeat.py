import os
import time
import traceback
import pytest

from pymavlink import mavutil

from . import reporter


RUN_HIL = os.getenv("RUN_HIL", "0") == "1"
PIXHAWK_DEVICE = os.getenv("PIXHAWK_DEVICE", "/dev/cu.usbmodem01")
PIXHAWK_BAUD = int(os.getenv("PIXHAWK_BAUD", "115200"))


def test_pixhawk_heartbeat():
    """Connect to Pixhawk serial and wait for a heartbeat.

    This test is hardware-dependent; it will write a report file to
    hil_sil_tests/reports/test_pixhawk_heartbeat.report.txt with the
    outcome (PASS / FAIL / SKIPPED) and helpful details.
    """
    test_name = "test_pixhawk_heartbeat"
    start = time.time()

    if not RUN_HIL:
        reporter.write_report(test_name, "SKIPPED", details="RUN_HIL not set; set RUN_HIL=1 to enable HIL tests")
        pytest.skip("HIL tests disabled; set RUN_HIL=1 to enable")

    conn_str = PIXHAWK_DEVICE
    m = None
    try:
        # pymavlink accepts a device path and baud parameter
        m = mavutil.mavlink_connection(conn_str, baud=PIXHAWK_BAUD)
        # Send a synthetic heartbeat to stimulate the device (some devices
        # respond better when they see a heartbeat from a peer).
        try:
            # Use GCS type to indicate ground station origin
            m.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            # small pause to allow device to see it
            time.sleep(0.2)
        except Exception:
            # best-effort: if sending fails, continue to waiting
            pass
        hb = m.wait_heartbeat(timeout=10)
        duration = time.time() - start
        if hb is None:
            details = f"No heartbeat from Pixhawk at {PIXHAWK_DEVICE}:{PIXHAWK_BAUD}"
            reporter.write_report(test_name, "FAIL", details=details, duration=duration)
            assert False, details
        else:
            details = f"Heartbeat received from sysid={hb.get_srcSystem()} compid={hb.get_srcComponent()}"
            reporter.write_report(test_name, "PASS", details=details, duration=duration)
    except Exception as e:
        duration = time.time() - start
        tb = traceback.format_exc()
        reporter.write_report(test_name, "FAIL", details=f"Exception: {e}\n\nTraceback:\n{tb}", duration=duration)
        raise
    finally:
        try:
            if m is not None:
                m.close()
        except Exception:
            pass
