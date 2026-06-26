"""Tests for hitron_client: pure parsers against captured fixtures + session
re-login logic with a fake requests session."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import hitron_client as hc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


# --- pure parsers against real captured JSON ---------------------------------

def test_parse_downstream_matches_fixture():
    # Asserts parsing/casting, not specific signal values (power/SNR drift between captures).
    data = json.load(open(FIX / "dsinfo.json"))
    ds = hc.parse_downstream(data)
    assert len(ds) == 28
    ch1 = next(c for c in ds if c["channel_id"] == 1)
    assert isinstance(ch1["channel_id"], int)
    assert isinstance(ch1["power_dbmv"], float)
    assert isinstance(ch1["snr_db"], float) and 20 < ch1["snr_db"] < 50  # sane QAM256 range
    assert isinstance(ch1["uncorrect"], int)
    assert ch1["modulation"] == "QAM256"
    assert all(isinstance(c["snr_db"], float) for c in ds)


def test_parse_upstream_matches_fixture():
    data = json.load(open(FIX / "usinfo.json"))
    us = hc.parse_upstream(data)
    assert len(us) >= 1
    assert all(isinstance(c["power_dbmv"], float) for c in us)
    assert all(c["channel_id"] is not None for c in us)


def test_parse_downstream_empty_and_malformed():
    assert hc.parse_downstream({}) == []
    assert hc.parse_downstream({"Freq_List": None}) == []
    assert hc.parse_downstream(None) == []


def test_parse_downstream_missing_fields_default_safely():
    ds = hc.parse_downstream({"Freq_List": [{"channelId": "5"}]})
    assert len(ds) == 1
    assert ds[0]["channel_id"] == 5
    assert ds[0]["snr_db"] is None          # missing -> None, no crash
    assert ds[0]["uncorrect"] == 0          # missing counter -> 0


# --- session / re-login logic ------------------------------------------------

class FakeResp:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data
        if text is not None:
            self.text = text
        elif json_data is not None:
            self.text = json.dumps(json_data)
        else:
            self.text = ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    def __init__(self, post_resp, get_resps):
        self.post_resp = post_resp
        self.get_resps = list(get_resps)
        self.posts = 0
        self.gets = 0

    def post(self, *a, **k):
        self.posts += 1
        return self.post_resp

    def get(self, *a, **k):
        self.gets += 1
        return self.get_resps.pop(0)


def test_get_downstream_happy_path():
    sess = FakeSession(
        post_resp=FakeResp(json_data={"result": "success"}),
        get_resps=[FakeResp(json_data={"errCode": "000", "Freq_List": [{"channelId": "1", "snr": "40"}]})],
    )
    c = hc.HitronClient("x", "u", "p", session=sess)
    ds = c.get_downstream()
    assert sess.posts == 1 and sess.gets == 1
    assert ds[0]["snr_db"] == 40.0


def test_get_downstream_reauthorizes_on_expired_session():
    sess = FakeSession(
        post_resp=FakeResp(json_data={"result": "success"}),
        get_resps=[
            FakeResp(status_code=302, text=""),                       # expired -> redirect
            FakeResp(json_data={"errCode": "000", "Freq_List": []}),  # after re-login
        ],
    )
    c = hc.HitronClient("x", "u", "p", session=sess)
    ds = c.get_downstream()
    assert sess.posts == 2          # initial login + one re-login
    assert sess.gets == 2
    assert ds == []


def test_login_failure_raises():
    sess = FakeSession(post_resp=FakeResp(json_data={"result": "failed"}), get_resps=[])
    c = hc.HitronClient("x", "u", "p", session=sess)
    with pytest.raises(hc.HitronError):
        c.login()


def test_errcode_failure_raises():
    sess = FakeSession(
        post_resp=FakeResp(json_data={"result": "success"}),
        get_resps=[FakeResp(json_data={"errCode": "401", "errMsg": "denied"})],
    )
    c = hc.HitronClient("x", "u", "p", session=sess)
    with pytest.raises(hc.HitronError):
        c.get_downstream()
