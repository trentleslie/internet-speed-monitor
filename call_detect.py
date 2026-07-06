#!/usr/bin/env python3
"""Detect whether a work machine is currently on a video call, by reading recent
rows of the Deco contention log (data/deco_clients.csv).

Used by the speedtest gate so a saturating speedtest never runs during a Zoom
call. Reads the existing contention data (no extra Deco auth). A call shows up as
a work host with sustained upload above a threshold. Indeterminate states (no/stale
data) return active=False so the caller can fail safe to running the test.
"""
import csv
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CLIENTS_CSV = DATA_DIR / "deco_clients.csv"
CLIENTS_HEADER = "timestamp,mac,hostname,ip,conn_type,down_speed,up_speed"

WORK_HOSTS = {"MacBookPro", "pop-os"}   # Trent's real-meeting machines (confirmed 2026-06-26)
# A video call is BIDIRECTIONAL: you send your camera (up) AND receive others' video (down) at once.
# Background sync goes up-only (MacBookPro idle: up bursts ~1Mbps, down <250kbps); streaming/downloads
# go down-only. Requiring BOTH directions elevated separates a real call from either confounder.
DOWN_THRESHOLD_KBPS = 250  # recalibrated 2026-06-26 vs a live MacBook Pro video call: an active call is
                           # ~symmetric (both ~300-600 kbps); background sync is asymmetric (up~1Mbps, down<250),
                           # so a 250 down-floor catches the call yet still rejects sync. (Camera-off/quiet
                           # calls sit <250 both ways and remain undetectable by traffic alone.)
UP_FLOOR_KBPS = 200        # plus non-trivial upload = interactive (your cam/mic), not passive streaming
WINDOW_S = 150             # 2.5-min lookback
MIN_HITS = 2               # require 2 qualifying polls -> sustained, not an isolated blip
STALE_S = 90               # newest row older than this -> data stale -> indeterminate


def parse_rows(text):
    return list(csv.DictReader(text.splitlines()))


def _ts(row):
    try:
        return datetime.fromisoformat(row["timestamp"])
    except (KeyError, ValueError):
        return None


def _kbps(row, field):
    try:
        return float(row.get(field, 0) or 0)
    except ValueError:
        return 0.0


def is_call_active(rows, now, work_hosts=WORK_HOSTS, down_threshold=DOWN_THRESHOLD_KBPS,
                   up_floor=UP_FLOOR_KBPS, window_s=WINDOW_S, min_hits=MIN_HITS, stale_s=STALE_S):
    """Pure. rows: list of dicts from deco_clients.csv; now: datetime.
    A poll qualifies as call-like when a work host has BOTH down>=down_threshold and up>=up_floor
    (bidirectional = sending camera + receiving video). Returns (active, reason); indeterminate
    states (no/stale data) return (False, 'indeterminate: ...') so the caller can fail safe."""
    if not rows:
        return False, "indeterminate: no deco data"
    times = [t for t in (_ts(r) for r in rows) if t is not None]
    if not times:
        return False, "indeterminate: no parseable timestamps"
    if (now - max(times)) > timedelta(seconds=stale_s):
        return False, f"indeterminate: stale deco data (newest {max(times).isoformat()})"

    cutoff = now - timedelta(seconds=window_s)
    hits = {}
    for r in rows:
        t = _ts(r)
        if t is None or t < cutoff:
            continue
        if r.get("hostname", "") not in work_hosts:
            continue
        if _kbps(r, "down_speed") >= down_threshold and _kbps(r, "up_speed") >= up_floor:
            hits[r["hostname"]] = hits.get(r["hostname"], 0) + 1
    for host, n in hits.items():
        if n >= min_hits:
            return True, f"call active: {host} (down>={down_threshold},up>={up_floor}) x{n}"
    return False, "no call detected"


def read_recent(path=CLIENTS_CSV, tail_bytes=65536):
    """Read the tail of the clients CSV (small reads keep this cheap as the file grows)."""
    p = Path(path)
    if not p.exists():
        return []
    size = p.stat().st_size
    with open(p) as f:
        if size > tail_bytes:
            f.seek(size - tail_bytes)
            f.readline()  # discard the partial first line
            text = CLIENTS_HEADER + "\n" + f.read()
        else:
            text = f.read()
    return parse_rows(text)
