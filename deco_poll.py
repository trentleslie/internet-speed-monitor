#!/usr/bin/env python3
"""Poll the TP-Link Deco for per-client throughput and log it to CSV.

Part of internet-speed-monitor. Captures real-time per-device up/down rates from
the Deco's local API so speedtest dips can later be classified as household
contention vs. a Pi-side bottleneck (see analyze_contention.py).

Modes:
  (default)  run forever, polling every POLL_INTERVAL seconds
  --once     authorize, poll once, print the active clients, exit (health check)

Credentials are read from ~/.config/deco/.env (DECO_PW); never passed on argv.
"""
import argparse
import os
import sys
import time
from pathlib import Path

from tplinkrouterc6u import TPLinkDecoClient

from monitor_utils import append_rows, load_env, now_iso

HOST = "192.168.68.1"
USERNAME = "admin"  # local Deco auth uses "admin" + the app password, not the email
ENV_PATH = Path(os.path.expanduser("~/.config/deco/.env"))
DATA_DIR = Path(__file__).resolve().parent / "data"
CLIENTS_CSV = DATA_DIR / "deco_clients.csv"
STATUS_CSV = DATA_DIR / "deco_status.csv"
POLL_INTERVAL = 30  # seconds
ERROR_BACKOFF = 5   # seconds to wait before reauth after a failed poll

CLIENTS_HEADER = ["timestamp", "mac", "hostname", "ip", "conn_type", "down_speed", "up_speed"]
STATUS_HEADER = ["timestamp", "poll_ok", "cpu_usage", "mem_usage",
                 "clients_total", "active_clients", "error"]


def extract_rows(status, ts):
    """Pure transform: a Status -> (status_row dict, [active client_row dicts]).

    Only clients with non-zero up or down throughput are emitted as client rows;
    idle clients contribute nothing to contention. A status row is always produced.
    """
    devices = getattr(status, "devices", None) or []
    client_rows = []
    for d in devices:
        down = getattr(d, "down_speed", 0) or 0
        up = getattr(d, "up_speed", 0) or 0
        if down == 0 and up == 0:
            continue
        conn = getattr(d, "type", None)
        conn = getattr(conn, "value", conn)
        client_rows.append({
            "timestamp": ts,
            "mac": str(getattr(d, "macaddress", "") or ""),
            "hostname": getattr(d, "hostname", "") or "",
            "ip": str(getattr(d, "ipaddress", "") or ""),
            "conn_type": "" if conn is None else conn,
            "down_speed": down,
            "up_speed": up,
        })
    status_row = {
        "timestamp": ts,
        "poll_ok": True,
        "cpu_usage": getattr(status, "cpu_usage", ""),
        "mem_usage": getattr(status, "mem_usage", ""),
        "clients_total": getattr(status, "clients_total", len(devices)),
        "active_clients": len(client_rows),
        "error": "",
    }
    return status_row, client_rows


def failure_row(ts, err):
    return {
        "timestamp": ts, "poll_ok": False, "cpu_usage": "", "mem_usage": "",
        "clients_total": "", "active_clients": "", "error": str(err)[:200],
    }


def write_poll(status, ts):
    status_row, client_rows = extract_rows(status, ts)
    append_rows(STATUS_CSV, STATUS_HEADER, [status_row])
    append_rows(CLIENTS_CSV, CLIENTS_HEADER, client_rows)
    return status_row, client_rows


def make_client(password):
    return TPLinkDecoClient(HOST, password, username=USERNAME, verify_ssl=False, timeout=15)


def do_iteration(client, ts, reauth):
    """Run one poll. On failure, log a poll_ok=False row and reauthorize.

    Returns the client to use for the next iteration (the same one on success,
    a freshly authorized one on failure). Never raises -- the loop must not die.
    """
    try:
        write_poll(client.get_status(), ts)
        return client
    except Exception as e:
        append_rows(STATUS_CSV, STATUS_HEADER, [failure_row(ts, e)])
        print(f"[{ts}] poll failed: {e!r}; reauthorizing", flush=True)
        time.sleep(ERROR_BACKOFF)
        try:
            return reauth()
        except Exception as e2:
            print(f"[{ts}] reauth failed: {e2!r}", flush=True)
            return client


def run_loop(password):
    DATA_DIR.mkdir(exist_ok=True)
    try:
        client = _authorized(password)
    except Exception as e:
        # e.g. network not up yet at boot; the loop's reauth path will recover.
        print(f"initial authorize failed: {e!r}; will retry in loop", flush=True)
        client = make_client(password)
    print(f"deco_poll: polling {HOST} every {POLL_INTERVAL}s -> "
          f"{STATUS_CSV.name} / {CLIENTS_CSV.name}", flush=True)
    while True:
        start = time.monotonic()
        ts = now_iso()
        client = do_iteration(client, ts, lambda: _authorized(password))
        elapsed = time.monotonic() - start
        time.sleep(max(0, POLL_INTERVAL - elapsed))


def _authorized(password):
    c = make_client(password)
    c.authorize()
    return c


def run_once(password):
    DATA_DIR.mkdir(exist_ok=True)
    client = make_client(password)
    client.authorize()
    ts = now_iso()
    status_row, client_rows = write_poll(client.get_status(), ts)
    print(f"[{ts}] poll_ok=True cpu={status_row['cpu_usage']} "
          f"mem={status_row['mem_usage']} clients={status_row['clients_total']} "
          f"active={status_row['active_clients']}")
    for r in client_rows:
        print(f"  {r['hostname']:<16} {r['ip']:<15} {r['conn_type']:<10} "
              f"down={r['down_speed']} up={r['up_speed']}")
    try:
        client.logout()
    except Exception:
        pass
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Poll Deco for per-client throughput")
    parser.add_argument("--once", action="store_true",
                        help="authorize, poll once, print active clients, exit")
    args = parser.parse_args(argv)

    try:
        env = load_env(ENV_PATH)
    except FileNotFoundError:
        print(f"ERROR: env file not found at {ENV_PATH}", file=sys.stderr)
        return 2
    password = env.get("DECO_PW")
    if not password:
        print("ERROR: DECO_PW missing or empty in env", file=sys.stderr)
        return 2

    if args.once:
        try:
            return run_once(password)
        except Exception as e:
            print(f"ERROR: one-shot poll failed: {e!r}", file=sys.stderr)
            return 1

    run_loop(password)
    return 0


if __name__ == "__main__":
    sys.exit(main())
