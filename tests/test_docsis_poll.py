"""Tests for docsis_poll: summary/row builders and the self-healing iteration."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import docsis_poll as dp  # noqa: E402

DS = [
    {"channel_id": 1, "freq_hz": 279000000, "modulation": "QAM256",
     "power_dbmv": 11.5, "snr_db": 38.6, "correcteds": 26, "uncorrect": 0},
    {"channel_id": 2, "freq_hz": 285000000, "modulation": "QAM256",
     "power_dbmv": 10.0, "snr_db": 37.1, "correcteds": 4, "uncorrect": 3},
]
US = [
    {"channel_id": 2, "freq_hz": 30400000, "modulation": "64QAM",
     "power_dbmv": 48.3, "symbolrate": 5120},
]


def test_summarize_computes_health_aggregates():
    s = dp.summarize(DS, US, "2026-06-25T10:00:00")
    assert s["poll_ok"] is True
    assert s["min_snr"] == 37.1
    assert s["max_ds_power"] == 11.5
    assert s["total_correcteds"] == 30
    assert s["total_uncorrect"] == 3
    assert s["ds_channels"] == 2 and s["us_channels"] == 1
    assert s["max_us_power"] == 48.3


def test_summarize_healthy_idle_not_failed():
    clean = [dict(c, correcteds=0, uncorrect=0) for c in DS]
    s = dp.summarize(clean, US, "2026-06-25T10:00:00")
    assert s["poll_ok"] is True
    assert s["total_uncorrect"] == 0


def test_summarize_empty_channels_no_crash():
    s = dp.summarize([], [], "2026-06-25T10:00:00")
    assert s["ds_channels"] == 0 and s["min_snr"] == ""


def test_ds_us_rows_shape():
    rows = dp.ds_rows(DS, "T")
    assert rows[0]["channel_id"] == 1 and rows[0]["timestamp"] == "T"
    assert set(rows[0].keys()) == set(dp.DS_HEADER)
    urows = dp.us_rows(US, "T")
    assert set(urows[0].keys()) == set(dp.US_HEADER)


class FakeClient:
    def __init__(self, ds=None, us=None, raise_on_get=False):
        self._ds, self._us, self._raise = ds, us, raise_on_get

    def get_downstream(self):
        if self._raise:
            raise RuntimeError("session expired")
        return self._ds

    def get_upstream(self):
        return self._us


def test_do_iteration_success_writes_all_three(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "STATUS_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(dp, "DS_CSV", tmp_path / "ds.csv")
    monkeypatch.setattr(dp, "US_CSV", tmp_path / "us.csv")
    client = FakeClient(ds=DS, us=US)
    result = dp.do_iteration(client, "2026-06-25T10:00:00", lambda: None)
    assert result is client
    srows = list(csv.DictReader(open(tmp_path / "s.csv")))
    assert srows[0]["poll_ok"] == "True" and srows[0]["total_uncorrect"] == "3"
    assert len(list(csv.DictReader(open(tmp_path / "ds.csv")))) == 2


def test_do_iteration_failure_logs_and_reauthorizes(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "STATUS_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(dp, "DS_CSV", tmp_path / "ds.csv")
    monkeypatch.setattr(dp, "US_CSV", tmp_path / "us.csv")
    monkeypatch.setattr(dp, "ERROR_BACKOFF", 0)
    new_client = FakeClient(ds=DS, us=US)
    result = dp.do_iteration(FakeClient(raise_on_get=True), "2026-06-25T10:00:00",
                             lambda: new_client)
    assert result is new_client
    srows = list(csv.DictReader(open(tmp_path / "s.csv")))
    assert srows[0]["poll_ok"] == "False"
    assert "session expired" in srows[0]["error"]
    assert not (tmp_path / "ds.csv").exists()  # no channel rows on failure


def test_do_iteration_survives_reauth_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "STATUS_CSV", tmp_path / "s.csv")
    monkeypatch.setattr(dp, "DS_CSV", tmp_path / "ds.csv")
    monkeypatch.setattr(dp, "US_CSV", tmp_path / "us.csv")
    monkeypatch.setattr(dp, "ERROR_BACKOFF", 0)
    client = FakeClient(raise_on_get=True)

    def bad_reauth():
        raise RuntimeError("modem down")

    result = dp.do_iteration(client, "2026-06-25T10:00:00", bad_reauth)
    assert result is client  # keeps going with old client; loop must not die


def test_main_missing_credentials_exits_2(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("DECO_PW=x\n")  # env exists but no ASTOUND_* creds
    monkeypatch.setattr(dp, "ENV_PATH", env_file)
    rc = dp.main(["--once"])
    assert rc == 2
    assert "ASTOUND" in capsys.readouterr().err


def test_main_missing_env_file_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dp, "ENV_PATH", tmp_path / "nope.env")
    rc = dp.main([])
    assert rc == 2
    assert "not found" in capsys.readouterr().err
