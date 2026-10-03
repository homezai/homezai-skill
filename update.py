#!/usr/bin/env python3
"""Update this skill to the latest published version on GitHub.

Works for both kinds of install:

  * a ``git clone`` of the repository: runs ``git pull --ff-only``;
  * a plain copy of the files (no ``.git``): downloads the latest ``main``
    archive from GitHub and replaces the skill's own files in place.

Your local files are never touched: ``.env`` and any ``*.env``, ``LOCAL.md``
(install-specific notes), and the version-check cache. Unlike the daily
version check, an update you asked for fails loudly: it exits non-zero and
says why, so an agent never mistakes a failed update for a current one.

    python3 update.py           # update now
    python3 update.py --check   # re-check GitHub now (ignores the daily cache)
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from typing import Callable, Optional

import version_check as vc

ARCHIVE_URL = "https://codeload.github.com/homezai/homezai-skill/tar.gz/refs/heads/main"
_NETWORK_TIMEOUT = 30.0
_HERE = os.path.dirname(os.path.abspath(__file__))

# Never overwritten or deleted by an update.
PRESERVED = {".env", "LOCAL.md", vc.CACHE_FILENAME}


class UpdateError(Exception):
    """The update could not be completed. The install is left as it was."""


def _is_preserved(name: str) -> bool:
    return name in PRESERVED or (name.endswith(".env") and name != ".env.example")


def _fetch_archive() -> bytes:
    req = urllib.request.Request(ARCHIVE_URL, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"could not download {ARCHIVE_URL}: {exc}") from None


def _skill_files_from_archive(data: bytes) -> dict:
    """Return {filename: bytes} for the skill's top-level files in the archive.

    Only regular files directly under the archive's single top directory are
    taken. Anything with a path separator, a parent reference or an absolute
    path is rejected, so a malformed archive cannot write outside the skill.
    """
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                parts = member.name.split("/")
                if member.name.startswith("/") or ".." in parts:
                    raise UpdateError(f"unsafe path in archive: {member.name!r}")
                if not member.isfile() or len(parts) != 2:
                    continue  # the top directory itself, .github/, etc.
                name = parts[1]
                if not name or _is_preserved(name):
                    continue
                handle = tar.extractfile(member)
                if handle is not None:
                    files[name] = handle.read()
    except tarfile.TarError as exc:
        raise UpdateError(f"downloaded archive is not readable: {exc}") from None
    if "VERSION" not in files or "homezai_client.py" not in files:
        raise UpdateError("downloaded archive does not look like homezai-skill")
    return files


def _install_files(base_dir: str, files: dict) -> None:
    """Write every file next to its target first, then swap them in."""
    staged = []
    try:
        for name, content in files.items():
            fd, tmp = tempfile.mkstemp(prefix=f".{name}.", dir=base_dir)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            staged.append((tmp, os.path.join(base_dir, name)))
        for tmp, target in staged:
            if os.path.exists(target):
                shutil.copymode(target, tmp)
            os.replace(tmp, target)
    finally:
        for tmp, _ in staged:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _git_pull(base_dir: str) -> None:
    result = subprocess.run(
        ["git", "-C", base_dir, "pull", "--ff-only"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(f"git pull --ff-only failed: {detail}")


def _clear_cache(base_dir: str) -> None:
    try:
        os.unlink(os.path.join(base_dir, vc.CACHE_FILENAME))
    except OSError:
        pass


def update(
    base_dir: Optional[str] = None,
    *,
    fetch_archive: Optional[Callable[[], bytes]] = None,
) -> tuple:
    """Update the install at ``base_dir``. Returns (old_version, new_version)."""
    base_dir = base_dir or _HERE
    old = vc._read_local_version(base_dir) or "unknown"
    if os.path.isdir(os.path.join(base_dir, ".git")):
        _git_pull(base_dir)
    else:
        data = (fetch_archive or _fetch_archive)()
        _install_files(base_dir, _skill_files_from_archive(data))
    _clear_cache(base_dir)
    new = vc._read_local_version(base_dir) or "unknown"
    return old, new


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Update the Homezai agent skill.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-check GitHub now and report, without updating",
    )
    args = parser.parse_args(argv)

    if args.check:
        _clear_cache(_HERE)
        message = vc.check_for_update(_HERE)
        local = vc._read_local_version(_HERE)
        if message:
            print(f"[homezai-skill] {message}")
            return 1
        print(f"[homezai-skill] {local} is the latest published version (or GitHub was unreachable).")
        return 0

    try:
        old, new = update(_HERE)
    except UpdateError as exc:
        print(f"[homezai-skill] UPDATE FAILED: {exc}", file=sys.stderr)
        return 2
    if old == new:
        print(f"[homezai-skill] already on the latest version ({new}).")
    else:
        print(
            f"[homezai-skill] updated {old} -> {new}. Re-read SKILL.md and "
            "LOCAL.md before continuing: commands or guidance may have changed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
