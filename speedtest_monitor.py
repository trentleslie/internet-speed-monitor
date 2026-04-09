#!/usr/bin/env python3
"""Run speed test and log results to CSV.

Supports dual-ISP monitoring via interface binding.
Uses Ookla's official speedtest CLI (not speedtest-cli from PyPI).

Usage:
    python speedtest_monitor.py                         # Default (no interface binding)
    python speedtest_monitor.py --interface eth0 --isp astound
    python speedtest_monitor.py --interface eth1 --isp tmobile
"""

import argparse
import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def run_speedtest(interface: str | None = None) -> dict:
    """Run Ookla speedtest CLI and return parsed results.

    Args:
        interface: Network interface to bind to (e.g., 'eth0'). None for default.

    Returns:
        Parsed JSON result from speedtest CLI.
    """
    cmd = ["speedtest", "--format=json", "--accept-license"]
    if interface:
        cmd.extend(["--interface", interface])

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"Speedtest failed: {result.stderr}")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Run speed test and log to CSV")
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
    csv_file = DATA_DIR / f"speed_logs_{args.isp}.csv"
    write_header = not csv_file.exists()

    data = run_speedtest(args.interface)

    # Ookla CLI returns speeds in bytes/sec, convert to Mbps
    # Structure differs from speedtest-cli: download/upload are nested objects
    download_bps = data["download"]["bandwidth"]  # bytes/sec
    upload_bps = data["upload"]["bandwidth"]  # bytes/sec

    row = {
        "timestamp": datetime.now().isoformat(),
        "isp": args.isp,
        "interface": args.interface or "default",
        "download_mbps": round(download_bps * 8 / 1_000_000, 2),  # bytes/s -> Mbps
        "upload_mbps": round(upload_bps * 8 / 1_000_000, 2),
        "ping_ms": round(data["ping"]["latency"], 2),
        "jitter_ms": round(data["ping"].get("jitter", 0), 2),
        "server_name": data["server"]["name"],
        "server_location": f"{data['server']['location']}, {data['server']['country']}",
        "result_url": data.get("result", {}).get("url", ""),
    }

    fieldnames = list(row.keys())
    with open(csv_file, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    print(f"[{args.isp}] Logged: {row['download_mbps']} Mbps down, "
          f"{row['upload_mbps']} Mbps up, {row['ping_ms']} ms ping")


if __name__ == "__main__":
    main()
