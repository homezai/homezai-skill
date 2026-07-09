"""Minimal, dependency-free client for the Homezai agent API.

Authenticates every request with a user-scoped Homezai API token
(``Authorization: Bearer hzai_...``). The token grants exactly the same access
the owning user has in the browser — no more, no less. Store the token in a
``.env`` file (see ``.env.example``); never hard-code or commit it.

Uses only the Python standard library so the skill runs anywhere without a
``pip install`` step.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional


class HomezaiApiError(Exception):
    """Base error for any non-2xx Homezai API response."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class HomezaiAuthError(HomezaiApiError):
    """Raised on 401/403 — token missing, invalid, revoked, or lacking access."""


def load_env(path: str = ".env") -> None:
    """Load ``KEY=VALUE`` lines from a local .env into ``os.environ``.

    Existing environment variables take precedence. Lines starting with ``#``
    and blank lines are ignored. This is a tiny loader so the skill has no
    third-party dependency; swap in python-dotenv if preferred.
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


class HomezaiClient:
    """Thin, deterministic wrapper over the user-scoped Homezai agent API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        base_url = base_url or os.environ.get("HOMEZAI_API_BASE_URL")
        # HOMEZAI_API_TOKEN is the public/canonical variable name. Accept the
        # legacy HOMEZAI_AGENT_API_TOKEN as a fallback so existing setups keep
        # working; the public docs and .env.example still use HOMEZAI_API_TOKEN.
        token = (
            token
            or os.environ.get("HOMEZAI_API_TOKEN")
            or os.environ.get("HOMEZAI_AGENT_API_TOKEN")
        )
        if not base_url:
            raise HomezaiApiError("HOMEZAI_API_BASE_URL is not set")
        if not token:
            raise HomezaiApiError("HOMEZAI_API_TOKEN is not set")
        if not token.startswith("hzai_"):
            raise HomezaiApiError(
                "HOMEZAI_API_TOKEN does not look like a Homezai API token "
                "(expected an 'hzai_' prefix)"
            )
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout

    # ------------------------------------------------------------------ #
    # Low-level request
    # ------------------------------------------------------------------ #
    def _request(self, method: str, path: str) -> Any:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = _safe_error_detail(exc)
            if status in (401, 403):
                raise HomezaiAuthError(
                    f"Authentication failed ({status}): {detail}. "
                    "Check HOMEZAI_API_TOKEN, or rotate it in Homezai "
                    "Profile settings and update your .env.",
                    status=status,
                ) from None
            raise HomezaiApiError(
                f"Homezai API error ({status}): {detail}", status=status
            ) from None
        except urllib.error.URLError as exc:
            raise HomezaiApiError(
                f"Could not reach Homezai API at {self.base_url}: {exc.reason}"
            ) from None

    # ------------------------------------------------------------------ #
    # User-scoped reads (same data the logged-in UI sees)
    # ------------------------------------------------------------------ #
    def token_status(self) -> Any:
        """Safe read-only call to verify the token works. GET agent-token."""
        return self._request("GET", "/api/v1/user/agent-token")

    def whoami(self) -> Any:
        """Current user profile + capabilities. GET /api/v1/user/profile."""
        return self._request("GET", "/api/v1/user/profile")

    def list_listings(self) -> Any:
        """User-scoped listings — the same set shown at /agent/listings."""
        return self._request("GET", "/api/v1/agent/listings")

    def brokerage_context(self) -> Any:
        """The user's active brokerage context. GET brokerages/context."""
        return self._request("GET", "/api/v1/agent/brokerages/context")


def _safe_error_detail(exc: "urllib.error.HTTPError") -> str:
    try:
        body = exc.read().decode("utf-8")
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            return str(parsed.get("message") or parsed.get("error") or body)[:200]
        return body[:200]
    except Exception:
        return exc.reason if getattr(exc, "reason", None) else "request failed"
