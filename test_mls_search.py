"""Offline tests for mls_search.py (no network).

    python3 -m pytest skills/homezai-agent-api/test_mls_search.py -q
"""

import json
import urllib.parse
from unittest.mock import patch

import pytest

import mls_search
from homezai_client import HomezaiAuthError, HomezaiClient

BASE = "https://api.example.com"
TOKEN = "hzai_testtoken"

LISTING = {
    "mls_id": "123456",
    "mls_source": "EXAMPLE",
    "mls_source_display_name": "Example MLS",
    "display_mls_id": "123456",
    "address": "12 Example Way",
    "city": "Springfield",
    "state": "AL",
    "list_price": 315000.0,
    "bedrooms_total": 3,
    "bathrooms_total": 2.0,
    "living_area": 1850,
    "property_type": "Residential",
    "standard_status": "Active",
    "list_agent_name": "Pat Example",
    "list_office_name": "Example Realty",
}


def _result(listings, total=None, **extra):
    body = {
        "listings": listings,
        "total_count": len(listings) if total is None else total,
        "returned_count": len(listings),
        "skip": 0,
        "top": 25,
        "failed_sources": [],
        "restricted_sources": [],
    }
    body.update(extra)
    return body


def _args(argv):
    return mls_search.make_parser().parse_args(argv)


def test_build_query_maps_flags_to_api_names_and_drops_unset():
    q = mls_search.build_query(
        _args(["--city", "Riverton", "--state", "AL", "--zip", "36500",
               "--min-price", "200000", "--beds", "3", "--baths", "2.5",
               "--max-days-on-market", "30"])
    )
    assert q == {
        "city": "Riverton", "state": "AL", "zipCode": "36500",
        "minPrice": 200000, "beds": 3, "baths": 2.5,
        "maxDaysOnMarket": 30, "top": 25, "skip": 0,
    }
    assert "mlsId" not in q and "status" not in q


def test_search_sends_encoded_query_to_search_path():
    client = HomezaiClient(base_url=BASE, token=TOKEN)
    with patch.object(client, "_request", return_value=_result([])) as req:
        mls_search.search(client, {"city": "Lakeside", "top": 5, "beds": None})
    method, path = req.call_args.args
    assert method == "GET"
    parsed = urllib.parse.urlparse(path)
    assert parsed.path == "/api/v1/agent/mls/search"
    assert urllib.parse.parse_qs(parsed.query) == {"city": ["Lakeside"], "top": ["5"]}


def test_format_result_shows_listing_and_next_page_hint():
    text = mls_search.format_result(_result([LISTING], total=314))
    assert "314 matching listing(s); showing 1 starting at 0." in text
    assert "12 Example Way, Springfield, AL" in text
    assert "$315,000 | 3 bd / 2 ba | 1850 sqft | Residential | Active" in text
    assert "MLS# 123456 (Example MLS)" in text
    assert "Listed by Pat Example, Example Realty" in text
    assert "rerun with --skip 1" in text


def test_format_listing_does_not_repeat_city_already_in_address():
    folded = dict(LISTING, address="40 Sample Road, Riverton AL 36500", city="Riverton")
    assert "- 40 Sample Road, Riverton AL 36500\n" in mls_search.format_listing(folded)


def test_format_result_surfaces_failed_and_restricted_feeds():
    text = mls_search.format_result(
        _result([], failed_sources=["SDMLS"], restricted_sources=["BSAOR"])
    )
    assert "WARNING" in text and "SDMLS" in text
    assert "skipped for this account: BSAOR" in text


def test_coverage_counts_feeds_and_explains_missing_markets():
    client = HomezaiClient(base_url=BASE, token=TOKEN)
    other = dict(LISTING, mls_source="EXAMPLE2", mls_source_display_name="Second Example MLS")
    with patch.object(client, "_request", return_value=_result([LISTING, LISTING, other], total=5256)) as req:
        text = mls_search.coverage(client)
    assert "top=100" in req.call_args.args[1]
    assert "5256 active listing(s)" in text
    assert "Example MLS: 2 in sample" in text
    assert "Second Example MLS: 1 in sample" in text
    assert "lacks access" in text


def test_coverage_with_no_feeds_says_so():
    client = HomezaiClient(base_url=BASE, token=TOKEN)
    with patch.object(client, "_request", return_value=_result([], total=0)):
        assert "no MLS feed access" in mls_search.coverage(client)


def test_main_rejects_top_out_of_range(capsys):
    assert mls_search.main(["--top", "500"]) == 2
    assert "between 1 and 100" in capsys.readouterr().err


def test_main_json_prints_raw_response(monkeypatch, capsys):
    monkeypatch.setenv("HOMEZAI_API_BASE_URL", BASE)
    monkeypatch.setenv("HOMEZAI_API_TOKEN", TOKEN)
    monkeypatch.setattr(mls_search, "maybe_warn", lambda: None)
    with patch.object(HomezaiClient, "_request", return_value=_result([LISTING])):
        assert mls_search.main(["--city", "Springfield", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["listings"][0]["mls_id"] == "123456"


def test_main_auth_failure_exits_1(monkeypatch, capsys):
    monkeypatch.setenv("HOMEZAI_API_BASE_URL", BASE)
    monkeypatch.setenv("HOMEZAI_API_TOKEN", TOKEN)
    monkeypatch.setattr(mls_search, "maybe_warn", lambda: None)
    with patch.object(HomezaiClient, "_request", side_effect=HomezaiAuthError("bad", status=403)):
        assert mls_search.main(["--city", "Springfield"]) == 1
    assert "AUTH FAILED" in capsys.readouterr().err


@pytest.mark.parametrize("value,expected", [(None, "-"), (3.0, "3"), (2.5, "2.5")])
def test_num_formatting(value, expected):
    assert mls_search._num(value) == expected
