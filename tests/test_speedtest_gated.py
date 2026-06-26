"""Tests for speedtest_gated.main: run/defer/skip/fail-safe logic with injected
check, runner, sleep, clock, and marker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import speedtest_gated as sg  # noqa: E402


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, action, reason, waited):
        self.calls.append((action, reason, round(waited)))


def make_clock(values):
    seq = list(values)
    return lambda: seq.pop(0)


def test_runs_immediately_when_clear():
    runner = lambda: 0
    ran = []
    marker = Recorder()
    rc = sg.main(check=lambda: (False, "no call detected"),
                 runner=lambda: ran.append(1) or 7,
                 sleep=lambda s: None, clock=make_clock([0, 0]), marker=marker)
    assert rc == 7
    assert ran == [1]
    assert marker.calls == []  # clean run, no marker


def test_defers_then_runs_when_call_clears():
    # 1st check active, 2nd check clear; clock: start=0, waited(active)=10, waited(clear)=60
    checks = iter([(True, "call active: pop-os"), (False, "no call detected")])
    slept = []
    ran = []
    marker = Recorder()
    rc = sg.main(check=lambda: next(checks),
                 runner=lambda: ran.append(1) or 0,
                 sleep=lambda s: slept.append(s),
                 clock=make_clock([0, 10, 60]), retry_interval=45, marker=marker)
    assert ran == [1]
    assert slept == [45]                      # deferred once
    assert marker.calls[0][0] == "ran_after_defer"


def test_skips_when_call_active_past_max_wait():
    runner = lambda: (_ for _ in ()).throw(AssertionError("should not run"))
    marker = Recorder()
    rc = sg.main(check=lambda: (True, "call active: MacBookPro"),
                 runner=runner, sleep=lambda s: None,
                 clock=make_clock([0, 1000]), max_wait=300, marker=marker)
    assert rc == 0
    assert marker.calls == [("skipped", "call active: MacBookPro", 1000)]


def test_indeterminate_runs_fail_safe_with_marker():
    ran = []
    marker = Recorder()
    rc = sg.main(check=lambda: (False, "indeterminate: stale deco data"),
                 runner=lambda: ran.append(1) or 0,
                 sleep=lambda s: None, clock=make_clock([0, 0]), marker=marker)
    assert ran == [1]
    assert marker.calls[0][0] == "ran_indeterminate"


def test_append_gate_writes_header_once(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sg, "GATE_CSV", tmp_path / "speedtest_gate.csv")
    sg.append_gate("skipped", "call active", 300)
    sg.append_gate("skipped", "call active", 300)
    lines = (tmp_path / "speedtest_gate.csv").read_text().splitlines()
    assert lines[0] == ",".join(sg.GATE_HEADER)
    assert len(lines) == 3
