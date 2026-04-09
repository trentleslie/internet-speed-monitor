#!/usr/bin/env python3
"""Lightweight connectivity check via ping.

Supports dual-ISP monitoring via interface binding.

Usage:
    python connectivity_check.py                         # Default (no interface binding)
    python connectivity_check.py --interface eth0 --isp astound
    python connectivity_check.py --interface eth1 --isp tmobile
"""

import argparse
import csv
import subprocess
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

TARGETS = ["8.8.8.8", "1.1.1.1"]  # Google DNS, Cloudflare DNS


def ping(target: str, interface: str | None = None) -> tuple[float | None, bool]:
    """Ping target and return (latency_ms, success).

    Args:
        target: IP address to ping.
        interface: Network interface to bind to (e.g., 'eth0'). None for default.

    Returns:
        Tuple of (latency in ms or None, success boolean).
    """
    try:
        cmd = ["ping", "-c", "1", "-W", "2"]
        if interface:
            cmd.extend(["-I", interface])
        cmd.append(target)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse "time=X.XX ms" from output
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    time_part = line.split("time=")[1].split()[0]
                    return float(time_part), True
        return None, False
    except Exception:
        return None, False


def main():
    parser = argparse.ArgumentParser(description="Check connectivity via ping")
    parser.add_argument(
        "--interface", "-i",
        help="Network interface to bind to (e.g., eth0, eth1)"
    )
    parser.add_argument(
        "--isp",
        default="default",
        help="ISP identifier for CSV filename (e.g., astound, tmobile)"
    )
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    # Dynamic CSV filename based on ISP
    csv_file = DATA_DIR / f"connectivity_{args.isp}.csv"
    write_header = not csv_file.exists()
    timestamp = datetime.now().isoformat()

    rows = []
    for target in TARGETS:
        latency, success = ping(target, args.interface)
        rows.append({
            "timestamp": timestamp,
            "isp": args.isp,
            "interface": args.interface or "default",
            "target": target,
            "latency_ms": round(latency, 2) if latency else None,
            "success": success,
        })

    fieldnames = ["timestamp", "isp", "interface", "target", "latency_ms", "success"]
    with open(csv_file, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    status = "OK" if all(r["success"] for r in rows) else "FAIL"
    print(f"[{args.isp}] Connectivity: {status} - {[r['latency_ms'] for r in rows]} ms")


if __name__ == "__main__":
    main()
