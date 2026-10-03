"""Offline tests for update.py. No network: the archive is built in memory.

    python -m pytest test_update.py -q
"""

import io
import os
import tarfile
import tempfile
import unittest

import update
import version_check as vc


def _archive(files, top="homezai-skill-main", extra=None):
    """Build a GitHub-style tar.gz with every path under one top directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        dir_info = tarfile.TarInfo(top)
        dir_info.type = tarfile.DIRTYPE
        tar.addfile(dir_info)
        for name, content in {**files, **(extra or {})}.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


UPSTREAM = {
    "VERSION": "9.9.9\n",
    "homezai_client.py": "# new client\n",
    "SKILL.md": "new skill doc\n",
    "LOCAL.md": "upstream must never overwrite this\n",
    ".env": "HOMEZAI_API_TOKEN=hzai_upstream_should_never_land\n",
    ".env.example": "HOMEZAI_API_TOKEN=hzai_your_token_here\n",
}


class UpdateFromArchiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        self._write("VERSION", "1.0.0\n")
        self._write("homezai_client.py", "# old client\n")
        self._write(".env", "HOMEZAI_API_TOKEN=hzai_mine\n")
        self._write("LOCAL.md", "my install notes\n")
        self._write(vc.CACHE_FILENAME, '{"checked_at": 1, "latest_version": "9.9.9"}')

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, name, content):
        with open(os.path.join(self.base, name), "w", encoding="utf-8") as fh:
            fh.write(content)

    def _read(self, name):
        with open(os.path.join(self.base, name), "r", encoding="utf-8") as fh:
            return fh.read()

    def test_replaces_skill_files_and_reports_versions(self):
        old, new = update.update(self.base, fetch_archive=lambda: _archive(UPSTREAM))
        self.assertEqual((old, new), ("1.0.0", "9.9.9"))
        self.assertEqual(self._read("homezai_client.py"), "# new client\n")
        self.assertEqual(self._read("SKILL.md"), "new skill doc\n")
        self.assertEqual(self._read(".env.example"), "HOMEZAI_API_TOKEN=hzai_your_token_here\n")

    def test_never_touches_env_or_local_notes(self):
        update.update(self.base, fetch_archive=lambda: _archive(UPSTREAM))
        self.assertEqual(self._read(".env"), "HOMEZAI_API_TOKEN=hzai_mine\n")
        self.assertEqual(self._read("LOCAL.md"), "my install notes\n")

    def test_clears_the_version_cache_so_the_next_check_is_fresh(self):
        update.update(self.base, fetch_archive=lambda: _archive(UPSTREAM))
        self.assertFalse(os.path.exists(os.path.join(self.base, vc.CACHE_FILENAME)))

    def test_skips_nested_directories(self):
        data = _archive(UPSTREAM, extra={".github/workflows/ci.yml": "name: CI\n"})
        update.update(self.base, fetch_archive=lambda: data)
        self.assertFalse(os.path.exists(os.path.join(self.base, ".github")))
        self.assertFalse(os.path.exists(os.path.join(self.base, "ci.yml")))

    def test_rejects_an_archive_with_a_parent_reference(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"x"
            info = tarfile.TarInfo("homezai-skill-main/../escape.py")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        with self.assertRaises(update.UpdateError):
            update.update(self.base, fetch_archive=lambda: buf.getvalue())
        self.assertEqual(self._read("homezai_client.py"), "# old client\n")

    def test_rejects_an_archive_that_is_not_this_skill(self):
        with self.assertRaises(update.UpdateError):
            update.update(self.base, fetch_archive=lambda: _archive({"README.md": "x"}))
        self.assertEqual(self._read("VERSION"), "1.0.0\n")

    def test_a_failed_download_is_loud_and_changes_nothing(self):
        def boom():
            raise update.UpdateError("could not download: offline")

        with self.assertRaises(update.UpdateError):
            update.update(self.base, fetch_archive=boom)
        self.assertEqual(self._read("VERSION"), "1.0.0\n")


class GitInstallTests(unittest.TestCase):
    def test_a_git_checkout_is_updated_with_git_pull(self):
        with tempfile.TemporaryDirectory() as base:
            os.mkdir(os.path.join(base, ".git"))
            with open(os.path.join(base, "VERSION"), "w") as fh:
                fh.write("1.0.0")
            calls = []
            original = update._git_pull
            update._git_pull = lambda d: calls.append(d)
            try:
                old, new = update.update(base, fetch_archive=lambda: self.fail("no download"))
            finally:
                update._git_pull = original
            self.assertEqual(calls, [base])
            self.assertEqual((old, new), ("1.0.0", "1.0.0"))


if __name__ == "__main__":
    unittest.main()
