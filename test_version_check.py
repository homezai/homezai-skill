"""Deterministic tests for the cached daily version check.

Covers: fresh cache (no network), stale cache (network re-check), newer
upstream available (warning), same/older upstream (no warning), network failure
(fails open), and the once-per-day caching guarantee (network called at most
once). No real network calls — ``fetch_latest`` and ``now`` are injected.
"""

import json
import os
import tempfile
import unittest

import version_check as vc


def _write_version(base_dir, value):
    with open(os.path.join(base_dir, "VERSION"), "w", encoding="utf-8") as fh:
        fh.write(value)


class VersionCompareTests(unittest.TestCase):
    def test_semver_parse_and_compare(self):
        self.assertTrue(vc.is_outdated("1.0.0", "1.0.1"))
        self.assertTrue(vc.is_outdated("1.0.0", "1.1.0"))
        self.assertTrue(vc.is_outdated("1.9.0", "2.0.0"))
        self.assertFalse(vc.is_outdated("1.0.1", "1.0.0"))
        self.assertFalse(vc.is_outdated("2.0.0", "2.0.0"))

    def test_semver_tolerates_prefix_and_metadata(self):
        self.assertFalse(vc.is_outdated("v1.2.3", "1.2.3"))
        self.assertTrue(vc.is_outdated("1.2.3", "v1.2.4-beta"))
        # Garbage never raises.
        self.assertFalse(vc.is_outdated("", ""))


class CheckForUpdateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        _write_version(self.base, "1.0.0")
        self.calls = {"n": 0}

    def tearDown(self):
        self._tmp.cleanup()

    def _fetch(self, value):
        def _f():
            self.calls["n"] += 1
            return value
        return _f

    def _cache(self):
        path = os.path.join(self.base, vc.CACHE_FILENAME)
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def test_newer_upstream_warns_and_caches(self):
        msg = vc.check_for_update(
            self.base, now=lambda: 1000.0, fetch_latest=self._fetch("1.1.0")
        )
        self.assertIsNotNone(msg)
        # The notice is an instruction an agent can act on as written: the
        # exact updater path, and a promise that local secrets survive it.
        self.assertIn(f"python3 {os.path.join(self.base, 'update.py')}", msg)
        self.assertIn("re-read SKILL.md", msg)
        self.assertIn(".env", msg)
        self.assertIn("1.1.0", msg)
        self.assertEqual(self.calls["n"], 1)
        cache = self._cache()
        self.assertEqual(cache["latest_version"], "1.1.0")
        self.assertEqual(cache["checked_at"], 1000.0)

    def test_same_version_no_warning(self):
        msg = vc.check_for_update(
            self.base, now=lambda: 1000.0, fetch_latest=self._fetch("1.0.0")
        )
        self.assertIsNone(msg)

    def test_fresh_cache_skips_network(self):
        # Seed a fresh cache advertising a newer version.
        path = os.path.join(self.base, vc.CACHE_FILENAME)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"checked_at": 1000.0, "latest_version": "1.2.0"}, fh)
        # now is only 1h later -> cache still fresh -> no fetch.
        msg = vc.check_for_update(
            self.base, now=lambda: 1000.0 + 3600, fetch_latest=self._fetch("9.9.9")
        )
        self.assertIsNotNone(msg)
        self.assertIn("1.2.0", msg)  # used cached value, not fetched 9.9.9
        self.assertEqual(self.calls["n"], 0)  # network NOT called

    def test_stale_cache_triggers_network(self):
        path = os.path.join(self.base, vc.CACHE_FILENAME)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"checked_at": 1000.0, "latest_version": "1.0.0"}, fh)
        # 25h later -> stale -> re-fetch.
        later = 1000.0 + vc.CHECK_INTERVAL_SECONDS + 3600
        msg = vc.check_for_update(
            self.base, now=lambda: later, fetch_latest=self._fetch("1.3.0")
        )
        self.assertIsNotNone(msg)
        self.assertIn("1.3.0", msg)
        self.assertEqual(self.calls["n"], 1)
        self.assertEqual(self._cache()["latest_version"], "1.3.0")

    def test_network_failure_fails_open(self):
        msg = vc.check_for_update(
            self.base, now=lambda: 1000.0, fetch_latest=lambda: None
        )
        self.assertIsNone(msg)  # no warning
        # A failed attempt is still cached (with null latest) so we don't hammer
        # GitHub every command for the next 24h.
        self.assertEqual(self._cache()["latest_version"], None)

    def test_failed_check_is_rate_limited_for_a_day(self):
        # First (stale) check fails -> caches null latest at t=1000.
        vc.check_for_update(
            self.base, now=lambda: 1000.0, fetch_latest=lambda: None
        )
        # 1h later, still within interval -> must NOT call network again.
        vc.check_for_update(
            self.base, now=lambda: 1000.0 + 3600, fetch_latest=self._fetch("2.0.0")
        )
        self.assertEqual(self.calls["n"], 0)

    def test_missing_local_version_fails_open(self):
        os.remove(os.path.join(self.base, "VERSION"))
        msg = vc.check_for_update(
            self.base, now=lambda: 1000.0, fetch_latest=self._fetch("5.0.0")
        )
        self.assertIsNone(msg)


class MaybeWarnTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = self._tmp.name
        _write_version(self.base, "1.0.0")

    def tearDown(self):
        self._tmp.cleanup()

    def test_maybe_warn_never_raises(self):
        # Even with a fetch that raises, maybe_warn swallows it (fail open).
        import io

        def boom():
            raise RuntimeError("network exploded")

        # Monkeypatch the default fetch used inside check_for_update via a
        # stale cache so the network path is exercised.
        buf = io.StringIO()
        # Direct call path: check_for_update swallows fetch exceptions? It does
        # not; maybe_warn does. Simulate by pointing default fetch at boom.
        original = vc._default_fetch_latest
        vc._default_fetch_latest = boom
        try:
            result = vc.maybe_warn(self.base, stream=buf)
        finally:
            vc._default_fetch_latest = original
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
