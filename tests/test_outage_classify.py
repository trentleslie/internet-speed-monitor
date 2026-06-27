"""Tests for outage_classify: outage grouping and the held/dropped/unreach verdict.

The verdict logic is the part worth pinning down -- in particular that a failed
DOCSIS poll only means "your line" when corroborated by an RF reboot (error-counter
reset) or lock loss, not on its own (Hitron's mgmt endpoint blips while RF is fine).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import outage_classify as oc  # noqa: E402


def poll(ts, ok=True, corr=94, ds=28, us=3, snr=38.6):
    """Build a docsis_status row as strings, matching a CSV read."""
    if not ok:
        return {"timestamp": ts, "poll_ok": "False", "min_snr": "", "max_ds_power": "",
                "total_correcteds": "", "total_uncorrect": "", "ds_channels": "",
                "us_channels": "", "max_us_power": "", "error": "unreachable"}
    return {"timestamp": ts, "poll_ok": "True", "min_snr": str(snr), "max_ds_power": "12",
            "total_correcteds": str(corr), "total_uncorrect": "0", "ds_channels": str(ds),
            "us_channels": str(us), "max_us_power": "47", "error": ""}


def minutes(sh, sm, eh, em):
    t, end = datetime(2026, 6, 26, sh, sm, 55), datetime(2026, 6, 26, eh, em, 55)
    while t <= end:
        yield t
        t += timedelta(minutes=1)


def event(sh, sm, eh, em):
    s, e = datetime(2026, 6, 26, sh, sm, 16), datetime(2026, 6, 26, eh, em, 16)
    return {"start": s, "end": e, "cycles": 2, "duration_s": int((e - s).total_seconds())}


def classify(ev, rows):
    return oc.classify(ev, rows)[0]


def test_modem_held_when_locked_through_outage():
    # 55-min outage; one failed poll mid-way but counters never reset -> upstream.
    rows = [poll(t.isoformat(), ok=(t.minute != 30)) for t in minutes(16, 0, 17, 20)]
    assert classify(event(16, 17, 17, 12), rows) == "MODEM_HELD"


def test_modem_dropped_on_counter_reset_reboot():
    # corr 4782 before, modem unreachable during, corr 26 after = a real reboot.
    rows = [poll(t.isoformat(), corr=4782) for t in minutes(13, 10, 13, 13)]
    rows += [poll(datetime(2026, 6, 26, 13, 14, 55).isoformat(), ok=False)]
    rows += [poll(t.isoformat(), corr=26) for t in minutes(13, 15, 13, 18)]
    assert classify(event(13, 14, 13, 15), rows) == "MODEM_DROPPED"


def test_modem_unreach_when_mgmt_blips_without_reset():
    # Mgmt HTTP unreachable for the outage, but corr steady 94->94 = no reboot.
    rows = [poll(t.isoformat()) for t in minutes(18, 30, 18, 31)]
    rows += [poll(datetime(2026, 6, 26, 18, 32, 55).isoformat(), ok=False),
             poll(datetime(2026, 6, 26, 18, 33, 55).isoformat(), ok=False)]
    rows += [poll(t.isoformat()) for t in minutes(18, 34, 18, 36)]
    assert classify(event(18, 33, 18, 34), rows) == "MODEM_UNREACH"


def test_modem_dropped_on_visible_lock_loss():
    # A reachable poll showing fewer locked channels is hard RF evidence.
    rows = [poll(t.isoformat(), ds=(20 if t.minute == 0 else 28)) for t in minutes(14, 0, 14, 3)]
    rows = [poll(t.isoformat()) for t in minutes(13, 57, 13, 59)] + rows
    assert classify(event(14, 0, 14, 1), rows) == "MODEM_DROPPED"


def test_no_docsis_when_window_empty():
    assert classify(event(5, 0, 5, 1), []) == "NO_DOCSIS"


def test_modem_unreach_when_no_poll_inside_core():
    # Short outage whose interval catches no DOCSIS poll, but the padded window is
    # all-unreachable. Must not fall through to MODEM_HELD (empty-core regression).
    rows = [poll(datetime(2026, 6, 26, 18, 57, 55).isoformat()),          # neighbor, outside window
            poll(datetime(2026, 6, 26, 18, 59, 55).isoformat(), ok=False),
            poll(datetime(2026, 6, 26, 19, 0, 55).isoformat(), ok=False),
            poll(datetime(2026, 6, 26, 19, 3, 55).isoformat())]           # neighbor, outside window
    ev = event(19, 0, 19, 0)   # single down cycle at 19:00:16, no poll inside [start, end]
    assert classify(ev, rows) == "MODEM_UNREACH"


def test_local_baseline_ignores_stale_high_channel_history():
    # An old 32-channel era must not make today's normal 28-channel polls look like
    # lock loss during a clean upstream outage (stale-baseline regression).
    rows = [poll(t.isoformat(), ds=32, corr=10) for t in minutes(10, 0, 10, 4)]   # old era
    rows += [poll(t.isoformat(), ds=28, corr=500) for t in minutes(14, 55, 15, 10)]
    assert classify(event(15, 0, 15, 5), rows) == "MODEM_HELD"


def conn(ts, ok):
    s = "True" if ok else "False"
    return [{"timestamp": ts, "success": s, "target": "8.8.8.8"},
            {"timestamp": ts, "success": s, "target": "1.1.1.1"}]


def test_find_outages_groups_consecutive_and_splits_on_gap():
    rows = []
    for m in (0, 1, 2):                      # one 3-cycle outage 10:00-10:02
        rows += conn(f"2026-06-26T10:0{m}:00", ok=False)
    rows += conn("2026-06-26T10:10:00", ok=False)   # gap > 180s -> separate outage
    rows += conn("2026-06-26T10:11:00", ok=True)    # partial-up cycle is not an outage
    rows[-1]["success"] = "True"

    events = oc.find_outages(rows)
    assert len(events) == 2
    assert events[0]["cycles"] == 3 and events[0]["duration_s"] == 120
    assert events[1]["cycles"] == 1
