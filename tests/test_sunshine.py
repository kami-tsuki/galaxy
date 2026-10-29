import io
import itertools
import json
import unittest
import urllib.error
from unittest import mock

from galaxy import sunshine
from tests.helpers import JobsCase, make_cfg


def response(body):
    handle = mock.MagicMock()
    handle.__enter__.return_value.read.return_value = body
    return handle


class ApiTests(unittest.TestCase):
    def call(self, raw=b"{}", **kwargs):
        with mock.patch.object(sunshine.urllib.request, "urlopen", return_value=response(raw)) as urlopen:
            result = sunshine.api(make_cfg(SUNSHINE_UI_PORT="4999"), *kwargs.pop("args", ("GET", "/api/config")), **kwargs)
        return result, urlopen.call_args.args[0]

    def test_requires_username(self):
        with mock.patch.object(sunshine.urllib.request, "urlopen") as urlopen:
            with self.assertRaisesRegex(RuntimeError, "SUNSHINE_USER"):
                sunshine.api(make_cfg(SUNSHINE_USER=""), "GET", "/api/config")
        urlopen.assert_not_called()

    def test_builds_https_request_with_basic_auth(self):
        _, request = self.call()
        self.assertEqual(request.full_url, "https://192.0.2.10:4999/api/config")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Basic dXNlcjpwYXNz")
        self.assertIsNone(request.data)

    def test_posts_json_body(self):
        _, request = self.call(args=("POST", "/api/config"), body={"a": 1})
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"a": 1})

    def test_parses_json_response(self):
        result, _ = self.call(b'{"x": 2}')
        self.assertEqual(result, {"x": 2})

    def test_empty_response_is_empty_dict(self):
        result, _ = self.call(b"")
        self.assertEqual(result, {})

    def test_http_error_becomes_runtime_error_with_status(self):
        error = urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO())
        with mock.patch.object(sunshine.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "401"):
                sunshine.api(make_cfg(), "GET", "/api/config")

    def test_connection_errors_stay_oserror(self):
        with mock.patch.object(sunshine.urllib.request, "urlopen", side_effect=ConnectionRefusedError):
            with self.assertRaises(OSError):
                sunshine.api(make_cfg(), "GET", "/api/config")


class SettingsTests(unittest.TestCase):
    def test_drops_platform_version_and_status(self):
        payload = {"platform": "linux", "version": "1", "status": "ok", "output_name": "x", "fps": "[60]"}
        with mock.patch.object(sunshine, "api", return_value=payload) as api:
            self.assertEqual(sunshine.settings(make_cfg()), {"output_name": "x", "fps": "[60]"})
        api.assert_called_once_with(mock.ANY, "GET", "/api/config")


class CurrentOutputTests(JobsCase):
    def test_returns_output_name_and_caches(self):
        with mock.patch.object(sunshine, "settings", return_value={"output_name": "dev1"}) as settings:
            self.assertEqual(sunshine.current_output(make_cfg()), "dev1")
            self.assertEqual(sunshine.current_output(make_cfg()), "dev1")
        settings.assert_called_once()

    def test_missing_output_name_is_empty_string(self):
        with mock.patch.object(sunshine, "settings", return_value={}):
            self.assertEqual(sunshine.current_output(make_cfg()), "")

    def test_errors_yield_none(self):
        for error in (OSError("x"), RuntimeError("x"), ValueError("x")):
            sunshine.jobs.invalidate("sunshine-output")
            with mock.patch.object(sunshine, "settings", side_effect=error):
                self.assertIsNone(sunshine.current_output(make_cfg()))


class WaitRestartTests(unittest.TestCase):
    def setUp(self):
        sleep = mock.patch.object(sunshine.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_waits_for_shutdown_then_for_settings_to_answer(self):
        with mock.patch.object(sunshine.pc, "sunshine_up", side_effect=[True, False, True, True]):
            with mock.patch.object(sunshine, "settings", side_effect=[OSError, {}]) as settings:
                sunshine.wait_restart(make_cfg())
        self.assertEqual(settings.call_count, 2)

    def test_raises_when_sunshine_never_returns(self):
        with mock.patch.object(sunshine.pc, "sunshine_up", return_value=False):
            with mock.patch.object(sunshine.time, "time", side_effect=itertools.count(0, 30)):
                with self.assertRaisesRegex(RuntimeError, "did not come back"):
                    sunshine.wait_restart(make_cfg())


class SelectOutputTests(JobsCase):
    def setUp(self):
        super().setUp()
        self.posts = []
        self.current = {"output_name": "dev-old", "fps": "[60]", "min_log_level": "2"}
        api = mock.patch.object(sunshine, "api", side_effect=self.fake_api)
        wait = mock.patch.object(sunshine, "wait_restart")
        self.api, self.wait = api.start(), wait.start()
        self.addCleanup(api.stop)
        self.addCleanup(wait.stop)

    def fake_api(self, cfg, method, path, body=None):
        if method == "GET":
            return {**self.current, "platform": "linux", "version": "1", "status": "ok"}
        self.posts.append((path, body))
        return {}

    def test_returns_false_without_post_when_already_selected(self):
        self.assertFalse(sunshine.select_output(make_cfg(), "dev-old"))
        self.assertEqual(self.posts, [])
        self.wait.assert_not_called()

    def test_posts_full_settings_with_new_output_then_restarts(self):
        self.assertTrue(sunshine.select_output(make_cfg(), "dev-new"))
        self.assertEqual(
            self.posts,
            [("/api/config", {"output_name": "dev-new", "fps": "[60]", "min_log_level": "2"}), ("/api/restart", {})],
        )
        self.wait.assert_called_once()

    def test_posted_body_excludes_ignored_keys(self):
        sunshine.select_output(make_cfg(), "dev-new")
        for key in sunshine.IGNORED_KEYS:
            self.assertNotIn(key, self.posts[0][1])

    def test_connection_drop_during_restart_is_tolerated(self):
        def flaky(cfg, method, path, body=None):
            if path == "/api/restart":
                raise ConnectionResetError
            return self.fake_api(cfg, method, path, body)

        self.api.side_effect = flaky
        self.assertTrue(sunshine.select_output(make_cfg(), "dev-new"))
        self.wait.assert_called_once()

    def test_invalidates_cached_output_after_change(self):
        sunshine.jobs.cached("sunshine-output", 60, lambda: "stale")
        sunshine.select_output(make_cfg(), "dev-new")
        self.assertNotIn("sunshine-output", sunshine.jobs._cache)

    def test_api_error_propagates_before_any_restart(self):
        def failing(cfg, method, path, body=None):
            if method == "POST":
                raise RuntimeError("Sunshine answered 400")
            return self.fake_api(cfg, method, path, body)

        self.api.side_effect = failing
        with self.assertRaises(RuntimeError):
            sunshine.select_output(make_cfg(), "dev-new")
        self.wait.assert_not_called()


if __name__ == "__main__":
    unittest.main()
