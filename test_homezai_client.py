"""Deterministic tests for the Homezai agent API skill client.

Runs with no network and no third-party deps:
    python -m pytest skills/homezai-agent-api/test_homezai_client.py -q
"""

import io
import json
import urllib.error
from unittest.mock import patch

import pytest
from homezai_client import (
    HomezaiApiError,
    HomezaiAuthError,
    HomezaiClient,
    load_env,
)

BASE = "https://api.example.com"
TOKEN = "hzai_testtoken"


def _client():
    return HomezaiClient(base_url=BASE, token=TOKEN)


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(status, payload):
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return urllib.error.HTTPError(BASE, status, "err", {}, body)


# --------------------------------------------------------------------------- #
# Construction / config
# --------------------------------------------------------------------------- #
def test_requires_base_url_and_token():
    with pytest.raises(HomezaiApiError):
        HomezaiClient(base_url=None, token=TOKEN)
    with pytest.raises(HomezaiApiError):
        HomezaiClient(base_url=BASE, token=None)


def test_rejects_non_hzai_token():
    with pytest.raises(HomezaiApiError):
        HomezaiClient(base_url=BASE, token="not-a-homezai-token")


def test_sends_bearer_authorization_header():
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.get_header("Authorization")
        captured["url"] = req.full_url
        return _FakeResp({"active": True})

    with patch("urllib.request.urlopen", fake_urlopen):
        _client().token_status()
    assert captured["auth"] == f"Bearer {TOKEN}"
    assert captured["url"] == f"{BASE}/api/v1/user/agent-token"


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def test_whoami_returns_json():
    with patch(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp(
            {"id": 7, "email": "a@example.com", "role": "SELLER_AGENT"}
        ),
    ):
        me = _client().whoami()
    assert me["id"] == 7
    assert me["role"] == "SELLER_AGENT"


def test_list_listings_returns_list():
    with patch(
        "urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp([{"id": 1}, {"id": 2}]),
    ):
        listings = _client().list_listings()
    assert len(listings) == 2


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
def test_401_raises_auth_error():
    def boom(req, timeout=None):
        raise _http_error(401, {"message": "Invalid or revoked Homezai API token"})

    with patch("urllib.request.urlopen", boom):
        with pytest.raises(HomezaiAuthError) as exc:
            _client().whoami()
    assert exc.value.status == 401


def test_403_raises_auth_error():
    def boom(req, timeout=None):
        raise _http_error(403, {"message": "Agent access required"})

    with patch("urllib.request.urlopen", boom):
        with pytest.raises(HomezaiAuthError) as exc:
            _client().list_listings()
    assert exc.value.status == 403


def test_500_raises_generic_api_error():
    def boom(req, timeout=None):
        raise _http_error(500, {"error": "Internal server error"})

    with patch("urllib.request.urlopen", boom):
        with pytest.raises(HomezaiApiError) as exc:
            _client().whoami()
    assert exc.value.status == 500
    assert not isinstance(exc.value, HomezaiAuthError)


def test_network_error_raises_api_error():
    def boom(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    with patch("urllib.request.urlopen", boom):
        with pytest.raises(HomezaiApiError):
            _client().token_status()


# --------------------------------------------------------------------------- #
# .env loader
# --------------------------------------------------------------------------- #
def test_load_env_parses_and_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\nHOMEZAI_API_BASE_URL=http://localhost:7778\n"
        'HOMEZAI_API_TOKEN="hzai_fromfile"\n\n'
    )
    monkeypatch.delenv("HOMEZAI_API_BASE_URL", raising=False)
    monkeypatch.delenv("HOMEZAI_API_TOKEN", raising=False)
    load_env(str(env_file))
    import os

    assert os.environ["HOMEZAI_API_BASE_URL"] == "http://localhost:7778"
    assert os.environ["HOMEZAI_API_TOKEN"] == "hzai_fromfile"
