"""Tests for deco_poll: the pure transform, CSV append behavior, and the
self-healing poll iteration. Run with the venv pytest from internet-speed-monitor/.
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import deco_poll  # noqa: E402


# --- fakes -------------------------------------------------------------------

class FakeConn:
    def __init__(self, value):
        self.value = value


class FakeDevice:
    def __init__(self, hostname, mac, ip, conn, down, up):
        self.hostname = hostname
        self._mac = mac
        self._ip = ip
        self.type = FakeConn(conn)
        self.down_speed = down
        self.up_speed = up

    @property
    def macaddress(self):
        return self._mac

    @property
    def ipaddress(self):
        return self._ip


class FakeStatus:
    def __init__(self, devices, cpu=0.1, mem=0.5, clients_total=None):
        self.devices = devices
        self.cpu_usage = cpu
        self.mem_usage = mem
        self.clients_total = clients_total if clients_total is not None else len(devices)


# --- extract_rows: happy path, idle, zero-speed exclusion --------------------

def test_extract_rows_keeps_only_active_clients():
    status = FakeStatus([
        FakeDevice("pop-os", "AA", "192.168.68.63", "iot_2g", 44, 153),
        FakeDevice("iPad", "BB", "192.168.68.58", "host_5g", 0, 0),   # idle
        FakeDevice("iPhone", "CC", "192.168.68.56", "host_5g", 3, 25),
    ], clients_total=3)
    status_row, client_rows = deco_poll.extract_rows(status, "2026-06-24T20:00:00")

    assert status_row["poll_ok"] is True
    assert status_row["active_clients"] == 2
    assert status_row["clients_total"] == 3
    hostnames = {r["hostname"] for r in client_rows}
    assert hostnames == {"pop-os", "iPhone"}
    pop = next(r for r in client_rows if r["hostname"] == "pop-os")
    assert pop["conn_type"] == "iot_2g"
    assert pop["down_speed"] == 44 and pop["up_speed"] == 153
    assert pop["ip"] == "192.168.68.63"


def test_extract_rows_idle_network_records_status_but_no_clients():
    status = FakeStatus([
        FakeDevice("iPad", "BB", "192.168.68.58", "host_5g", 0, 0),
        FakeDevice("RoboVac", "DD", "192.168.68.53", "iot_2g", 0, 0),
    ])
    status_row, client_rows = deco_poll.extract_rows(status, "2026-06-24T20:00:30")
    assert client_rows == []
    assert status_row["poll_ok"] is True
    assert status_row["active_clients"] == 0  # idle != failed


def test_extract_rows_excludes_zero_zero_but_keeps_one_directional():
    status = FakeStatus([
        FakeDevice("up-only", "EE", "10.0.0.1", "wired", 0, 7),   # kept
        FakeDevice("idle", "FF", "10.0.0.2", "wired", 0, 0),      # dropped
    ])
    _, client_rows = deco_poll.extract_rows(status, "2026-06-24T20:01:00")
    assert len(client_rows) == 1
    assert client_rows[0]["hostname"] == "up-only"


# --- append_rows: header-once, no duplication --------------------------------

def test_append_rows_writes_header_once(tmp_path):
    path = tmp_path / "status.csv"
    row = deco_poll.failure_row("2026-06-24T20:00:00", "boom")
    deco_poll.append_rows(path, deco_poll.STATUS_HEADER, [row])
    deco_poll.append_rows(path, deco_poll.STATUS_HEADER, [row])
    lines = path.read_text().splitlines()
    assert lines[0] == ",".join(deco_poll.STATUS_HEADER)
    assert sum(1 for ln in lines if ln.startswith("timestamp,")) == 1
    assert len(lines) == 3  # 1 header + 2 data rows


def test_append_rows_noop_on_empty(tmp_path):
    path = tmp_path / "clients.csv"
    deco_poll.append_rows(path, deco_poll.CLIENTS_HEADER, [])
    assert not path.exists()


# --- do_iteration: success keeps client, failure reauths + logs failure ------

def test_do_iteration_success_writes_rows_and_keeps_client(tmp_path, monkeypatch):
    monkeypatch.setattr(deco_poll, "STATUS_CSV", tmp_path / "deco_status.csv")
    monkeypatch.setattr(deco_poll, "CLIENTS_CSV", tmp_path / "deco_clients.csv")

    class OkClient:
        def get_status(self):
            return FakeStatus([FakeDevice("pop-os", "AA", "1.1.1.1", "wired", 5, 5)])

    client = OkClient()
    reauth_called = []
    result = deco_poll.do_iteration(client, "2026-06-24T20:00:00",
                                    lambda: reauth_called.append(True))
    assert result is client            # same client kept on success
    assert reauth_called == []          # no reauth on success
    rows = list(csv.DictReader(open(tmp_path / "deco_status.csv")))
    assert rows[0]["poll_ok"] == "True"
    assert rows[0]["active_clients"] == "1"


def test_do_iteration_failure_logs_and_reauthorizes(tmp_path, monkeypatch):
    monkeypatch.setattr(deco_poll, "STATUS_CSV", tmp_path / "deco_status.csv")
    monkeypatch.setattr(deco_poll, "CLIENTS_CSV", tmp_path / "deco_clients.csv")
    monkeypatch.setattr(deco_poll, "ERROR_BACKOFF", 0)

    class BoomClient:
        def get_status(self):
            raise RuntimeError("session expired")

    new_client = object()
    result = deco_poll.do_iteration(BoomClient(), "2026-06-24T20:00:00",
                                    lambda: new_client)
    assert result is new_client        # swapped to reauthorized client
    rows = list(csv.DictReader(open(tmp_path / "deco_status.csv")))
    assert rows[0]["poll_ok"] == "False"
    assert "session expired" in rows[0]["error"]
    assert not (tmp_path / "deco_clients.csv").exists()  # no client rows on failure


def test_do_iteration_survives_reauth_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(deco_poll, "STATUS_CSV", tmp_path / "deco_status.csv")
    monkeypatch.setattr(deco_poll, "CLIENTS_CSV", tmp_path / "deco_clients.csv")
    monkeypatch.setattr(deco_poll, "ERROR_BACKOFF", 0)

    class BoomClient:
        def get_status(self):
            raise RuntimeError("down")

    def bad_reauth():
        raise RuntimeError("still down")

    client = BoomClient()
    # Must not raise; returns the original client so the loop continues.
    result = deco_poll.do_iteration(client, "2026-06-24T20:00:00", bad_reauth)
    assert result is client


# --- main: missing credential guard ------------------------------------------

def test_main_missing_password_exits_2(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("DECO_USERNAME=someone@example.com\n")  # no DECO_PW
    monkeypatch.setattr(deco_poll, "ENV_PATH", env_file)
    rc = deco_poll.main(["--once"])
    assert rc == 2
    assert "DECO_PW" in capsys.readouterr().err


def test_main_missing_env_file_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deco_poll, "ENV_PATH", tmp_path / "nope.env")
    rc = deco_poll.main([])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
