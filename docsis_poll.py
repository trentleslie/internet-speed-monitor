#!/usr/bin/env python3
"""Poll the Hitron modem's DOCSIS stats every 60s and log channel + status data.

Mirrors deco_poll.py: long-running self-healing systemd service, header-once +
fsync CSV writes, --once health check. Logs per-channel downstream/upstream rows
plus a per-poll status summary, so a failed poll is distinct from a healthy one.

Counters (correcteds/uncorrect) are cumulative since the last modem reboot; the
analysis step computes deltas (and treats a negative delta as a reboot reset).
"""
import argparse
import os
import sys
import time
from pathlib import Path

import hitron_client

from monitor_utils import append_rows, load_env, now_iso

HOST = "192.168.100.1"
ENV_PATH = Path(os.path.expanduser("~/.config/deco/.env"))
DATA_DIR = Path(__file__).resolve().parent / "data"
DS_CSV = DATA_DIR / "docsis_downstream.csv"
US_CSV = DATA_DIR / "docsis_upstream.csv"
STATUS_CSV = DATA_DIR / "docsis_status.csv"
POLL_INTERVAL = 60
ERROR_BACKOFF = 5

DS_HEADER = ["timestamp", "channel_id", "freq_hz", "modulation",
             "power_dbmv", "snr_db", "correcteds", "uncorrect"]
US_HEADER = ["timestamp", "channel_id", "freq_hz", "modulation", "power_dbmv", "symbolrate"]
STATUS_HEADER = ["timestamp", "poll_ok", "min_snr", "max_ds_power", "total_correcteds",
                 "total_uncorrect", "ds_channels", "us_channels", "max_us_power", "error"]


def ds_rows(ds, ts):
    return [{"timestamp": ts, **{k: c.get(k) for k in
            ("channel_id", "freq_hz", "modulation", "power_dbmv", "snr_db", "correcteds", "uncorrect")}}
            for c in ds]


def us_rows(us, ts):
    return [{"timestamp": ts, **{k: c.get(k) for k in
            ("channel_id", "freq_hz", "modulation", "power_dbmv", "symbolrate")}}
            for c in us]


def summarize(ds, us, ts):
    snrs = [c["snr_db"] for c in ds if c.get("snr_db") is not None]
    ds_pow = [c["power_dbmv"] for c in ds if c.get("power_dbmv") is not None]
    us_pow = [c["power_dbmv"] for c in us if c.get("power_dbmv") is not None]
    return {
        "timestamp": ts, "poll_ok": True,
        "min_snr": min(snrs) if snrs else "",
        "max_ds_power": max(ds_pow) if ds_pow else "",
        "total_correcteds": sum(c.get("correcteds") or 0 for c in ds),
        "total_uncorrect": sum(c.get("uncorrect") or 0 for c in ds),
        "ds_channels": len(ds), "us_channels": len(us),
        "max_us_power": max(us_pow) if us_pow else "", "error": "",
    }


def failure_status(ts, err):
    return {"timestamp": ts, "poll_ok": False, "min_snr": "", "max_ds_power": "",
            "total_correcteds": "", "total_uncorrect": "", "ds_channels": "",
            "us_channels": "", "max_us_power": "", "error": str(err)[:200]}


def write_poll(client, ts):
    ds = client.get_downstream()
    us = client.get_upstream()
    append_rows(STATUS_CSV, STATUS_HEADER, [summarize(ds, us, ts)])
    append_rows(DS_CSV, DS_HEADER, ds_rows(ds, ts))
    append_rows(US_CSV, US_HEADER, us_rows(us, ts))
    return ds, us


def make_client():
    env = load_env(ENV_PATH)
    return hitron_client.HitronClient(HOST, env.get("ASTOUND_USERNAME"), env.get("ASTOUND_PW"))


def do_iteration(client, ts, reauth):
    """One poll. On failure: log poll_ok=False, back off, re-create the client. Never raises."""
    try:
        write_poll(client, ts)
        return client
    except Exception as e:
        append_rows(STATUS_CSV, STATUS_HEADER, [failure_status(ts, e)])
        print(f"[{ts}] docsis poll failed: {e!r}; re-logging in", flush=True)
        time.sleep(ERROR_BACKOFF)
        try:
            return reauth()
        except Exception as e2:
            print(f"[{ts}] re-login failed: {e2!r}", flush=True)
            return client


def run_loop():
    DATA_DIR.mkdir(exist_ok=True)
    client = make_client()
    print(f"docsis_poll: polling {HOST} every {POLL_INTERVAL}s -> "
          f"{STATUS_CSV.name} / {DS_CSV.name} / {US_CSV.name}", flush=True)
    while True:
        start = time.monotonic()
        ts = now_iso()
        client = do_iteration(client, ts, make_client)
        time.sleep(max(0, POLL_INTERVAL - (time.monotonic() - start)))


def run_once():
    DATA_DIR.mkdir(exist_ok=True)
    client = make_client()
    ts = now_iso()
    ds, us = write_poll(client, ts)
    s = summarize(ds, us, ts)
    print(f"[{ts}] DS {s['ds_channels']}ch  min_snr={s['min_snr']} "
          f"max_ds_power={s['max_ds_power']} correcteds={s['total_correcteds']} "
          f"uncorrect={s['total_uncorrect']}")
    print(f"        US {s['us_channels']}ch  max_us_power={s['max_us_power']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Poll Hitron modem DOCSIS stats")
    parser.add_argument("--once", action="store_true", help="poll once, print summary, exit")
    args = parser.parse_args(argv)
    try:
        env = load_env(ENV_PATH)
    except FileNotFoundError:
        print(f"ERROR: env file not found at {ENV_PATH}", file=sys.stderr)
        return 2
    if not env.get("ASTOUND_USERNAME") or not env.get("ASTOUND_PW"):
        print("ERROR: ASTOUND_USERNAME/ASTOUND_PW missing or empty in env", file=sys.stderr)
        return 2
    if args.once:
        try:
            return run_once()
        except Exception as e:
            print(f"ERROR: one-shot poll failed: {e!r}", file=sys.stderr)
            return 1
    run_loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
