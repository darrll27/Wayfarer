# HIL / SIL tests

This folder contains optional hardware-in-the-loop (HIL) and software-in-the-loop (SIL) tests.

Running
- These tests are skipped by default. To run them, set the environment variable `RUN_HIL=1`.

Example (macOS / zsh):

1) Run the full HIL test suite (serial + UDP tests will be attempted; UDP requires an active MAVLink UDP endpoint):

```bash
# activate your venv (optional)
source .venv/bin/activate

# enable HIL tests
export RUN_HIL=1

# serial device used for Pixhawk (example)
export PIXHAWK_DEVICE=/dev/cu.usbmodem01
export PIXHAWK_BAUD=115200

# UDP endpoint used by the UDP HIL test (example: QGroundControl or SITL)
export QGC_UDP=127.0.0.1:14550

# run all HIL tests (from project root)
PYTHONPATH=. pytest hil_sil_tests -q
```

2) Run only the serial mission upload/download test (useful when hardware is attached):

```bash
export RUN_HIL=1 PIXHAWK_DEVICE=/dev/cu.usbmodem01 PIXHAWK_BAUD=115200 PYTHONPATH=. pytest -q hil_sil_tests/test_mission_upload_download_serial.py::test_mission_upload_download_serial
```

3) Run only the UDP mission upload/download test (ensure `QGC_UDP` points to an active UDP heartbeat source):

```bash
export RUN_HIL=1 QGC_UDP=127.0.0.1:14550 PYTHONPATH=. pytest -q hil_sil_tests/test_mission_upload_download_udp.py::test_mission_upload_download_udp
```

Routing serial to UDP for local UDP validation
- If you don't have a separate UDP MAVLink source but want to validate the UDP test locally, you can bridge your serial device to a UDP port. Two common approaches:

- Using mavproxy (recommended if installed):

```bash
# forward serial -> udp (MAVProxy will publish heartbeats and traffic to udp:127.0.0.1:14550)
mavproxy.py --master=/dev/cu.usbmodem01:115200 --out=udp:127.0.0.1:14550 --console
```

- Using socat (simple raw bridge; may be noisy):

```bash
# forward serial device to UDP port (socat will copy raw bytes)
socat -d -d /dev/cu.usbmodem01,raw,echo=0 UDP:127.0.0.1:14550
```

Notes and safety
- By default these tests only open the serial/UDP connection and wait for a heartbeat.
- Write operations (mode changes, mission uploads) are intentionally gated: set `RUN_HIL_WRITE=1` to allow tests to perform write actions. Use that with extreme caution on real vehicles.

Reports
- Each HIL test writes a human-readable report to `hil_sil_tests/reports/<test_name>.report.txt` summarizing SKIPPED/PASS/FAIL, duration, and details. Check those files after test runs to get quick pass/fail artifacts.


Safety
- By default these tests only open the serial/UDP connection and wait for a heartbeat.
- Write operations (mode changes, mission uploads) are intentionally disabled unless
  `RUN_HIL_WRITE=1` is set. Use that with extreme caution when testing on real vehicles.

Files
- `test_pixhawk_heartbeat.py` — verifies Pixhawk heartbeat on specified serial device.
- `test_qgc_heartbeat.py` — verifies QGC heartbeat via UDP.

Verification status (current)
- Serial mission upload/download: verified in this workspace — the serial HIL test `test_mission_upload_download_serial.py` was run with `RUN_HIL=1` against a Pixhawk on `/dev/cu.usbmodem01` at 115200 and produced a PASS report (see `hil_sil_tests/reports/test_mission_upload_download_serial.report.txt`).
- UDP mission upload/download: not yet verified — the UDP HIL test `test_mission_upload_download_udp.py` is implemented and will run when a MAVLink UDP endpoint (for example QGroundControl or a router) is actively publishing heartbeats on the `QGC_UDP` address. During a recent run the test failed early because no heartbeat was observed on the configured UDP address/port.

How to validate UDP locally
- If you want to validate the UDP test locally prior to connecting real hardware, you can run a local MAVLink endpoint (SITL or a proxy) that publishes on the configured `QGC_UDP` (default example port in this file). Once a heartbeat is visible on that UDP port, re-run the UDP test with `RUN_HIL=1` and it should proceed.
