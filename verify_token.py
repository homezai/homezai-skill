#!/usr/bin/env python3
"""Safe, read-only smoke check that a Homezai API token works.

Usage:
    cp .env.example .env    # then edit .env with your token
    python verify_token.py

Performs only GET requests (no data is created or modified):
  1. token_status()   — proves the token authenticates
  2. whoami()         — shows the resolved user + capabilities
  3. list_listings()  — a user-scoped read (same data as /agent/listings)

Exits non-zero on any auth or API error.
"""

import sys

from homezai_client import HomezaiApiError, HomezaiAuthError, HomezaiClient, load_env
from version_check import maybe_warn


def main() -> int:
    # Cheap, once-per-day, fail-open "is this skill up to date?" check. It never
    # blocks the command and never touches the network more than once a day.
    maybe_warn()
    load_env()
    try:
        client = HomezaiClient()
    except HomezaiApiError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        status = client.token_status()
        print(
            f"[1/3] token_status: active={status.get('active')} "
            f"prefix={status.get('token_prefix')} suffix={status.get('token_suffix')}"
        )

        me = client.whoami()
        # Print only non-sensitive identity fields.
        print(
            f"[2/3] whoami: id={me.get('id')} email={me.get('email')} "
            f"role={me.get('role')}"
        )

        listings = client.list_listings()
        count = len(listings) if isinstance(listings, list) else "n/a"
        print(f"[3/3] list_listings: {count} listing(s) visible to this user")
    except HomezaiAuthError as exc:
        print(f"AUTH FAILED: {exc}", file=sys.stderr)
        return 1
    except HomezaiApiError as exc:
        print(f"API ERROR: {exc}", file=sys.stderr)
        return 1

    print("OK — token authenticates and returns user-scoped data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
