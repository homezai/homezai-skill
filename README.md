# Homezai Agent Skill

Let an AI agent (or any script) call the [Homezai](https://app.homezai.com) API
**as you** — with exactly the same access you have when you are logged into the
Homezai web app. Same role, same brokerage memberships, same listings, same
admin status, same feature flags. Nothing more, nothing less.

You generate a personal **Agent API token** in Homezai, hand that token plus the
link to this repository to your AI agent, and the agent can set itself up and
start working through your own Homezai account.

- Dependency-free: Python standard library only, no `pip install` step.
- User-scoped: a token authenticates as one user, with that user's permissions.
- Safe by default: the shipped commands are read-only.
- Self-updating awareness: warns you (at most once a day) when a newer version
  of this skill is published.

---

## What an Agent API token can do

The token is a **bearer credential that acts as you**. Any agent or person who
holds it can do anything the Homezai API lets your account do, subject to your
role and brokerage permissions. Depending on your account that can include:

- viewing your profile and account information;
- viewing your brokerage memberships and active brokerage context;
- viewing listings, contacts, clients, showings, messages, and analytics your
  account can access;
- creating or editing Homezai records you are allowed to manage;
- scheduling, editing, sending, or cancelling communications the API exposes;
- changing branding or brokerage settings if your role allows it;
- admin-level actions if your account is a Homezai or brokerage admin.

**Treat the token like a password.** Only give it to an agent you trust. If it
is ever exposed, rotate or revoke it immediately in Homezai (rotation
invalidates the old token instantly). Homezai cannot tell you apart from an
agent using your token, except through token audit metadata.

---

## 1. Generate your token

1. Log in to the Homezai agent portal: <https://app.homezai.com>
2. Open **Profile** (`/agent/settings`) → **Agent API Token**.
3. Click **Generate token** (or **Rotate token** if you already have one).
4. The raw token (`hzai_...`) is shown **once**. Copy it immediately — it
   cannot be retrieved later.

## 2. Give the token and this repo to your agent

Point your AI agent at this repository and give it the token. For example:

> "Clone `https://github.com/homezai/homezai-skill`, put my Homezai token in
> `.env`, and use `verify_token.py` / `whoami.py` to confirm it works before
> doing anything else."

Or set it up yourself:

```bash
git clone https://github.com/homezai/homezai-skill
cd homezai-skill
cp .env.example .env
# edit .env and paste your token
```

## 3. Configure `.env`

```
HOMEZAI_API_BASE_URL=https://api.dev.homezyai.com
HOMEZAI_API_TOKEN=hzai_your_token_here
```

`HOMEZAI_API_BASE_URL` is the Homezai production API. `HOMEZAI_API_TOKEN` is the
token you just generated. **Never commit `.env`** — it is gitignored; only
`.env.example` is tracked.

> If you have an older setup that used `HOMEZAI_AGENT_API_TOKEN`, the client
> still reads it as a fallback, but `HOMEZAI_API_TOKEN` is the canonical name
> and takes precedence.

## 4. Confirm the token works (read-only)

```bash
python whoami.py        # which account does this token belong to?
python verify_token.py  # token status + profile + a user-scoped read
```

Expected `verify_token.py` output:

```
[1/3] token_status: active=True prefix=hzai_ suffix=abcd
[2/3] whoami: id=123 email=you@example.com role=SELLER_AGENT
[3/3] list_listings: 4 listing(s) visible to this user
OK — token authenticates and returns user-scoped data.
```

If either command prints a line beginning with `[homezai-skill]`, a newer
version of this skill is available. Run `python3 update.py` to update (see
"Staying up to date").

## 4a. Search the MLS (read-only)

```bash
python mls_search.py --coverage                     # which MLS feeds this token reaches
python mls_search.py --city Riverton --state AL --beds 3 --max-price 450000
python mls_search.py --mls-id 123456 --json
```

Search is scoped to **your** MLS access. Homezai picks the feeds from your
brokerage and MLS memberships; brokerage and association admins may be
narrowed to their offices; Homezai Admins reach every enabled feed. A market
outside your feeds returns zero results because you lack access to it, not
because it is empty. Run `--coverage` to see your feeds. `SKILL.md` lists
every filter.

## 5. Use it in code

```python
from homezai_client import HomezaiClient, load_env, HomezaiAuthError

load_env()                 # reads .env
client = HomezaiClient()   # or HomezaiClient(base_url=..., token=...)

me = client.whoami()                  # GET /api/v1/user/profile
listings = client.list_listings()     # GET /api/v1/agent/listings
context = client.brokerage_context()  # GET /api/v1/agent/brokerages/context

try:
    client.whoami()
except HomezaiAuthError as exc:
    # 401/403 — token missing, invalid, revoked, or lacking access.
    print(exc)
```

### Supported operations

Read-only, user-scoped calls that prove the contract:

| Method | Endpoint | Purpose |
|---|---|---|
| `token_status()` | `GET /api/v1/user/agent-token` | verify the token (safe) |
| `whoami()` | `GET /api/v1/user/profile` | current user + capabilities |
| `list_listings()` | `GET /api/v1/agent/listings` | listings visible to you |
| `brokerage_context()` | `GET /api/v1/agent/brokerages/context` | your active brokerage |
| `search_mls(params)` | `GET /api/v1/agent/mls/search` | live MLS search, scoped to your MLS access |

Mutations are intentionally out of scope for v1. When you add them, use safe
test data and clean up after yourself — a mutation runs with your real account
permissions.

---

## How authority maps to your account

There is **no separate permission model** for tokens. Server-side, a valid
`hzai_` bearer is resolved to your user and exchanged for the same identity a
browser login produces. Every role, brokerage, admin, and feature-flag check
then behaves exactly as it would for you in the app. Invalid, revoked, rotated,
or malformed tokens fail closed (HTTP 401/403).

## Security notes

- Auth header: `Authorization: Bearer hzai_...`.
- The token is stored server-side only as a SHA-256 hash; the plaintext is
  never persisted or logged.
- Tokens do not expire in v1. If exposed, **rotate or revoke** in Profile
  settings — rotation invalidates the old one immediately.
- Keep the token in `.env` only. Do not hard-code it, print it, or send it to
  logs or analytics.

## Staying up to date

`version_check.py` compares your local `VERSION` against the latest published
`VERSION` in this repository. It runs on every command but contacts the network
**at most once per day** (cached in `.homezai_version_cache.json`) and **fails
open** — if GitHub is unreachable it stays silent and never blocks your command.
When you are behind, every command prints a one-line notice telling you (or
your agent) to run `python3 update.py`.

`update.py` works for both kinds of install. In a `git clone` it runs
`git pull --ff-only`. In a plain copy of the files it downloads the latest
`main` from GitHub and replaces the skill's own files. Either way it keeps your
`.env` and `LOCAL.md`, and it fails loudly if it cannot finish.
`python3 update.py --check` re-checks GitHub immediately.

Keep notes that belong to one install (where its token lives, which account it
is) in `LOCAL.md` next to `SKILL.md`. Agents read it first, and updates never
overwrite it.

## Run the tests

```bash
python -m pytest -q            # or: python -m unittest discover -p 'test_*.py'
```

## License

[MIT](./LICENSE)
