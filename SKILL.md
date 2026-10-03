---
name: homezai-agent-api
description: Act in Homezai as a specific user through their hzai_ Agent API token. Use for live MLS listing searches (city, state, zip, address, MLS number, price, beds, baths, square feet, year built, lot size, days on market) scoped to that user's MLS access, checking which MLS feeds a token reaches, confirming which account a token belongs to, and reading the user's own listings and brokerage context.
---

# Homezai agent skill

Everything here runs as the token's Homezai user, with exactly that user's
role, brokerage memberships, admin status and MLS access. There is no separate
permission model and no admin bypass.

## Before anything else

1. If a `LOCAL.md` file sits next to this one, read it first. It holds notes
   for this install only, such as where the token is kept and which account it
   belongs to. Updates never overwrite it.
2. Every command checks GitHub for a newer version of this skill, at most once
   a day. If a command prints a line starting with `[homezai-skill]` that says
   a newer version is available, run the update it names
   (`python3 update.py` in this folder), then re-read this file and
   `LOCAL.md` before continuing. Your `.env` and `LOCAL.md` are kept.
3. To force a fresh check at any time: `python3 update.py --check`.

## Token

Set `HOMEZAI_API_BASE_URL` and `HOMEZAI_API_TOKEN`, either in a `.env` file in
this folder or in the environment. Never print the token, never write it into
a tracked file, and never paste it into a chat or an email. A Homezai account
has one active token at a time: generating or rotating a token in Profile
settings instantly revokes the previous one, so reuse the token you were given.

Confirm which account the token belongs to before doing anything sensitive:

    python3 whoami.py
    python3 verify_token.py

## Live MLS search (read-only)

`mls_search.py` runs the same MLS search as the Homezai agent portal. Homezai
picks the MLS feeds from the token user's access: an agent reaches the feeds
their brokerage and MLS memberships hold, a brokerage or association admin may
be narrowed to their offices, and a Homezai Admin reaches every enabled feed.
So the same search can return different results for different tokens.

    python3 mls_search.py --coverage
    python3 mls_search.py --city Riverton --state AL --beds 3 --max-price 450000
    python3 mls_search.py --zip 36500 --top 50 --skip 50
    python3 mls_search.py --mls-id 123456 --json

Run `--coverage` once for a new token: it lists the feeds the token reaches. A
market outside those feeds returns zero results, which means this account has
no access to that feed, not that the market is empty. Say so plainly instead
of reporting an empty market.

Filters: `--city` (partial match), `--state` (two letters), `--zip`,
`--address`, `--q` (street name text), `--mls-id`, `--min-price`,
`--max-price`, `--beds` and `--baths` (minimums), `--property-type`,
`--status` (default Active), `--min-sqft`, `--max-sqft`, `--min-year-built`,
`--max-year-built`, `--min-lot-size`, `--max-lot-size` (acres),
`--max-days-on-market`. Paging: `--top` (max 100, default 25) and `--skip`.
`--json` prints the raw response, which also carries remarks, photo URL,
county, listing agent contact, showing instructions and dates. There is no
radius or map search and no way to choose a feed.

MLS data is licensed to the brokerages and MLSs that supply it. Use results as
research for the token's user, and do not republish raw listing data publicly.

## In code

    from homezai_client import HomezaiClient, load_env
    load_env()
    client = HomezaiClient()
    client.whoami()
    client.search_mls({"city": "Riverton", "state": "AL", "beds": 3})

## Files

- `homezai_client.py`: standard-library client with typed errors.
- `mls_search.py`, `whoami.py`, `verify_token.py`: read-only commands.
- `version_check.py`: cached daily check against GitHub.
- `update.py`: updates a git clone or a plain copy to the latest version.
- `test_*.py`: offline tests (`python3 -m pytest -q`).
