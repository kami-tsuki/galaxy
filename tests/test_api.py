import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from galaxy import api, config, jobs, pc, player, session, tv, watchdog
from tests.helpers import TOKEN, JobsCase, make_cfg, start_patch, wait_idle

SECURITY = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def serve_in_thread(case, source):
    server = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(source))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    case.addCleanup(thread.join, 3)
    case.addCleanup(server.server_close)
    case.addCleanup(server.shutdown)
    return server.server_address[1]


def send(case, port, method, path, token=TOKEN, headers=None, raw=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    case.addCleanup(connection.close)
    sent = dict(headers or {})
    if token is not None:
        sent.setdefault("Authorization", f"Bearer {token}")
    connection.request(method, path, body=raw, headers=sent)
    response = connection.getresponse()
    return response, response.read()


class ApiCase(JobsCase):
    state = {}

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(lambda: cls.state["cfg"]))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def setUp(self):
        super().setUp()
        self.state["cfg"] = make_cfg()
        self.cfg = self.state["cfg"]
        self.sleep = start_patch(self, api.time, "sleep")
        start_patch(self, api, "log")
        start_patch(self, jobs, "log")
        start_patch(self, player, "read_session", return_value={"app": "", "audio": ""})

    def patch(self, target, name, **kwargs):
        return start_patch(self, target, name, **kwargs)

    def request(self, method, path, body=None, token=TOKEN, headers=None, raw=None):
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        return send(self, self.port, method, path, token, headers, payload)

    def post(self, path, body=None, **kwargs):
        response, data = self.request("POST", path, body, **kwargs)
        return response.status, json.loads(data)


class AuthTests(ApiCase):
    def test_missing_token_is_401_and_delayed(self):
        status, body = self.post("/v1/stop", token=None)
        self.assertEqual((status, body), (401, {"error": "unauthorized"}))
        self.sleep.assert_called_once_with(api.FAILED_AUTH_DELAY)

    def test_wrong_token_is_401_for_post_and_get(self):
        self.assertEqual(self.post("/v1/stop", token="nope")[0], 401)
        self.assertEqual(self.request("GET", "/v1/status", token="nope")[0].status, 401)
        self.assertEqual(self.sleep.call_count, 2)

    def test_token_prefix_and_non_bearer_scheme_are_rejected(self):
        self.assertEqual(self.post("/v1/stop", token=TOKEN[:-1])[0], 401)
        self.assertEqual(self.post("/v1/stop", token=None, headers={"Authorization": f"Basic {TOKEN}"})[0], 401)
        self.assertEqual(self.post("/v1/stop", token=None, headers={"Authorization": TOKEN})[0], 401)

    def test_bearer_scheme_is_case_insensitive(self):
        self.patch(session, "status", return_value={})
        response, _ = self.request("GET", "/v1/status", token=None, headers={"Authorization": f"bearer {TOKEN}"})
        self.assertEqual(response.status, 200)

    def test_unauthorized_requests_do_not_trigger_actions(self):
        wake = self.patch(pc, "wake")
        self.post("/v1/wake", token="nope")
        wake.assert_not_called()

    def test_unknown_get_route_requires_auth_before_404(self):
        self.assertEqual(self.request("GET", "/nothing", token=None)[0].status, 401)

    def test_tokens_shorter_than_the_minimum_never_authorize(self):
        short = "s" * (config.MIN_TOKEN_LENGTH - 1)
        self.state["cfg"] = make_cfg(API_TOKEN=short)
        self.assertEqual(self.request("GET", "/v1/status", token=short)[0].status, 401)

    def test_token_of_exactly_the_minimum_length_authorizes(self):
        exact = "e" * config.MIN_TOKEN_LENGTH
        self.state["cfg"] = make_cfg(API_TOKEN=exact)
        self.patch(session, "status", return_value={})
        self.assertEqual(self.request("GET", "/v1/status", token=exact)[0].status, 200)

    def test_empty_configured_token_rejects_everything(self):
        self.state["cfg"] = make_cfg(API_TOKEN="")
        self.assertEqual(self.request("GET", "/v1/status", token="", headers={"Authorization": "Bearer "})[0].status, 401)


class ConfigSourceTests(ApiCase):
    def test_callable_provider_is_re_read_on_every_request(self):
        self.patch(session, "status", return_value={})
        other = "o" * config.MIN_TOKEN_LENGTH
        self.assertEqual(self.request("GET", "/v1/status")[0].status, 200)
        self.state["cfg"] = make_cfg(API_TOKEN=other)
        self.assertEqual(self.request("GET", "/v1/status")[0].status, 401)
        self.assertEqual(self.request("GET", "/v1/status", token=other)[0].status, 200)

    def test_status_receives_the_freshly_provided_config(self):
        status = self.patch(session, "status", return_value={})
        self.state["cfg"] = make_cfg(API_TOKEN=TOKEN, PC_HOST="198.51.100.7")
        self.request("GET", "/v1/status")
        self.assertEqual(status.call_args.args[0]["PC_HOST"], "198.51.100.7")

    def test_plain_dict_is_accepted_as_a_fixed_config(self):
        fixed = make_cfg()
        status = self.patch(session, "status", return_value={"phase": "idle"})
        port = serve_in_thread(self, fixed)
        response, data = send(self, port, "GET", "/v1/status")
        self.assertEqual((response.status, json.loads(data)), (200, {"phase": "idle"}))
        status.assert_called_once_with(fixed)

    def test_handler_has_a_socket_timeout(self):
        self.assertEqual(api.make_handler(make_cfg()).timeout, api.REQUEST_TIMEOUT)


class SecurityHeaderTests(ApiCase):
    def assert_secured(self, response):
        for name, value in SECURITY.items():
            self.assertEqual(response.getheader(name), value, name)
        policy = response.getheader("Content-Security-Policy")
        self.assertIn("default-src 'self'", policy)

    def test_index_reply_carries_security_headers(self):
        self.assert_secured(self.request("GET", "/", token=None)[0])

    def test_unauthorized_reply_carries_security_headers(self):
        self.assert_secured(self.request("GET", "/v1/status", token=None)[0])

    def test_not_found_reply_carries_security_headers(self):
        self.assert_secured(self.request("GET", "/v1/nope")[0])

    def test_accepted_post_reply_carries_security_headers(self):
        self.patch(pc, "wake")
        self.assert_secured(self.request("POST", "/v1/wake")[0])

    def test_error_reply_carries_security_headers(self):
        self.patch(session, "status", side_effect=OSError("boom"))
        self.assert_secured(self.request("GET", "/v1/status")[0])


class GetTests(ApiCase):
    def test_root_serves_index_without_authentication(self):
        response, data = self.request("GET", "/", token=None)
        self.assertEqual(response.status, 200)
        self.assertEqual(data, api.INDEX.read_bytes())
        self.assertEqual(response.getheader("Content-Type"), "text/html; charset=utf-8")
        self.sleep.assert_not_called()

    def test_index_path_is_the_web_page_next_to_api_py(self):
        self.assertEqual(api.INDEX, Path(api.__file__).resolve().parent / "web" / "index.html")
        self.assertTrue(api.INDEX.is_file())

    def test_root_ignores_query_string(self):
        self.assertEqual(self.request("GET", "/?x=1", token=None)[0].status, 200)

    def test_status_returns_session_status_json(self):
        shape = {"phase": "idle", "stream": False, "sources": ["main"], "busy": False}
        status = self.patch(session, "status", return_value=shape)
        response, data = self.request("GET", "/v1/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(json.loads(data), shape)
        self.assertEqual(int(response.getheader("Content-Length")), len(data))
        status.assert_called_once_with(self.cfg)

    def test_status_failure_is_a_502_not_a_dropped_connection(self):
        self.patch(session, "status", side_effect=OSError("boom"))
        response, data = self.request("GET", "/v1/status")
        self.assertEqual((response.status, json.loads(data)), (502, {"error": "boom"}))

    def test_unknown_authorized_route_is_404(self):
        response, data = self.request("GET", "/v1/nope")
        self.assertEqual((response.status, json.loads(data)), (404, {"error": "not found"}))


class ConnectTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.connect = self.patch(session, "connect", __name__="connect")

    def test_valid_body_is_accepted_and_connect_runs_with_options(self):
        status, body = self.post("/v1/connect", {"source": "second", "audio": "tv", "app": "Steam Big Picture"})
        self.assertEqual((status, body), (202, {"accepted": "/v1/connect"}))
        self.assertTrue(wait_idle())
        self.connect.assert_called_once_with(self.cfg, "second", "tv", "Steam Big Picture")

    def test_empty_body_uses_defaults(self):
        self.assertEqual(self.post("/v1/connect")[0], 202)
        self.assertTrue(wait_idle())
        self.connect.assert_called_once_with(self.cfg, "", "", "")

    def test_request_is_validated_through_session_resolve_before_submitting(self):
        resolve = self.patch(session, "resolve", side_effect=ValueError("nope"))
        status, body = self.post("/v1/connect", {"source": "main"})
        self.assertEqual((status, body), (400, {"error": "nope"}))
        resolve.assert_called_once_with(self.cfg, "main", "", "")
        self.connect.assert_not_called()
        self.assertFalse(jobs.busy())

    def test_connect_failure_is_reported_in_phase(self):
        self.connect.side_effect = RuntimeError("PC did not come up")
        self.assertEqual(self.post("/v1/connect", {})[0], 202)
        self.assertTrue(wait_idle())
        snap = jobs.snapshot()
        self.assertEqual((snap["phase"], snap["error"]), ("error", "PC did not come up"))

    def assert_bad_request(self, **kwargs):
        status, body = self.post("/v1/connect", **kwargs)
        self.assertEqual(status, 400, body)
        self.assertIn("error", body)
        self.connect.assert_not_called()
        self.assertFalse(jobs.busy())
        return body

    def test_invalid_json_is_400(self):
        self.assert_bad_request(raw=b"{not json")

    def test_non_object_bodies_are_400(self):
        for raw in (b"[]", b'"text"', b"42", b"null"):
            body = self.assert_bad_request(raw=raw)
            self.assertIn("JSON object", body["error"])

    def test_non_string_fields_are_400(self):
        for field in ("source", "audio", "app"):
            for value in (5, None, ["x"], {"a": 1}, True):
                body = self.assert_bad_request(body={field: value})
                self.assertIn(f"{field} must be a string", body["error"])

    def test_unknown_source_audio_and_app_are_400(self):
        self.assertIn("unknown source", self.assert_bad_request(body={"source": "tv"})["error"])
        self.assertIn("unknown audio", self.assert_bad_request(body={"audio": "loud"})["error"])
        self.assertIn("unknown app", self.assert_bad_request(body={"app": "Calc"})["error"])

    def test_obs_source_is_unknown_when_obs_disabled(self):
        self.assertIn("unknown source", self.assert_bad_request(body={"source": "obs"})["error"])

    def test_missing_pc_host_is_400_not_a_failed_job(self):
        self.state["cfg"] = make_cfg(PC_HOST="")
        self.assertIn("PC_HOST", self.assert_bad_request(body={"source": "main"})["error"])

    def test_missing_sunshine_user_is_400(self):
        self.state["cfg"] = make_cfg(SUNSHINE_USER="")
        self.assertIn("SUNSHINE_USER", self.assert_bad_request(body={"source": "main"})["error"])

    def test_no_displays_configured_is_400(self):
        self.state["cfg"] = make_cfg(DISPLAYS="")
        self.assertIn("no source", self.assert_bad_request()["error"])

    def test_oversized_content_length_is_400_without_reading_body(self):
        body = self.assert_bad_request(raw=b"{}", headers={"Content-Length": str(api.MAX_BODY + 1)})
        self.assertIn("bad body size", body["error"])

    def test_negative_content_length_is_400(self):
        body = self.assert_bad_request(raw=b"{}", headers={"Content-Length": "-5"})
        self.assertIn("bad body size", body["error"])

    def test_non_numeric_content_length_is_400(self):
        body = self.assert_bad_request(raw=b"{}", headers={"Content-Length": "abc"})
        self.assertIn("Content-Length", body["error"])

    def test_body_at_the_size_limit_is_parsed(self):
        padding = " " * (api.MAX_BODY - 2)
        self.assertEqual(self.post("/v1/connect", raw=b"{" + padding.encode() + b"}")[0], 202)
        self.assertTrue(wait_idle())

    def test_409_while_another_job_holds_the_lock(self):
        jobs._job_lock.acquire()
        status, body = self.post("/v1/connect", {"source": "main"})
        self.assertEqual(status, 409)
        self.assertIn("another action", body["error"])
        self.connect.assert_not_called()


class StopTests(ApiCase):
    def setUp(self):
        super().setUp()
        self.disconnect = self.patch(session, "disconnect", __name__="disconnect")

    def test_stop_submits_disconnect_and_is_accepted(self):
        self.assertEqual(self.post("/v1/stop"), (202, {"accepted": "/v1/stop"}))
        self.assertTrue(wait_idle())
        self.disconnect.assert_called_once_with(self.cfg)

    def test_stop_sets_intent_down_and_requests_cancel(self):
        jobs.update(intent="up")
        self.post("/v1/stop")
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["intent"], "down")
        self.assertTrue(jobs.cancelled())

    def test_stop_waits_for_a_running_job_instead_of_returning_409(self):
        seen = {}

        def finish_running_job():
            seen["intent"] = jobs.snapshot()["intent"]
            seen["cancelled"] = jobs.cancelled()
            jobs._job_lock.release()

        jobs.update(intent="up")
        jobs._job_lock.acquire()
        timer = threading.Timer(0.1, finish_running_job)
        timer.start()
        self.addCleanup(timer.cancel)
        status, body = self.post("/v1/stop")
        self.assertEqual((status, body), (202, {"accepted": "/v1/stop"}))
        self.assertEqual(seen, {"intent": "down", "cancelled": True})
        self.assertTrue(wait_idle())
        self.disconnect.assert_called_once_with(self.cfg)

    def test_stop_submits_with_wait(self):
        submit = self.patch(jobs, "submit")
        self.post("/v1/stop")
        submit.assert_called_once_with(session.disconnect, self.cfg, wait=True)

    def test_stop_gives_409_only_when_the_lock_wait_runs_out(self):
        self.patch(jobs, "LOCK_WAIT", new=0.05)
        jobs._job_lock.acquire()
        self.assertEqual(self.post("/v1/stop")[0], 409)
        self.disconnect.assert_not_called()


class ActionTests(ApiCase):
    def test_wake_sends_magic_packet_and_returns_200(self):
        wake = self.patch(pc, "wake")
        self.assertEqual(self.post("/v1/wake"), (200, {"accepted": "/v1/wake"}))
        wake.assert_called_once_with(self.cfg)

    def test_wake_failure_is_502(self):
        self.patch(pc, "wake", side_effect=RuntimeError("PC_MAC is not a valid MAC address"))
        status, body = self.post("/v1/wake")
        self.assertEqual(status, 502)
        self.assertIn("MAC", body["error"])

    def test_tv_on_and_off_switch_in_background_without_reporting(self):
        switch = self.patch(tv, "switch", __name__="switch")
        self.assertEqual(self.post("/v1/tv/on"), (202, {"accepted": "/v1/tv/on"}))
        self.assertTrue(wait_idle())
        self.assertEqual(self.post("/v1/tv/off")[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(switch.call_args_list, [mock.call(self.cfg, True), mock.call(self.cfg, False)])

    def test_tv_failure_does_not_change_phase(self):
        self.patch(tv, "switch", side_effect=OSError("cec"), __name__="switch")
        self.patch(jobs, "log")
        self.assertEqual(self.post("/v1/tv/on")[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "idle")

    def test_tv_is_409_while_busy(self):
        self.patch(tv, "switch", __name__="switch")
        jobs._job_lock.acquire()
        self.assertEqual(self.post("/v1/tv/on")[0], 409)

    def test_power_actions_call_pc_power_and_return_200(self):
        power = self.patch(pc, "power")
        for action in pc.POWER_COMMANDS:
            self.assertEqual(self.post(f"/v1/{action}"), (200, {"accepted": f"/v1/{action}"}))
        self.assertEqual([c.args[1] for c in power.call_args_list], list(pc.POWER_COMMANDS))

    def test_power_action_is_502_when_power_raises(self):
        self.patch(pc, "power", side_effect=RuntimeError("PC is not reachable over SSH"))
        for action in pc.POWER_COMMANDS:
            status, body = self.post(f"/v1/{action}")
            self.assertEqual((status, body), (502, {"error": "PC is not reachable over SSH"}))

    def test_unknown_post_routes_are_404(self):
        for path in ("/v1/unknown", "/", "/v1/", "/v1/status"):
            self.assertEqual(self.post(path)[0], 404, path)


class ServeTests(unittest.TestCase):
    def setUp(self):
        self.server_class = start_patch(self, api, "ThreadingHTTPServer")
        self.handler = start_patch(self, api, "make_handler")
        self.start = start_patch(self, watchdog, "start")
        start_patch(self, api, "log")
        self.cfg = make_cfg(API_BIND="127.0.0.1", API_PORT="8899")
        self.provider = lambda: self.cfg

    def test_short_token_aborts_startup(self):
        self.cfg = make_cfg(API_TOKEN="x" * (config.MIN_TOKEN_LENGTH - 1))
        with self.assertRaises(SystemExit) as caught:
            api.serve(self.provider)
        self.assertIn("API_TOKEN", str(caught.exception.code))
        self.server_class.assert_not_called()

    def test_empty_token_aborts_startup(self):
        self.cfg = make_cfg(API_TOKEN="")
        with self.assertRaises(SystemExit):
            api.serve(self.provider)

    def test_binds_the_configured_address_with_the_provider_handler(self):
        api.serve(self.provider)
        self.handler.assert_called_once_with(self.provider)
        self.server_class.assert_called_once_with(("127.0.0.1", 8899), self.handler.return_value)
        self.server_class.return_value.serve_forever.assert_called_once()

    def test_watchdog_starts_with_the_provider_when_enabled(self):
        self.cfg = make_cfg(WATCHDOG="true")
        api.serve(self.provider)
        self.start.assert_called_once_with(self.provider)

    def test_watchdog_is_not_started_when_disabled(self):
        self.cfg = make_cfg(WATCHDOG="false")
        api.serve(self.provider)
        self.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
