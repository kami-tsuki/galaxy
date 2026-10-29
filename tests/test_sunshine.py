import hashlib
import itertools
import json
import unittest
from unittest import mock

from galaxy import sunshine
from tests.helpers import JobsCase, make_cfg, start_patch

CERT = b"certificate-bytes"
CERT_SHA = hashlib.sha256(CERT).hexdigest()


class ConnectionCase(unittest.TestCase):
    def setUp(self):
        factory = start_patch(self, sunshine.http.client, "HTTPSConnection")
        self.factory = factory
        self.connection = factory.return_value
        self.connection.sock.getpeercert.return_value = CERT
        self.reply(200, b"{}")

    def reply(self, status, body):
        answer = mock.Mock(status=status)
        answer.read.return_value = body
        self.connection.getresponse.return_value = answer


class ApiTests(ConnectionCase):
    def call(self, *args, **kwargs):
        cfg = make_cfg(SUNSHINE_UI_PORT="4999", **kwargs.pop("cfg", {}))
        return sunshine.api(cfg, *(args or ("GET", "/api/config")), **kwargs)

    def test_requires_username_before_connecting(self):
        with self.assertRaisesRegex(RuntimeError, "SUNSHINE_USER"):
            sunshine.api(make_cfg(SUNSHINE_USER=""), "GET", "/api/config")
        self.factory.assert_not_called()

    def test_connects_to_the_ui_port_over_https_with_timeout(self):
        self.call()
        args, kwargs = self.factory.call_args
        self.assertEqual(args, ("192.0.2.10", 4999))
        self.assertEqual(kwargs["timeout"], 15)
        self.assertIsNotNone(kwargs["context"])

    def test_sends_basic_auth_and_no_body_for_get(self):
        self.call()
        method, path = self.connection.request.call_args.args
        kwargs = self.connection.request.call_args.kwargs
        self.assertEqual((method, path), ("GET", "/api/config"))
        self.assertIsNone(kwargs["body"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Basic dXNlcjpwYXNz")

    def test_posts_json_body(self):
        self.call("POST", "/api/config", body={"a": 1})
        self.assertEqual(self.connection.request.call_args.args[0], "POST")
        self.assertEqual(json.loads(self.connection.request.call_args.kwargs["body"]), {"a": 1})
        self.assertEqual(self.connection.request.call_args.kwargs["headers"]["Content-Type"], "application/json")

    def test_parses_json_response(self):
        self.reply(200, b'{"x": 2}')
        self.assertEqual(self.call(), {"x": 2})

    def test_empty_response_is_empty_dict(self):
        self.reply(200, b"")
        self.assertEqual(self.call(), {})

    def test_connection_is_closed_on_success_and_on_error(self):
        self.call()
        self.connection.close.assert_called_once()
        self.connection.close.reset_mock()
        self.connection.request.side_effect = OSError("reset")
        with self.assertRaises(OSError):
            self.call()
        self.connection.close.assert_called_once()

    def test_rejected_login_statuses_name_the_credentials(self):
        for status in (401, 403):
            self.reply(status, b"")
            with self.assertRaisesRegex(RuntimeError, "rejected the login"):
                self.call()

    def test_other_error_statuses_report_code_and_path(self):
        for status in (400, 404, 500):
            self.reply(status, b"")
            with self.assertRaisesRegex(RuntimeError, f"answered {status} for /api/config"):
                self.call()

    def test_connection_errors_stay_oserror(self):
        self.connection.connect.side_effect = ConnectionRefusedError
        with self.assertRaises(OSError):
            self.call()
        self.connection.close.assert_called_once()

    def test_invalid_json_response_is_a_value_error_within_errors(self):
        self.reply(200, b"<html>")
        with self.assertRaises(ValueError):
            self.call()
        self.assertIn(ValueError, sunshine.ERRORS)
        self.assertIn(OSError, sunshine.ERRORS)
        self.assertIn(RuntimeError, sunshine.ERRORS)


class PinningTests(ConnectionCase):
    def call(self, pinned):
        return sunshine.api(make_cfg(SUNSHINE_CERT_SHA256=pinned), "GET", "/api/config")

    def test_matching_pin_allows_the_request(self):
        self.call(CERT_SHA)
        self.connection.request.assert_called_once()

    def test_pin_comparison_ignores_case_and_surrounding_whitespace(self):
        self.call(f"  {CERT_SHA.upper()} ")
        self.connection.request.assert_called_once()

    def test_mismatching_pin_aborts_before_sending_credentials(self):
        with self.assertRaisesRegex(RuntimeError, "python3 -m galaxy pin"):
            self.call("0" * 64)
        self.connection.request.assert_not_called()
        self.connection.close.assert_called_once()

    def test_empty_pin_skips_the_certificate_check(self):
        self.connection.sock.getpeercert.side_effect = AssertionError("must not read the certificate")
        self.call("")
        self.connection.request.assert_called_once()


class FingerprintTests(unittest.TestCase):
    def test_returns_sha256_of_the_peer_certificate(self):
        tls = mock.MagicMock()
        tls.__enter__.return_value.getpeercert.return_value = CERT
        context = mock.Mock()
        context.wrap_socket.return_value = tls
        sock = mock.MagicMock()
        with mock.patch.object(sunshine.socket, "create_connection", return_value=sock) as connect:
            with mock.patch.object(sunshine, "tls_context", return_value=context):
                result = sunshine.fingerprint(make_cfg(SUNSHINE_UI_PORT="4999"))
        self.assertEqual(result, CERT_SHA)
        self.assertEqual(connect.call_args.args[0], ("192.0.2.10", 4999))
        self.assertEqual(context.wrap_socket.call_args.kwargs["server_hostname"], "192.0.2.10")

    def test_connection_failure_propagates(self):
        with mock.patch.object(sunshine.socket, "create_connection", side_effect=OSError("down")):
            with self.assertRaises(OSError):
                sunshine.fingerprint(make_cfg())


class TlsContextTests(unittest.TestCase):
    def test_does_not_verify_the_chain_since_sunshine_is_self_signed(self):
        context = sunshine.tls_context()
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, sunshine.ssl.CERT_NONE)


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
