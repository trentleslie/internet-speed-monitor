#!/usr/bin/env python3
"""WiFi signal quality monitoring for location comparison.

Captures signal strength, latency to router, and optional speed test results
to help identify optimal placement for a Raspberry Pi streaming setup.

Supports both interactive testing and automated monitoring via cron.

Usage:
    # Set current location (persists to config file)
    python wifi_test.py --set-location dining_room

    # Run single test (uses configured location)
    python wifi_test.py

    # Run test with explicit location
    python wifi_test.py --location bedroom

    # Automated monitoring (quiet mode for cron)
    python wifi_test.py --quiet --skip-speedtest

    # Interactive mode with prompts
    python wifi_test.py --interactive
"""

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

DATA_DIR = Path(__file__).parent / "data" / "phase2"
CSV_FILE = DATA_DIR / "wifi_signal_tests.csv"
CONFIG_FILE = DATA_DIR / "wifi_test_config.json"

# Router IP for latency testing (Astound router)
ROUTER_IP = "192.168.68.1"

# Number of ping samples
PING_COUNT = 10


def load_config() -> dict:
    """Load configuration from JSON file."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_config(config: dict):
    """Save configuration to JSON file."""
    DATA_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_wifi_signal() -> dict | None:
    """Get current WiFi signal information from nmcli.

    Returns:
        Dict with signal_pct, channel, bssid, ssid, or None if not connected.
    """
    try:
        # Get list of visible networks with signal strength
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,CHAN,BSSID", "dev", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None

        # Get currently connected SSID
        conn_result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Find active WiFi connection
        active_ssid = None
        for line in conn_result.stdout.strip().split("\n"):
            if line and "wlan" in line.lower():
                parts = line.split(":")
                if parts:
                    active_ssid = parts[0]
                    break

        if not active_ssid:
            return None

        # Parse wifi list to find our connected network
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            # Format: SSID:SIGNAL:CHAN:BSSID
            parts = line.split(":")
            if len(parts) >= 4:
                ssid = parts[0]
                if ssid == active_ssid:
                    return {
                        "ssid": ssid,
                        "signal_pct": int(parts[1]) if parts[1].isdigit() else 0,
                        "channel": parts[2],
                        "bssid": parts[3] if len(parts) > 3 else "",
                    }

        return None
    except Exception as e:
        return None


def ping_router(count: int = PING_COUNT) -> dict:
    """Ping the router and return latency statistics.

    Args:
        count: Number of pings to send.

    Returns:
        Dict with avg_ms, min_ms, max_ms, stddev_ms, packet_loss_pct.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", "2", ROUTER_IP],
            capture_output=True,
            text=True,
            timeout=30
        )

        latencies = []
        packet_loss = 0.0

        for line in result.stdout.split("\n"):
            # Parse individual ping times: "time=X.XX ms"
            if "time=" in line:
                match = re.search(r"time=(\d+\.?\d*)", line)
                if match:
                    latencies.append(float(match.group(1)))

            # Parse packet loss: "X% packet loss"
            if "packet loss" in line:
                match = re.search(r"(\d+)%\s+packet loss", line)
                if match:
                    packet_loss = float(match.group(1))

        if latencies:
            return {
                "avg_ms": round(mean(latencies), 2),
                "min_ms": round(min(latencies), 2),
                "max_ms": round(max(latencies), 2),
                "stddev_ms": round(stdev(latencies), 2) if len(latencies) > 1 else 0.0,
                "packet_loss_pct": packet_loss,
            }
        else:
            return {
                "avg_ms": None,
                "min_ms": None,
                "max_ms": None,
                "stddev_ms": None,
                "packet_loss_pct": 100.0,
            }
    except Exception:
        return {
            "avg_ms": None,
            "min_ms": None,
            "max_ms": None,
            "stddev_ms": None,
            "packet_loss_pct": 100.0,
        }


def run_speedtest() -> dict:
    """Run Ookla speedtest bound to WiFi interface.

    Returns:
        Dict with download_mbps, upload_mbps, or None values on failure.
    """
    try:
        # Bind to wlan0 interface for WiFi-specific test
        result = subprocess.run(
            ["speedtest", "--format=json", "--accept-license", "--interface", "wlan0"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            return {"download_mbps": None, "upload_mbps": None}

        data = json.loads(result.stdout)

        # Ookla CLI returns speeds in bytes/sec, convert to Mbps
        download_bps = data["download"]["bandwidth"]
        upload_bps = data["upload"]["bandwidth"]

        return {
            "download_mbps": round(download_bps * 8 / 1_000_000, 2),
            "upload_mbps": round(upload_bps * 8 / 1_000_000, 2),
        }
    except Exception:
        return {"download_mbps": None, "upload_mbps": None}


def run_test(location: str, include_speedtest: bool = True, quiet: bool = False) -> dict:
    """Run a complete WiFi test cycle.

    Args:
        location: Name of the test location (e.g., "dining_room").
        include_speedtest: Whether to run the speed test (slower).
        quiet: Suppress verbose output (for cron).

    Returns:
        Dict with all test results.
    """
    if not quiet:
        print(f"\n{'=' * 50}")
        print(f"Testing location: {location}")
        print("=" * 50)

    # Get WiFi signal
    if not quiet:
        print("Checking WiFi signal... ", end="", flush=True)
    wifi = get_wifi_signal()
    if wifi:
        if not quiet:
            print(f"{wifi['signal_pct']}% on channel {wifi['channel']}")
    else:
        if not quiet:
            print("FAILED - not connected to WiFi")
        wifi = {"ssid": None, "signal_pct": None, "channel": None, "bssid": None}

    # Ping router
    if not quiet:
        print(f"Pinging router ({ROUTER_IP})... ", end="", flush=True)
    ping_stats = ping_router()
    if ping_stats["avg_ms"]:
        if not quiet:
            print(f"{ping_stats['avg_ms']} ms avg ({ping_stats['min_ms']}-{ping_stats['max_ms']} ms)")
    else:
        if not quiet:
            print("FAILED - no response")

    # Speed test (optional)
    speed = {"download_mbps": None, "upload_mbps": None}
    if include_speedtest:
        if not quiet:
            print("Running speed test (this may take ~30 seconds)... ", flush=True)
        speed = run_speedtest()
        if speed["download_mbps"] and not quiet:
            print(f"  {speed['download_mbps']} Mbps down, {speed['upload_mbps']} Mbps up")
        elif not quiet:
            print("  FAILED")
    elif not quiet:
        print("Skipping speed test (--skip-speedtest)")

    # Combine results
    return {
        "timestamp": datetime.now().isoformat(),
        "location": location,
        "signal_pct": wifi.get("signal_pct"),
        "channel": wifi.get("channel"),
        "bssid": wifi.get("bssid"),
        "ssid": wifi.get("ssid"),
        "ping_avg_ms": ping_stats["avg_ms"],
        "ping_min_ms": ping_stats["min_ms"],
        "ping_max_ms": ping_stats["max_ms"],
        "ping_stddev_ms": ping_stats["stddev_ms"],
        "packet_loss_pct": ping_stats["packet_loss_pct"],
        "download_mbps": speed["download_mbps"],
        "upload_mbps": speed["upload_mbps"],
    }


def save_result(result: dict, quiet: bool = False):
    """Append test result to CSV file."""
    DATA_DIR.mkdir(exist_ok=True)

    fieldnames = [
        "timestamp", "location", "signal_pct", "channel", "bssid", "ssid",
        "ping_avg_ms", "ping_min_ms", "ping_max_ms", "ping_stddev_ms",
        "packet_loss_pct", "download_mbps", "upload_mbps"
    ]

    write_header = not CSV_FILE.exists()

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(result)

    if not quiet:
        print(f"\nResult saved to {CSV_FILE}")


def print_summary(result: dict):
    """Print a summary of the test result."""
    print("\n" + "-" * 50)
    print("SUMMARY")
    print("-" * 50)
    print(f"Location:     {result['location']}")
    print(f"Signal:       {result['signal_pct']}%" if result['signal_pct'] else "Signal:       N/A")
    print(f"Channel:      {result['channel']}" if result['channel'] else "Channel:      N/A")
    print(f"Router ping:  {result['ping_avg_ms']} ms avg" if result['ping_avg_ms'] else "Router ping:  FAILED")

    if result['download_mbps']:
        print(f"Download:     {result['download_mbps']} Mbps")
        print(f"Upload:       {result['upload_mbps']} Mbps")

    # Quality assessment
    print("\nQuality assessment:")
    if result['signal_pct']:
        if result['signal_pct'] >= 80:
            print("  Signal: EXCELLENT (80%+)")
        elif result['signal_pct'] >= 60:
            print("  Signal: GOOD (60-79%)")
        elif result['signal_pct'] >= 40:
            print("  Signal: FAIR (40-59%)")
        else:
            print("  Signal: POOR (<40%)")

    if result['ping_avg_ms']:
        if result['ping_avg_ms'] < 5:
            print("  Latency: EXCELLENT (<5 ms)")
        elif result['ping_avg_ms'] < 20:
            print("  Latency: GOOD (5-20 ms)")
        elif result['ping_avg_ms'] < 50:
            print("  Latency: FAIR (20-50 ms)")
        else:
            print("  Latency: POOR (>50 ms)")


def print_one_line(result: dict):
    """Print a single-line summary (for cron logs)."""
    signal = f"{result['signal_pct']}%" if result['signal_pct'] else "N/A"
    ping = f"{result['ping_avg_ms']}ms" if result['ping_avg_ms'] else "FAIL"
    dl = f"{result['download_mbps']}Mbps" if result['download_mbps'] else "-"
    ul = f"{result['upload_mbps']}Mbps" if result['upload_mbps'] else "-"
    print(f"[{result['location']}] Signal: {signal}, Ping: {ping}, DL: {dl}, UL: {ul}")


def main():
    parser = argparse.ArgumentParser(
        description="WiFi signal quality monitoring for location comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Set location before automated testing:
    python wifi_test.py --set-location dining_room

  Run automated test (uses configured location):
    python wifi_test.py --quiet --skip-speedtest

  Cron entry (every 5 minutes, signal/ping only):
    */5 * * * * cd ~/internet-speed-monitor && python wifi_test.py -qs

  Cron entry (every 30 minutes, with speed test):
    */30 * * * * cd ~/internet-speed-monitor && python wifi_test.py -q
"""
    )
    parser.add_argument(
        "--location", "-l",
        help="Location name (e.g., dining_room). Uses config if not specified."
    )
    parser.add_argument(
        "--set-location",
        metavar="NAME",
        help="Set the current location in config file (no test run)"
    )
    parser.add_argument(
        "--show-location",
        action="store_true",
        help="Show the currently configured location"
    )
    parser.add_argument(
        "--skip-speedtest", "-s",
        action="store_true",
        help="Skip the speed test (faster, ~15 sec vs ~45 sec)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (one-line summary, for cron)"
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Force interactive mode with prompts"
    )
    parser.add_argument(
        "--cycles", "-c",
        type=int,
        default=1,
        help="Number of test cycles to run (default: 1)"
    )
    args = parser.parse_args()

    config = load_config()

    # Handle --set-location
    if args.set_location:
        location = args.set_location.lower().replace(" ", "_").replace("-", "_")
        config["location"] = location
        save_config(config)
        print(f"Location set to: {location}")
        print(f"Config saved to: {CONFIG_FILE}")
        return

    # Handle --show-location
    if args.show_location:
        location = config.get("location")
        if location:
            print(f"Current location: {location}")
        else:
            print("No location configured. Use --set-location to set one.")
        return

    # Determine location
    location = args.location
    if not location:
        location = config.get("location")

    if not location:
        if args.interactive or sys.stdin.isatty():
            # Interactive mode
            print("\nWiFi Signal Quality Tester")
            print("-" * 30)
            print("Common locations: dining_room, living_room, kitchen, bedroom, office")
            location = input("\nEnter location name: ").strip()
            if not location:
                print("Error: Location name required")
                print("Tip: Use --set-location to configure for automated monitoring")
                return
        else:
            # Non-interactive (cron) mode with no location configured
            print("Error: No location configured for automated monitoring")
            print("Run: python wifi_test.py --set-location <name>")
            sys.exit(1)

    # Normalize location name
    location = location.lower().replace(" ", "_").replace("-", "_")

    # Run test cycles
    for cycle in range(1, args.cycles + 1):
        if args.cycles > 1 and not args.quiet:
            print(f"\n>>> CYCLE {cycle}/{args.cycles} <<<")

        result = run_test(location, include_speedtest=not args.skip_speedtest, quiet=args.quiet)
        save_result(result, quiet=args.quiet)

        if args.quiet:
            print_one_line(result)
        else:
            print_summary(result)

    if args.cycles > 1 and not args.quiet:
        print(f"\nCompleted {args.cycles} test cycles for location: {location}")


if __name__ == "__main__":
    main()
