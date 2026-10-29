import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from galaxy import api, jobs, pc, session, tv
from tests.helpers import JobsCase, make_cfg, wait_idle

TOKEN = "secret-token"


class ApiCase(JobsCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = make_cfg(API_TOKEN=TOKEN)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(cls.cfg))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(3)

    def setUp(self):
        super().setUp()
        self.sleep = self.patch(api.time, "sleep")
        self.patch(api, "log")

    def patch(self, target, name, **kwargs):
        patcher = mock.patch.object(target, name, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def request(self, method, path, body=None, token=TOKEN, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(connection.close)
        sent = dict(headers or {})
        if token is not None:
            sent.setdefault("Authorization", f"Bearer {token}")
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.request(method, path, body=payload, headers=sent)
        response = connection.getresponse()
        data = response.read()
        return response, data

    def post(self, path, body=None, **kwargs):
        response, data = self.request("POST", path, body, **kwargs)
        return response.status, json.loads(data)


class AuthTests(ApiCase):
    def test_missing_token_is_401_and_delayed(self):
        status, body = self.post("/v1/stop", token=None)
        self.assertEqual((status, body), (401, {"error": "unauthorized"}))
        self.sleep.assert_called_once_with(0.3)

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

    def test_empty_configured_token_rejects_everything(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(make_cfg(API_TOKEN="")))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", "/v1/status", headers={"Authorization": "Bearer "})
        self.assertEqual(connection.getresponse().status, 401)


class GetTests(ApiCase):
    def test_root_serves_index_without_authentication(self):
        response, data = self.request("GET", "/", token=None)
        self.assertEqual(response.status, 200)
        self.assertEqual(data, api.INDEX.read_bytes())
        self.assertEqual(response.getheader("Content-Type"), "text/html; charset=utf-8")
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.sleep.assert_not_called()

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

    def test_connect_failure_is_reported_in_phase(self):
        self.connect.side_effect = RuntimeError("PC did not come up")
        self.assertEqual(self.post("/v1/connect", {})[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "error")
        self.assertEqual(jobs.snapshot()["error"], "PC did not come up")

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

    def test_oversized_content_length_is_400_without_reading_body(self):
        body = self.assert_bad_request(raw=b"{}", headers={"Content-Length": str(api.MAX_BODY + 1)})
        self.assertIn("too large", body["error"])

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


class ActionTests(ApiCase):
    def test_stop_submits_disconnect(self):
        disconnect = self.patch(session, "disconnect", __name__="disconnect")
        self.assertEqual(self.post("/v1/stop"), (202, {"accepted": "/v1/stop"}))
        self.assertTrue(wait_idle())
        disconnect.assert_called_once_with(self.cfg)

    def test_stop_is_409_while_busy(self):
        disconnect = self.patch(session, "disconnect", __name__="disconnect")
        jobs._job_lock.acquire()
        self.assertEqual(self.post("/v1/stop")[0], 409)
        disconnect.assert_not_called()

    def test_wake_sends_magic_packet(self):
        wake = self.patch(pc, "wake")
        self.assertEqual(self.post("/v1/wake")[0], 202)
        wake.assert_called_once_with(self.cfg)

    def test_wake_failure_is_502(self):
        self.patch(pc, "wake", side_effect=RuntimeError("PC_MAC is not a valid MAC address"))
        status, body = self.post("/v1/wake")
        self.assertEqual(status, 502)
        self.assertIn("MAC", body["error"])

    def test_tv_on_and_off_switch_in_background_without_reporting(self):
        switch = self.patch(tv, "switch", __name__="switch")
        self.assertEqual(self.post("/v1/tv/on")[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(self.post("/v1/tv/off")[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(switch.call_args_list, [mock.call(self.cfg, True), mock.call(self.cfg, False)])

    def test_tv_failure_does_not_change_phase(self):
        self.patch(tv, "switch", side_effect=OSError("cec"), __name__="switch")
        self.assertEqual(self.post("/v1/tv/on")[0], 202)
        self.assertTrue(wait_idle())
        self.assertEqual(jobs.snapshot()["phase"], "idle")

    def test_tv_is_409_while_busy(self):
        self.patch(tv, "switch", __name__="switch")
        jobs._job_lock.acquire()
        self.assertEqual(self.post("/v1/tv/on")[0], 409)

    def test_power_actions_call_pc_power(self):
        power = self.patch(pc, "power")
        for action in pc.POWER_COMMANDS:
            self.assertEqual(self.post(f"/v1/{action}"), (202, {"accepted": f"/v1/{action}"}))
        self.assertEqual([c.args[1] for c in power.call_args_list], list(pc.POWER_COMMANDS))

    def test_sleep_is_502_when_power_raises(self):
        self.patch(pc, "power", side_effect=RuntimeError("PC is not reachable over SSH"))
        status, body = self.post("/v1/sleep")
        self.assertEqual((status, body), (502, {"error": "PC is not reachable over SSH"}))

    def test_unknown_post_routes_are_404(self):
        for path in ("/v1/unknown", "/", "/v1/", "/v1/status"):
            self.assertEqual(self.post(path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
