#!/usr/bin/env python3
"""Classify Astound connectivity outages as "modem held" vs "modem dropped".

An outage is a run of connectivity-check cycles where *every* ping target failed
(see connectivity_astound.csv). For each outage we look at the DOCSIS line-health
log (docsis_status.csv) over the same window and decide who is at fault:

  MODEM_HELD     -> the modem kept full DOCSIS lock through the outage, so the
                    break was upstream of the house (Astound / CMTS / routing).
  MODEM_DROPPED  -> hard RF evidence of a local fault: the modem rebooted (error
                    counters reset) or lost lock (channels dropped / SNR collapsed)
                    during the outage -> coax / drop / modem.
  MODEM_UNREACH  -> the modem's management HTTP endpoint was unreachable for the
                    outage but the RF link never rebooted or lost lock (counters
                    steady across the gap). Ambiguous: a LAN/modem-management blip,
                    NOT the coax. Hitron units refuse this endpoint transiently.
  NO_DOCSIS      -> no modem readings in the window; can't attribute (e.g. the
                    outage predates the DOCSIS poller, or the poller was down).

A single transient bad poll at the edge of a long-but-otherwise-clean outage does
NOT flip the verdict: a failed poll only matters if it dominates the *core* outage
window or is corroborated by an RF reboot/lock-loss. So the Jun 26 2026 55-minute
outage (1 failed poll at recovery, counters never reset) reads as MODEM_HELD, while
its 2-minute 18:33 blip (modem HTTP unreachable, but no reboot) reads as MODEM_UNREACH
rather than a false "your line" verdict.

Results are appended to data/outage_events.csv (idempotent: keyed by event start,
only finalized outages older than --finalize-after are recorded). Run with no args
to update the log and print recent sustained outages; this is what the
outage-classify systemd timer does.
"""
import argparse
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from monitor_utils import append_rows

DATA_DIR = Path(__file__).resolve().parent / "data"
CONN_CSV = DATA_DIR / "connectivity_astound.csv"
DOCSIS_CSV = DATA_DIR / "docsis_status.csv"
EVENTS_CSV = DATA_DIR / "outage_events.csv"

EVENTS_HEADER = ["event_start", "event_end", "duration_s", "down_cycles",
                 "classification", "fault", "docsis_polls", "docsis_degraded", "detail"]

# A run of down cycles is one outage as long as consecutive downs are within this
# gap (bridges a single recovered/missed 60s ping without splitting the event).
GAP_TOLERANCE_S = 180
# Pad the DOCSIS lookup window on each side so a poll straddling the edge counts.
DOCSIS_MARGIN_S = 90
# QAM256 downstream SNR floor; below this a poll is treated as degraded.
SNR_FLOOR_DB = 30.0
# Fraction of *core* (un-padded) polls that must be unreachable to call it MODEM_UNREACH.
UNREACH_FRACTION = 0.5

FAULT = {
    "MODEM_HELD": "Astound / upstream (modem stayed locked)",
    "MODEM_DROPPED": "Your line / modem (rebooted or lost DOCSIS lock)",
    "MODEM_UNREACH": "Ambiguous (modem mgmt unreachable, RF never dropped -- likely LAN/modem blip, not coax)",
    "NO_DOCSIS": "Unknown (no modem data in window)",
}


def read_csv(path):
    """Read a CSV tolerant of CRLF and the stray binary bytes that have crept into
    the long-running connectivity log; honors quoting (docsis error field)."""
    if not path.exists():
        return []
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="ignore").replace("\r", "")
    return list(csv.DictReader(io.StringIO(text)))


def parse_ts(s):
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def find_outages(conn_rows):
    """Group connectivity rows into outage events (all targets down per cycle)."""
    cycles = defaultdict(list)
    for r in conn_rows:
        cycles[r.get("timestamp")].append(r)

    downs = []
    for ts, rows in cycles.items():
        dt = parse_ts(ts)
        if dt is None:
            continue
        if all((r.get("success") or "").strip() != "True" for r in rows):
            downs.append(dt)
    downs.sort()

    events = []
    cur = []
    for dt in downs:
        if cur and (dt - cur[-1]).total_seconds() > GAP_TOLERANCE_S:
            events.append(cur)
            cur = []
        cur.append(dt)
    if cur:
        events.append(cur)

    return [{"start": e[0], "end": e[-1], "cycles": len(e),
             "duration_s": int((e[-1] - e[0]).total_seconds())} for e in events]


def ok(poll):
    return (poll.get("poll_ok") or "").strip() == "True"


def chan_count(poll, key):
    try:
        return int(poll[key])
    except (ValueError, KeyError, TypeError):
        return 0


def typical_lock(docsis_rows):
    """Modal locked-channel counts among healthy polls, for the summary line. The
    mode (not the max) so a one-off bonding spike doesn't masquerade as normal."""
    ds = Counter(chan_count(r, "ds_channels") for r in docsis_rows if ok(r))
    us = Counter(chan_count(r, "us_channels") for r in docsis_rows if ok(r))
    ds.pop(0, None)
    us.pop(0, None)
    return (ds.most_common(1)[0][0] if ds else 0), (us.most_common(1)[0][0] if us else 0)


def healthy_neighbors(docsis_rows, start, end):
    """The last healthy poll before an outage and the first healthy one after it."""
    before = [r for r in docsis_rows if ok(r) and (dt := parse_ts(r["timestamp"])) and dt < start]
    after = [r for r in docsis_rows if ok(r) and (dt := parse_ts(r["timestamp"])) and dt > end]
    b = max(before, key=lambda r: r["timestamp"]) if before else None
    a = min(after, key=lambda r: r["timestamp"]) if after else None
    return b, a


def lock_lost(poll, ds_base, us_base):
    """RF lock loss visible in a *reachable* poll: fewer channels or collapsed SNR."""
    if ds_base and chan_count(poll, "ds_channels") < ds_base:
        return True
    if us_base and chan_count(poll, "us_channels") < us_base:
        return True
    snr = poll.get("min_snr")
    if snr:
        try:
            return float(snr) < SNR_FLOOR_DB
        except ValueError:
            pass
    return False


def total_correcteds(poll):
    try:
        return int(poll["total_correcteds"])
    except (ValueError, KeyError, TypeError):
        return None


def rebooted(before, after):
    """A reboot resets the cumulative error counters: detect it as a drop in
    total_correcteds between the healthy polls bracketing the outage."""
    if not before or not after:
        return False
    c_before, c_after = total_correcteds(before), total_correcteds(after)
    return c_before is not None and c_after is not None and c_after < c_before


def classify(event, docsis_rows):
    lo = event["start"] - timedelta(seconds=DOCSIS_MARGIN_S)
    hi = event["end"] + timedelta(seconds=DOCSIS_MARGIN_S)
    window = [r for r in docsis_rows
              if (dt := parse_ts(r.get("timestamp"))) is not None and lo <= dt <= hi]
    if not window:
        return "NO_DOCSIS", 0, 0

    # Expected lock comes from the healthy polls bracketing *this* outage, not a
    # global max, so a long-past higher-channel period can't force a false lock-loss.
    before, after = healthy_neighbors(docsis_rows, event["start"], event["end"])
    ds_base = max([chan_count(p, "ds_channels") for p in (before, after) if p], default=0)
    us_base = max([chan_count(p, "us_channels") for p in (before, after) if p], default=0)

    # Hard RF evidence of a genuine local fault.
    hard = rebooted(before, after) or any(lock_lost(p, ds_base, us_base) for p in window if ok(p))

    # Unreachability is judged on the polls *inside* the outage; if the poll cadence
    # left none there, fall back to the padded window so an all-unreachable window
    # isn't mislabeled MODEM_HELD.
    core = [r for r in window if event["start"] <= parse_ts(r["timestamp"]) <= event["end"]]
    basis = core or window
    unreach = sum(1 for r in basis if not ok(r))

    degraded = sum(1 for r in window if not ok(r) or lock_lost(r, ds_base, us_base))

    if hard:
        label = "MODEM_DROPPED"
    elif basis and unreach / len(basis) >= UNREACH_FRACTION:
        label = "MODEM_UNREACH"
    else:
        label = "MODEM_HELD"
    return label, len(window), degraded


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="Only consider outages on/after this date (YYYY-MM-DD)")
    ap.add_argument("--min-duration", type=int, default=120,
                    help="Printed-summary cutoff in seconds (default 120); all events still logged")
    ap.add_argument("--finalize-after", type=int, default=300,
                    help="Only record outages whose end is older than this many seconds (default 300)")
    ap.add_argument("--all", action="store_true", help="Print every event, not just sustained ones")
    ap.add_argument("--no-write", action="store_true", help="Don't update outage_events.csv")
    args = ap.parse_args()

    conn_rows = read_csv(CONN_CSV)
    docsis_rows = read_csv(DOCSIS_CSV)
    ds_typ, us_typ = typical_lock(docsis_rows)

    # Default to when DOCSIS logging began: outages before that can't be attributed,
    # so there's no point recording hundreds of pre-poller NO_DOCSIS events.
    if args.since:
        since = datetime.fromisoformat(args.since)
    else:
        docsis_ts = [dt for r in docsis_rows if (dt := parse_ts(r.get("timestamp")))]
        since = min(docsis_ts) if docsis_ts else None

    events = find_outages(conn_rows)
    if since:
        events = [e for e in events if e["end"] >= since]

    now = datetime.now()
    classified = []
    for e in events:
        label, total, degraded = classify(e, docsis_rows)
        e.update(classification=label, polls=total, degraded=degraded,
                 final=(now - e["end"]).total_seconds() >= args.finalize_after)
        classified.append(e)

    # Persist newly finalized events (idempotent on event_start).
    if not args.no_write:
        seen = {r["event_start"] for r in read_csv(EVENTS_CSV)}
        new_rows = []
        for e in classified:
            key = e["start"].isoformat()
            if not e["final"] or key in seen:
                continue
            new_rows.append({
                "event_start": key,
                "event_end": e["end"].isoformat(),
                "duration_s": e["duration_s"],
                "down_cycles": e["cycles"],
                "classification": e["classification"],
                "fault": FAULT[e["classification"]],
                "docsis_polls": e["polls"],
                "docsis_degraded": e["degraded"],
                "detail": f"{e['degraded']}/{e['polls']} polls degraded",
            })
        DATA_DIR.mkdir(exist_ok=True)
        append_rows(EVENTS_CSV, EVENTS_HEADER, new_rows)
        if new_rows:
            print(f"Recorded {len(new_rows)} new outage event(s) to {EVENTS_CSV.name}")

    # Print summary.
    shown = [e for e in classified if args.all or e["duration_s"] >= args.min_duration]
    shown.sort(key=lambda e: e["start"], reverse=True)
    tally = defaultdict(int)
    for e in classified:
        tally[e["classification"]] += 1

    print(f"\nDOCSIS typical lock: {ds_typ} downstream / {us_typ} upstream channels")
    print(f"Outages found: {len(classified)}  "
          f"(held={tally['MODEM_HELD']}, dropped={tally['MODEM_DROPPED']}, "
          f"unreach={tally['MODEM_UNREACH']}, no-data={tally['NO_DOCSIS']})")
    cutoff = "all" if args.all else f">={args.min_duration}s"
    print(f"\nRecent outages ({cutoff}):")
    if not shown:
        print("  (none)")
    for e in shown[:30]:
        mins = e["duration_s"] / 60
        flag = {"MODEM_HELD": "✓ upstream", "MODEM_DROPPED": "✗ YOUR LINE",
                "MODEM_UNREACH": "~ ambiguous", "NO_DOCSIS": "? no-data"}[e["classification"]]
        pend = "" if e["final"] else "  [not yet finalized]"
        print(f"  {e['start']:%Y-%m-%d %H:%M}  {mins:5.1f} min  "
              f"{flag:12s}  ({e['degraded']}/{e['polls']} polls degraded){pend}")


if __name__ == "__main__":
    main()
