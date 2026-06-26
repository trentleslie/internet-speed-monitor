#!/usr/bin/env python3
"""Client for the Hitron (Astound) cable modem local API at 192.168.100.1.

Authenticates with the cusadmin credentials and returns parsed DOCSIS
downstream/upstream channel stats. The PHPSESSID session is reused across calls
and re-established automatically on expiry.

Spike-verified (2026-06-24):
  POST /1/Device/Users/Login   body: model={"username":..,"password":..} -> {"result":"success"}
  GET  /1/Device/CM/DsInfo     -> {"errCode":"000","Freq_List":[{...downstream...}]}
  GET  /1/Device/CM/UsInfo     -> {"errCode":"000","Freq_List":[{...upstream...}]}
Gated endpoints 302-redirect to /webpages/login.html without a valid session.
"""
import json

import requests

DEFAULT_HOST = "192.168.100.1"
LOGIN_PATH = "/1/Device/Users/Login"
DS_PATH = "/1/Device/CM/DsInfo"
US_PATH = "/1/Device/CM/UsInfo"


class HitronError(Exception):
    pass


def _num(value, cast=float, default=None):
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def parse_downstream(data):
    """Pure: DsInfo JSON dict -> list of normalized downstream channel dicts."""
    out = []
    for c in (data or {}).get("Freq_List") or []:
        out.append({
            "channel_id": _num(c.get("channelId"), int),
            "freq_hz": _num(c.get("frequency"), int),
            "modulation": c.get("modulation", ""),
            "power_dbmv": _num(c.get("signalStrength")),
            "snr_db": _num(c.get("snr")),
            "correcteds": _num(c.get("correcteds"), int, 0),
            "uncorrect": _num(c.get("uncorrect"), int, 0),
        })
    return out


def parse_upstream(data):
    """Pure: UsInfo JSON dict -> list of normalized upstream channel dicts."""
    out = []
    for c in (data or {}).get("Freq_List") or []:
        out.append({
            "channel_id": _num(c.get("channelId"), int),
            "freq_hz": _num(c.get("frequency"), int),
            "modulation": c.get("modulationType", ""),
            "power_dbmv": _num(c.get("signalStrength")),
            "symbolrate": _num(c.get("symbolrate"), int),
        })
    return out


class HitronClient:
    def __init__(self, host, username, password, timeout=15, session=None):
        self.base = f"http://{host}"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = session or requests.Session()
        self._logged_in = False

    def login(self):
        model = json.dumps({"username": self.username, "password": self.password})
        r = self.session.post(self.base + LOGIN_PATH, data={"model": model},
                              timeout=self.timeout, allow_redirects=False)
        try:
            res = r.json()
        except ValueError:
            raise HitronError(f"login: non-JSON response (HTTP {r.status_code})")
        if res.get("result") != "success":
            raise HitronError(f"login failed: {res.get('result') or res.get('errMsg')}")
        self._logged_in = True

    def _get_json(self, path):
        """GET a data endpoint, transparently re-logging in once if the session expired."""
        if not self._logged_in:
            self.login()
        r = self.session.get(self.base + path, timeout=self.timeout, allow_redirects=False)
        if r.status_code in (301, 302) or not (r.text or "").strip():
            # Session expired (redirect to login) -> re-login once and retry.
            self._logged_in = False
            self.login()
            r = self.session.get(self.base + path, timeout=self.timeout, allow_redirects=False)
        if r.status_code in (301, 302):
            raise HitronError(f"{path}: still redirecting after re-login")
        try:
            data = r.json()
        except ValueError:
            raise HitronError(f"{path}: non-JSON response (HTTP {r.status_code})")
        if data.get("errCode") not in (None, "000", "0"):
            raise HitronError(f"{path}: errCode={data.get('errCode')} {data.get('errMsg')}")
        return data

    def get_downstream(self):
        return parse_downstream(self._get_json(DS_PATH))

    def get_upstream(self):
        return parse_upstream(self._get_json(US_PATH))
