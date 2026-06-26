#!/usr/bin/env python3
"""Gate the saturating Astound speedtest so it never runs during a Zoom call.

Invoked by the speedtest-astound systemd service in place of speedtest_monitor.py.
Checks recent Deco contention data via call_detect; if a work machine is on a call,
defers and retries for up to MAX_WAIT_S, then skips (recording a marker). Fails
safe: if call state is indeterminate (Deco data stale/missing), runs the test.
"""
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import call_detect

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
GATE_CSV = DATA_DIR / "speedtest_gate.csv"
GATE_HEADER = ["timestamp", "action", "reason", "waited_s"]
SPEEDTEST_CMD = [sys.executable, str(HERE / "speedtest_monitor.py"),
                 "--interface", "eth0", "--isp", "astound"]
MAX_WAIT_S = 300
RETRY_INTERVAL_S = 45


def append_gate(action, reason, waited_s):
    DATA_DIR.mkdir(exist_ok=True)
    is_new = not GATE_CSV.exists()
    with open(GATE_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GATE_HEADER)
        if is_new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(), "action": action,
                    "reason": reason, "waited_s": round(waited_s)})
        f.flush()
        os.fsync(f.fileno())


def run_speedtest():
    return subprocess.call(SPEEDTEST_CMD)


def _default_check():
    return call_detect.is_call_active(call_detect.read_recent(), datetime.now())


def main(max_wait=MAX_WAIT_S, retry_interval=RETRY_INTERVAL_S,
         check=None, runner=run_speedtest, sleep=time.sleep, clock=time.monotonic,
         marker=append_gate):
    """Run the speedtest unless a call is active. Returns the speedtest exit code,
    or 0 if the cycle was skipped."""
    check = check or _default_check
    start = clock()
    while True:
        active, reason = check()
        waited = clock() - start
        if active and waited < max_wait:
            sleep(retry_interval)
            continue
        if active:  # still active at max_wait -> protect the call, skip this cycle
            marker("skipped", reason, waited)
            return 0
        # not active: clear, or indeterminate (fail safe to running)
        if reason.startswith("indeterminate"):
            marker("ran_indeterminate", reason, waited)
        elif waited >= retry_interval:
            marker("ran_after_defer", reason, waited)
        return runner()


if __name__ == "__main__":
    sys.exit(main())
