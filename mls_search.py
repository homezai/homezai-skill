#!/usr/bin/env python3
"""Search live MLS listings as the token's Homezai user (read-only).

Calls ``GET /api/v1/agent/mls/search``, the same search the Homezai agent
portal uses. The token's user decides which MLS feeds are searched: Homezai
resolves them from the user's brokerage and MLS memberships, so two tokens can
see different markets. Run ``--coverage`` to see which feeds this token reaches.

Read-only: it never creates, imports or changes anything.

    python3 mls_search.py --city Riverton --state AL --beds 3 --max-price 450000
    python3 mls_search.py --zip 36500 --top 50 --json
    python3 mls_search.py --mls-id 123456
    python3 mls_search.py --coverage
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from typing import Any, Optional

from homezai_client import HomezaiApiError, HomezaiAuthError, HomezaiClient, load_env
from version_check import maybe_warn

MAX_TOP = 100

# CLI flag -> API query parameter. Order is the order they appear in --help.
PARAM_MAP = [
    ("city", "city"),
    ("state", "state"),
    ("zip", "zipCode"),
    ("address", "address"),
    ("q", "q"),
    ("mls_id", "mlsId"),
    ("min_price", "minPrice"),
    ("max_price", "maxPrice"),
    ("beds", "beds"),
    ("baths", "baths"),
    ("property_type", "propertyType"),
    ("status", "status"),
    ("min_sqft", "minSqft"),
    ("max_sqft", "maxSqft"),
    ("min_year_built", "minYearBuilt"),
    ("max_year_built", "maxYearBuilt"),
    ("min_lot_size", "minLotSize"),
    ("max_lot_size", "maxLotSize"),
    ("max_days_on_market", "maxDaysOnMarket"),
    ("top", "top"),
    ("skip", "skip"),
]


def build_query(args: argparse.Namespace) -> dict:
    """Turn parsed CLI args into API query params, dropping unset ones."""
    query = {}
    for attr, api_name in PARAM_MAP:
        value = getattr(args, attr, None)
        if value is None or value == "":
            continue
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        query[api_name] = value
    return query


def search(client: HomezaiClient, query: dict) -> Any:
    return client.search_mls(query)


def _money(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"${value:,.0f}"


def _num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_listing(listing: dict) -> str:
    mls_number = listing.get("display_mls_id") or listing.get("mls_id")
    source = listing.get("mls_source_display_name") or listing.get("mls_source")
    parts = [
        f"{_money(listing.get('list_price'))}",
        f"{_num(listing.get('bedrooms_total'))} bd / {_num(listing.get('bathrooms_total'))} ba",
        f"{_num(listing.get('living_area'))} sqft",
        listing.get("property_type") or "-",
        listing.get("standard_status") or "-",
    ]
    address = listing.get("address") or ""
    city = listing.get("city")
    # Some feeds already fold city, state and zip into ``address``.
    if not city or city.lower() not in address.lower():
        address = ", ".join(p for p in (address, city, listing.get("state")) if p)
    agent = listing.get("list_agent_name")
    office = listing.get("list_office_name")
    lines = [
        f"- {address or '(no address)'}",
        f"    {' | '.join(parts)}",
        f"    MLS# {mls_number} ({source})",
    ]
    if agent or office:
        lines.append(f"    Listed by {agent or '-'}, {office or '-'}")
    return "\n".join(lines)


def format_result(result: dict) -> str:
    listings = result.get("listings") or []
    total = result.get("total_count")
    skip = result.get("skip") or 0
    lines = [
        f"{total} matching listing(s); showing {len(listings)} starting at {skip}."
    ]
    if result.get("failed_sources"):
        lines.append(
            "WARNING: these MLS feeds failed and are missing from the results: "
            + ", ".join(result["failed_sources"])
        )
    if result.get("restricted_sources"):
        lines.append(
            "Note: these MLS feeds were skipped for this account: "
            + ", ".join(result["restricted_sources"])
        )
    if total and skip + len(listings) < total:
        lines.append(f"More results: rerun with --skip {skip + len(listings)}.")
    lines.append("")
    lines.extend(format_listing(item) for item in listings)
    return "\n".join(lines)


def coverage(client: HomezaiClient) -> str:
    """Report which MLS feeds this token reaches, from one capped sample."""
    result = search(client, {"top": MAX_TOP})
    listings = result.get("listings") or []
    counts = collections.Counter(
        item.get("mls_source_display_name") or item.get("mls_source") for item in listings
    )
    lines = [
        f"This token can search {result.get('total_count')} active listing(s).",
        f"MLS feeds seen in a {len(listings)}-listing sample:",
    ]
    lines.extend(f"  {name}: {count} in sample" for name, count in counts.most_common())
    if not counts:
        lines.append("  none (this account has no MLS feed access)")
    if result.get("failed_sources"):
        lines.append("Failed feeds: " + ", ".join(result["failed_sources"]))
    if result.get("restricted_sources"):
        lines.append("Restricted feeds: " + ", ".join(result["restricted_sources"]))
    lines.append(
        "A feed missing here returns zero results for its markets. That means "
        "this account lacks access, not that the market has no listings."
    )
    return "\n".join(lines)


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search live MLS listings through the Homezai agent API (read-only)."
    )
    loc = p.add_argument_group("location")
    loc.add_argument("--city", help="city name, partial match")
    loc.add_argument("--state", help="two-letter state, exact match (e.g. AL, FL)")
    loc.add_argument("--zip", help="zip code, exact match")
    loc.add_argument("--address", help="street, city or zip text")
    loc.add_argument("--q", help="free text on street name")
    loc.add_argument("--mls-id", dest="mls_id", help="direct MLS number lookup")
    flt = p.add_argument_group("filters")
    flt.add_argument("--min-price", dest="min_price", type=float)
    flt.add_argument("--max-price", dest="max_price", type=float)
    flt.add_argument("--beds", type=int, help="minimum bedrooms")
    flt.add_argument("--baths", type=float, help="minimum bathrooms")
    flt.add_argument("--property-type", dest="property_type",
                     help="e.g. Residential, Condominium, Land")
    flt.add_argument("--status", help="listing status (default Active)")
    flt.add_argument("--min-sqft", dest="min_sqft", type=int)
    flt.add_argument("--max-sqft", dest="max_sqft", type=int)
    flt.add_argument("--min-year-built", dest="min_year_built", type=int)
    flt.add_argument("--max-year-built", dest="max_year_built", type=int)
    flt.add_argument("--min-lot-size", dest="min_lot_size", type=float, help="acres")
    flt.add_argument("--max-lot-size", dest="max_lot_size", type=float, help="acres")
    flt.add_argument("--max-days-on-market", dest="max_days_on_market", type=int)
    pg = p.add_argument_group("paging and output")
    pg.add_argument("--top", type=int, default=25, help=f"results per page (max {MAX_TOP})")
    pg.add_argument("--skip", type=int, default=0, help="offset for the next page")
    pg.add_argument("--json", action="store_true", help="print the raw API response")
    pg.add_argument("--coverage", action="store_true",
                    help="show which MLS feeds this token can search, then exit")
    return p


def main(argv: Optional[list] = None) -> int:
    args = make_parser().parse_args(argv)
    if args.top is not None and not 1 <= args.top <= MAX_TOP:
        print(f"ERROR: --top must be between 1 and {MAX_TOP}", file=sys.stderr)
        return 2
    maybe_warn()
    load_env()
    try:
        client = HomezaiClient(timeout=90.0)
        if args.coverage:
            print(coverage(client))
            return 0
        result = search(client, build_query(args))
    except HomezaiAuthError as exc:
        print(f"AUTH FAILED: {exc}", file=sys.stderr)
        return 1
    except HomezaiApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
