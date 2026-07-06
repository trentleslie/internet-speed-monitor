"""Tests for call_detect.is_call_active: bidirectional (down + up) call detection
that rejects MacBook Pro's up-only background sync and pure downloads/streaming."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import call_detect as cd  # noqa: E402

NOW = datetime(2026, 6, 26, 11, 0, 0)


def row(host, up, down, secs_ago):
    return {
        "timestamp": (NOW - timedelta(seconds=secs_ago)).isoformat(),
        "mac": "AA", "hostname": host, "ip": "1.1.1.1",
        "conn_type": "host_5g", "down_speed": str(down), "up_speed": str(up),
    }


def test_video_call_both_directions_is_call():
    # camera up + receiving video down, sustained
    rows = [row("pop-os", 350, 1900, 10), row("pop-os", 7509, 1500, 40)]
    active, reason = cd.is_call_active(rows, NOW)
    assert active is True
    assert "pop-os" in reason


def test_symmetric_low_kbps_call_is_detected():
    # ~400/400 kbps symmetric video call (camera on, both directions modest). Detected under the
    # recalibrated 250 down-floor; MISSED under the old 700. Regression guard against silent revert.
    rows = [row("pop-os", 400, 400, 10), row("pop-os", 420, 380, 40)]
    active, reason = cd.is_call_active(rows, NOW)
    assert active is True
    assert "pop-os" in reason


def test_background_sync_up_only_is_not_call():
    # MacBook Pro idle background: ~1Mbps up bursts, download stays low -> NOT a call
    rows = [row("MacBookPro", 1092, 107, 10), row("MacBookPro", 1045, 138, 40),
            row("MacBookPro", 699, 104, 70)]
    active, _ = cd.is_call_active(rows, NOW)
    assert active is False


def test_streaming_down_only_is_not_call():
    # high download, no upload (watching a video) -> NOT a call
    rows = [row("pop-os", 5, 8000, 10), row("pop-os", 8, 6000, 40)]
    active, _ = cd.is_call_active(rows, NOW)
    assert active is False


def test_single_qualifying_poll_not_sustained():
    rows = [row("pop-os", 400, 2000, 10), row("pop-os", 50, 100, 40)]  # only 1 bidirectional hit
    active, _ = cd.is_call_active(rows, NOW)
    assert active is False


def test_non_work_host_does_not_gate():
    # even a perfect call signature on a non-work host is ignored
    rows = [row("BirdWeather-PUC", 5000, 5000, 10), row("BirdWeather-PUC", 5000, 5000, 40)]
    active, _ = cd.is_call_active(rows, NOW)
    assert active is False


def test_below_thresholds_not_call():
    rows = [row("MacBookPro", 100, 90, 10), row("MacBookPro", 120, 80, 40)]
    active, _ = cd.is_call_active(rows, NOW)
    assert active is False


def test_old_rows_outside_window_ignored():
    # fresh newest row (not stale) below threshold + an old call-like row outside the 150s window
    rows = [row("pop-os", 7000, 2000, 300), row("pop-os", 50, 50, 10)]
    active, reason = cd.is_call_active(rows, NOW)
    assert active is False
    assert reason == "no call detected"


def test_stale_data_is_indeterminate():
    rows = [row("pop-os", 350, 1900, 600), row("pop-os", 400, 1500, 630)]
    active, reason = cd.is_call_active(rows, NOW)
    assert active is False
    assert reason.startswith("indeterminate")


def test_empty_rows_indeterminate():
    active, reason = cd.is_call_active([], NOW)
    assert active is False
    assert reason.startswith("indeterminate")


def test_read_recent_missing_file(tmp_path):
    assert cd.read_recent(tmp_path / "nope.csv") == []


def test_read_recent_parses_small_file(tmp_path):
    p = tmp_path / "deco_clients.csv"
    p.write_text(cd.CLIENTS_HEADER + "\n"
                 + row("pop-os", 350, 1900, 10)["timestamp"] + ",AA,pop-os,1.1.1.1,host_5g,1900,350\n")
    rows = cd.read_recent(p)
    assert len(rows) == 1 and rows[0]["hostname"] == "pop-os"
