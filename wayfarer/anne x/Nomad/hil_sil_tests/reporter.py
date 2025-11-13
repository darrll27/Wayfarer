import os
import datetime
import json


REPORT_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _ensure_dir():
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
    except Exception:
        # best-effort; if we can't create the dir, writing will fail later with clearer error
        pass


def write_report(test_name: str, status: str, details: str = "", duration: float | None = None, artifacts: dict | None = None):
    """Write a simple human-readable report file for a test.

    - test_name: short name, used for filename: <test_name>.report.txt
    - status: PASS | FAIL | SKIPPED
    - details: short multi-line string with context
    - duration: seconds (float)
    - artifacts: optional dict of artifact_name -> path or small metadata
    """
    _ensure_dir()
    fname = os.path.join(REPORT_DIR, f"{test_name}.report.txt")
    # Use a timezone-aware UTC timestamp (avoid deprecated utcnow usage)
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = []
    lines.append(f"Test: {test_name}")
    lines.append(f"Timestamp (UTC): {now}")
    lines.append(f"Status: {status}")
    if duration is not None:
        lines.append(f"Duration: {duration:.3f} s")
    lines.append("")
    lines.append("Details:")
    if details:
        # keep details readable; ensure it's a string
        lines.extend(str(details).splitlines())
    else:
        lines.append("(no details)")
    lines.append("")
    if artifacts:
        lines.append("Artifacts:")
        try:
            # pretty-print artifacts as JSON for machine-readability
            lines.append(json.dumps(artifacts, indent=2, ensure_ascii=False))
        except Exception:
            lines.append(str(artifacts))

    # Footer with a tiny generator note
    lines.append("")
    lines.append("Generated-by: hil_sil_tests.reporter")

    # Write atomically to avoid partial files; write to temp then rename
    tmp = fname + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        os.replace(tmp, fname)
    except Exception:
        # fallback: try a non-atomic write
        with open(fname, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
