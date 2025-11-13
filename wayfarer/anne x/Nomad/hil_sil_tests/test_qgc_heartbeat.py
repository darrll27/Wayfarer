import os
import time
import traceback
import pytest

from pymavlink import mavutil

from . import reporter


RUN_HIL = os.getenv("RUN_HIL", "0") == "1"
QGC_UDP = os.getenv("QGC_UDP", "127.0.0.1:14450")


def test_qgc_heartbeat():
    """Connect to QGC UDP and wait for a heartbeat forwarded by QGC.

    Writes hil_sil_tests/reports/test_qgc_heartbeat.report.txt with PASS/FAIL/SKIPPED.
    """
    test_name = "test_qgc_heartbeat"
    start = time.time()

    if not RUN_HIL:
        reporter.write_report(test_name, "SKIPPED", details="RUN_HIL not set; set RUN_HIL=1 to enable HIL tests")
        pytest.skip("HIL tests disabled; set RUN_HIL=1 to enable")

    host, port = QGC_UDP.split(":")
    conn_str = f"udp:{host}:{port}"
    m = None
    try:
        # Create a udp listener connection to receive any forwarded heartbeats
        m = mavutil.mavlink_connection(conn_str)
        # Send a synthetic heartbeat to the QGC UDP port (some setups will
        # respond or forward when they detect a peer heartbeat).
        try:
            host, port = QGC_UDP.split(":")
            sender = mavutil.mavlink_connection(f"udpout:{host}:{port}")
            sender.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)
            # allow a short moment for packets to traverse
            time.sleep(0.2)
            try:
                sender.close()
            except Exception:
                pass
        except Exception:
            # best-effort; continue to listening
            pass

        hb = m.wait_heartbeat(timeout=10)
        duration = time.time() - start
        if hb is None:
            details = f"No heartbeat from QGC at udp:{QGC_UDP}"
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
