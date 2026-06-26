#!/usr/bin/env python3
"""Shared helpers for the internet-speed-monitor collectors (deco_poll, docsis_poll).

Kept dependency-free so each collector can import it without pulling in the other's
device library (e.g. docsis_poll must not transitively import the Deco client)."""
import csv
import os
from datetime import datetime


def load_env(path):
    """Parse a simple KEY=value .env file into a dict."""
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def append_rows(path, header, rows):
    """Append rows to a CSV, writing the header only when creating the file.

    Flushes and fsyncs after each write so an abrupt kill never leaves a
    truncated/partial row (the failure mode that corrupted the old connectivity log)."""
    if not rows:
        return
    is_new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())


def now_iso():
    """Naive local-time ISO timestamp, matching every collector's CSV timestamps so
    they line up directly for correlation."""
    return datetime.now().isoformat()
