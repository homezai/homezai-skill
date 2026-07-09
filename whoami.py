#!/usr/bin/env python3
"""Print which Homezai account a token belongs to (safe, read-only).

Use this before doing anything sensitive to confirm the token resolves to the
account you expect. Performs a single GET; creates/modifies nothing.

    cp .env.example .env    # then edit .env with your token
    python whoami.py
"""

import sys

from homezai_client import HomezaiApiError, HomezaiAuthError, HomezaiClient, load_env
from version_check import maybe_warn


def main() -> int:
    maybe_warn()  # once-per-day, fail-open update check
    load_env()
    try:
        client = HomezaiClient()
        me = client.whoami()
    except HomezaiAuthError as exc:
        print(f"AUTH FAILED: {exc}", file=sys.stderr)
        return 1
    except HomezaiApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("This token belongs to:")
    print(f"  id:    {me.get('id')}")
    print(f"  email: {me.get('email')}")
    print(f"  role:  {me.get('role')}")
    print(
        "\nAny agent or person holding this token can act as this account, "
        "within its permissions. Treat it like a password."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
