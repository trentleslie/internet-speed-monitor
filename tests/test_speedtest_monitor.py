"""Tests for speedtest_monitor.run_speedtest command construction (interface +
pinned server-id passthrough to the Ookla CLI)."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speedtest_monitor as sm  # noqa: E402

FAKE_JSON = json.dumps({
    "download": {"bandwidth": 1}, "upload": {"bandwidth": 1},
    "ping": {"latency": 9.0, "jitter": 1.0},
    "server": {"name": "Astound", "location": "Port Orchard", "country": "US", "id": 69016},
})


class FakeCompleted:
    returncode = 0
    stdout = FAKE_JSON
    stderr = ""


def capture_cmd(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def test_run_speedtest_pins_server_and_binds_interface(monkeypatch):
    seen = capture_cmd(monkeypatch)
    sm.run_speedtest(interface="eth0", server_id="69016")
    assert "--interface" in seen["cmd"] and "eth0" in seen["cmd"]
    assert "--server-id=69016" in seen["cmd"]


def test_run_speedtest_auto_selects_without_server_id(monkeypatch):
    seen = capture_cmd(monkeypatch)
    sm.run_speedtest(interface="eth0")
    assert not any(str(a).startswith("--server-id") for a in seen["cmd"])
