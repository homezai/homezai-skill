"""Deterministic, cached "is my skill up to date?" check.

Runs on every skill command but only touches the network **at most once per
day** per local checkout. It:

  * reads the local ``VERSION`` file (the version this checkout is on),
  * compares it against the latest published ``VERSION`` in the public repo,
  * caches the result (with a timestamp) in ``.homezai_version_cache.json`` so
    subsequent commands within 24h do zero network calls,
  * **fails open**: if the network or GitHub is unavailable, it returns no
    warning and never blocks the command,
  * returns a short, actionable message telling the agent to run
    ``update.py`` (which handles git clones and plain copies alike) whenever
    the local checkout is behind.

No LLM/text heuristics — pure string/semver comparison so it is fully testable.
Standard library only; no third-party dependency.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

# Public source of truth for the latest released version.
LATEST_VERSION_URL = (
    "https://raw.githubusercontent.com/homezai/homezai-skill/main/VERSION"
)
CACHE_FILENAME = ".homezai_version_cache.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60  # once per day
_NETWORK_TIMEOUT = 5.0

_HERE = os.path.dirname(os.path.abspath(__file__))


def _read_local_version(base_dir: Optional[str] = None) -> Optional[str]:
    path = os.path.join(base_dir or _HERE, "VERSION")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
            return value or None
    except OSError:
        return None


def _parse_semver(value: str) -> Tuple[int, ...]:
    """Parse ``"1.2.3"`` -> ``(1, 2, 3)``. Non-numeric parts become 0.

    Tolerates a leading ``v`` and trailing pre-release/build metadata so the
    comparison never raises on unexpected input.
    """
    core = value.strip().lstrip("vV").split("+", 1)[0].split("-", 1)[0]
    parts = []
    for chunk in core.split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_outdated(local: str, latest: str) -> bool:
    """True iff ``latest`` is strictly newer than ``local``."""
    return _parse_semver(latest) > _parse_semver(local)


def _default_fetch_latest() -> Optional[str]:
    """Fetch the latest published VERSION over HTTPS. Returns None on failure."""
    req = urllib.request.Request(LATEST_VERSION_URL, method="GET")
    req.add_header("Accept", "text/plain")
    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT) as resp:
            return resp.read().decode("utf-8").strip() or None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _load_cache(cache_path: str) -> Optional[dict]:
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return None


def _write_cache(cache_path: str, checked_at: float, latest: Optional[str]) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"checked_at": checked_at, "latest_version": latest}, handle)
    except OSError:
        # Cache is an optimization; never fail the command because we could
        # not write it (e.g. read-only checkout).
        pass


def check_for_update(
    base_dir: Optional[str] = None,
    *,
    now: Optional[Callable[[], float]] = None,
    fetch_latest: Optional[Callable[[], Optional[str]]] = None,
) -> Optional[str]:
    """Return an update-warning string if the checkout is behind, else None.

    Network is contacted at most once per ``CHECK_INTERVAL_SECONDS``. All the
    time/network dependencies are injectable so the behavior is deterministic
    under test.
    """
    base_dir = base_dir or _HERE
    now_fn = now or time.time
    fetch_fn = fetch_latest or _default_fetch_latest

    local = _read_local_version(base_dir)
    if not local:
        # We cannot reason about freshness without a local version. Fail open.
        return None

    cache_path = os.path.join(base_dir, CACHE_FILENAME)
    cache = _load_cache(cache_path)
    current_time = now_fn()

    latest: Optional[str] = None
    cache_is_fresh = (
        cache is not None
        and isinstance(cache.get("checked_at"), (int, float))
        and (current_time - float(cache["checked_at"])) < CHECK_INTERVAL_SECONDS
    )

    if cache_is_fresh:
        latest = cache.get("latest_version")  # may be None if last check failed
    else:
        latest = fetch_fn()
        # Record the attempt time regardless of success so a failed network
        # call doesn't hammer GitHub on every command for the next 24h.
        _write_cache(cache_path, current_time, latest)

    if not latest:
        return None  # offline / unknown -> fail open, no warning

    if is_outdated(local, latest):
        updater = os.path.join(base_dir, "update.py")
        return (
            f"A newer Homezai agent skill is available (you have {local}, "
            f"latest is {latest}). Agents: update before continuing by running "
            f"`python3 {updater}`, then re-read SKILL.md. Your .env and "
            f"LOCAL.md are kept."
        )
    return None


def maybe_warn(base_dir: Optional[str] = None, stream=None) -> Optional[str]:
    """Convenience wrapper: print the warning (if any) to ``stream`` (stderr).

    Never raises; safe to call at the top of every command. Returns the warning
    text (or None) so callers/tests can assert on it.
    """
    import sys

    stream = stream if stream is not None else sys.stderr
    try:
        message = check_for_update(base_dir)
    except Exception:
        # Absolute belt-and-suspenders: a version check must never break a
        # real Homezai command.
        return None
    if message:
        print(f"[homezai-skill] {message}", file=stream)
    return message


if __name__ == "__main__":
    warning = maybe_warn()
    if warning:
        raise SystemExit(0)
    print("[homezai-skill] up to date.")
