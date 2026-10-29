import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from galaxy import obs
from tests.helpers import FakeObsServer, decode_bytes, expected_auth, make_cfg


class AuthResponseTests(unittest.TestCase):
    def test_matches_independent_obs_websocket_v5_computation(self):
        secret = base64.b64encode(hashlib.sha256(b"supersecretpasswordSALTSALT").digest())
        expected = base64.b64encode(hashlib.sha256(secret + b"CHALLENGE").digest()).decode()
        self.assertEqual(obs.auth_response("supersecretpassword", "SALTSALT", "CHALLENGE"), expected)

    def test_varies_with_each_input(self):
        base = obs.auth_response("p", "s", "c")
        self.assertEqual(base, expected_auth("p", "s", "c"))
        for args in (("q", "s", "c"), ("p", "t", "c"), ("p", "s", "d")):
            self.assertNotEqual(obs.auth_response(*args), base)


class EncodeFrameTests(unittest.TestCase):
    MASK = b"\x01\x02\x03\x04"

    def test_round_trips_payload_sizes_around_length_boundaries(self):
        for size, header in ((0, 2), (1, 2), (125, 2), (126, 4), (65535, 4), (65536, 10)):
            payload = os.urandom(size)
            data = obs.encode_frame(1, payload, self.MASK)
            frame = decode_bytes(data)
            self.assertEqual(len(data), header + 4 + size, size)
            self.assertEqual(frame["payload"], payload, size)
            self.assertEqual((frame["fin"], frame["opcode"], frame["masked"], frame["rest"]), (True, 1, True, b""), size)

    def test_length_markers(self):
        self.assertEqual(obs.encode_frame(1, b"x" * 125, self.MASK)[1], 0x80 | 125)
        self.assertEqual(obs.encode_frame(1, b"x" * 126, self.MASK)[1], 0x80 | 126)
        self.assertEqual(obs.encode_frame(1, b"x" * 65535, self.MASK)[2:4], b"\xff\xff")
        big = obs.encode_frame(1, b"x" * 65536, self.MASK)
        self.assertEqual((big[1], big[2:10]), (0x80 | 127, (65536).to_bytes(8, "big")))

    def test_payload_is_masked_on_the_wire(self):
        data = obs.encode_frame(1, b"\x00\x00\x00\x00\x00", self.MASK)
        self.assertEqual(data[2:6], self.MASK)
        self.assertEqual(data[6:], b"\x01\x02\x03\x04\x01")

    def test_opcode_is_preserved(self):
        for opcode in (1, 8, 9, 10):
            self.assertEqual(decode_bytes(obs.encode_frame(opcode, b"hi", self.MASK))["opcode"], opcode)


def server_cfg(server, password=""):
    return make_cfg(PC_HOST="127.0.0.1", OBS_PORT=str(server.port), OBS_PASS=password)


class ClientTests(unittest.TestCase):
    def test_identifies_without_authentication_when_server_has_no_password(self):
        with FakeObsServer() as server:
            with obs.Client(server_cfg(server)):
                pass
        self.assertEqual(server.identify, {"rpcVersion": 1})

    def test_authenticates_with_password(self):
        with FakeObsServer(password="hunter2") as server:
            with obs.Client(server_cfg(server, "hunter2")):
                pass
        self.assertEqual(
            server.identify["authentication"],
            expected_auth("hunter2", FakeObsServer.SALT, FakeObsServer.CHALLENGE),
        )

    def test_call_returns_response_data_and_sends_request_data(self):
        with FakeObsServer() as server:
            server.responses["GetProfileList"] = {"currentProfileName": "A", "profiles": ["A"]}
            with obs.Client(server_cfg(server)) as client:
                result = client.call("GetProfileList", {"x": 1})
                empty = client.call("StartStream")
        self.assertEqual(result, {"currentProfileName": "A", "profiles": ["A"]})
        self.assertEqual(empty, {})
        self.assertEqual(server.requests, [("GetProfileList", {"x": 1}), ("StartStream", {})])

    def test_failed_request_raises_with_obs_comment(self):
        with FakeObsServer(failures={"StartStream": "Output is busy"}) as server:
            with obs.Client(server_cfg(server)) as client:
                with self.assertRaisesRegex(RuntimeError, "Output is busy"):
                    client.call("StartStream")

    def test_failed_request_without_comment_names_the_request(self):
        with FakeObsServer(failures={"StartStream": ""}) as server:
            with obs.Client(server_cfg(server)) as client:
                with self.assertRaisesRegex(RuntimeError, "StartStream failed"):
                    client.call("StartStream")

    def test_wrong_password_reports_authentication_failure(self):
        with FakeObsServer(password="right") as server:
            with self.assertRaisesRegex(RuntimeError, "authentication failed, check OBS_PASS"):
                obs.Client(server_cfg(server, "wrong"))

    def test_server_ping_is_answered_with_pong_carrying_same_payload(self):
        with FakeObsServer(ping_before_response=True) as server:
            with obs.Client(server_cfg(server)) as client:
                client.call("GetStreamStatus")
                client.call("GetStreamStatus")
        self.assertEqual(server.pongs[:1], [b"hb"])

    def test_handshake_rejection_raises(self):
        with FakeObsServer(handshake_status="400 Bad Request") as server:
            with self.assertRaisesRegex(RuntimeError, "handshake failed"):
                obs.Client(server_cfg(server))

    def test_connection_refused_is_oserror(self):
        with FakeObsServer() as server:
            cfg = server_cfg(server)
        with self.assertRaises(OSError):
            obs.Client(cfg)

    def test_call_on_closed_socket_raises_oserror(self):
        with FakeObsServer() as server:
            with obs.Client(server_cfg(server)) as client:
                client.ws.sock.close()
                with self.assertRaises(OSError):
                    client.call("GetStreamStatus")


def raw_frame(opcode, payload, fin=True):
    first = (0x80 if fin else 0) | opcode
    if len(payload) < 126:
        return bytes([first, len(payload)]) + payload
    return bytes([first, 126]) + len(payload).to_bytes(2, "big") + payload


def ws_with(data):
    ws = obs.Ws.__new__(obs.Ws)
    ws.buf = data
    ws.sock = mock.Mock()
    ws.sock.recv.return_value = b""
    return ws


class WsRecvTests(unittest.TestCase):
    def test_single_frame_message(self):
        self.assertEqual(ws_with(raw_frame(1, b'{"op": 2}')).recv(), {"op": 2})

    def test_fragmented_message_is_reassembled_across_continuation_frames(self):
        data = raw_frame(1, b'{"op": ', fin=False) + raw_frame(0, b'"x', fin=False) + raw_frame(0, b'y"}')
        self.assertEqual(ws_with(data).recv(), {"op": "xy"})

    def test_ping_between_fragments_is_answered_and_message_still_completes(self):
        data = raw_frame(1, b'{"a":', fin=False) + raw_frame(9, b"hb") + raw_frame(0, b" 1}")
        ws = ws_with(data)
        with mock.patch.object(ws, "send_frame") as send:
            self.assertEqual(ws.recv(), {"a": 1})
        send.assert_called_once_with(10, b"hb")

    def test_message_is_not_returned_before_the_final_fragment(self):
        ws = ws_with(raw_frame(1, b'{"a": 1}', fin=False))
        with self.assertRaisesRegex(RuntimeError, "closed the connection"):
            ws.recv()

    def test_consecutive_messages_are_read_one_at_a_time(self):
        ws = ws_with(raw_frame(1, b'{"n": 1}') + raw_frame(1, b'{"n": 2}'))
        self.assertEqual([ws.recv(), ws.recv()], [{"n": 1}, {"n": 2}])

    def test_oversized_frame_is_rejected_before_reading_payload(self):
        header = bytes([0x81, 127]) + (obs.MAX_FRAME + 1).to_bytes(8, "big")
        with self.assertRaisesRegex(RuntimeError, "oversized"):
            ws_with(header).recv()

    def test_frame_at_the_limit_is_not_rejected_as_oversized(self):
        header = bytes([0x81, 127]) + obs.MAX_FRAME.to_bytes(8, "big")
        with self.assertRaisesRegex(RuntimeError, "closed the connection"):
            ws_with(header).recv()

    def test_close_frame_reports_known_reason(self):
        data = raw_frame(8, (4009).to_bytes(2, "big") + b"no")
        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            ws_with(data).recv()

    def test_close_frame_with_unknown_code_reports_the_code(self):
        with self.assertRaisesRegex(RuntimeError, "code 1006"):
            ws_with(raw_frame(8, (1006).to_bytes(2, "big"))).recv()

    def test_close_frame_without_payload_reports_code_zero(self):
        with self.assertRaisesRegex(RuntimeError, "code 0"):
            ws_with(raw_frame(8, b"")).recv()


class ConstantsTests(unittest.TestCase):
    def test_canvas_and_audio_bitrate(self):
        self.assertEqual(obs.CANVAS, (1920, 1080))
        self.assertEqual(obs.AUDIO_BITRATE, "160")

    def test_previous_profile_file_lives_in_the_runtime_dir(self):
        with mock.patch.object(obs.config, "runtime_dir", return_value=Path("/run/user/7")):
            self.assertEqual(obs.previous_profile_file(), Path("/run/user/7/galaxy-obs-previous"))


class ObsTimeoutTests(unittest.TestCase):
    def test_timeout_names_the_dialog_cause(self):
        client = obs.Client.__new__(obs.Client)
        client.ws = mock.Mock()
        client.ws.recv.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError) as caught:
            client.call("GetVersion")
        self.assertIn("dialog", str(caught.exception))


class HandshakeSocketTests(unittest.TestCase):
    def test_rejected_handshake_closes_the_socket(self):
        sock = mock.Mock()
        sock.recv.return_value = b"HTTP/1.1 403 Forbidden\r\n\r\n"
        with mock.patch.object(obs.socket, "create_connection", return_value=sock):
            with self.assertRaisesRegex(RuntimeError, "handshake failed"):
                obs.Ws("127.0.0.1", 4455)
        sock.close.assert_called_once()

    def test_connection_closed_during_handshake_closes_the_socket(self):
        sock = mock.Mock()
        sock.recv.return_value = b""
        with mock.patch.object(obs.socket, "create_connection", return_value=sock):
            with self.assertRaises(RuntimeError):
                obs.Ws("127.0.0.1", 4455)
        sock.close.assert_called_once()


class FakeObs:
    def __init__(self, current="Other", profiles=("Other",), streaming=False, camera=False):
        self.current = current
        self.profiles = list(profiles)
        self.streaming = streaming
        self.camera = camera
        self.video = {"baseWidth": 640, "baseHeight": 480, "outputWidth": 640, "outputHeight": 480, "fpsNumerator": 30}
        self.video_error = None
        self.calls = []
        self.error = None

    def __call__(self, cfg):
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def call(self, kind, data=None):
        self.calls.append((kind, data))
        if kind == "GetStreamStatus":
            return {"outputActive": self.streaming}
        if kind == "GetProfileList":
            return {"currentProfileName": self.current, "profiles": self.profiles}
        if kind == "GetVideoSettings":
            return dict(self.video)
        if kind == "GetVirtualCamStatus":
            return {"outputActive": self.camera}
        if kind == "StopVirtualCam":
            self.camera = False
        if kind == "StartVirtualCam":
            self.camera = True
        if kind == "SetVideoSettings":
            if self.video_error:
                raise self.video_error
            self.video = dict(data)
        if kind == "StartStream":
            self.streaming = True
        if kind == "StopStream":
            self.streaming = False
        if kind == "SetCurrentProfile":
            self.current = data["profileName"]
        return {}

    def kinds(self):
        return [kind for kind, _ in self.calls]

    def payload(self, kind):
        return [data for name, data in self.calls if name == kind]


class ObsFlowCase(unittest.TestCase):
    URL = "srt://10.0.0.5:9000?mode=caller&pkt_size=1316"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.previous = Path(tmp.name) / "previous"
        self.fake = FakeObs()
        for patcher in (
            mock.patch.object(obs, "Client", self.fake),
            mock.patch.object(obs, "previous_profile_file", return_value=self.previous),
            mock.patch.object(obs.time, "sleep"),
            mock.patch.object(obs, "log"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class BeginTests(ObsFlowCase):
    def begin(self, **overrides):
        obs.begin(make_cfg(OBS_FPS="30", OBS_BITRATE="6000", **overrides), self.URL)

    def test_creates_galaxy_profile_and_issues_full_request_sequence(self):
        self.begin()
        self.assertEqual(
            self.fake.kinds(),
            [
                "GetStreamStatus",
                "GetProfileList",
                "CreateProfile",
                "GetVideoSettings",
                "GetVirtualCamStatus",
                "SetVideoSettings",
                "SetProfileParameter",
                "SetProfileParameter",
                "SetProfileParameter",
                "SetStreamServiceSettings",
                "StartStream",
                "GetStreamStatus",
            ],
        )
        self.assertEqual(self.fake.payload("CreateProfile"), [{"profileName": "Galaxy"}])

    def test_video_settings_are_1080p_at_configured_fps(self):
        self.begin()
        self.assertEqual(
            self.fake.payload("SetVideoSettings"),
            [
                {
                    "baseWidth": 1920,
                    "baseHeight": 1080,
                    "outputWidth": 1920,
                    "outputHeight": 1080,
                    "fpsNumerator": 30,
                    "fpsDenominator": 1,
                }
            ],
        )

    def test_profile_parameters_use_configured_bitrate(self):
        self.begin()
        got = [(d["parameterCategory"], d["parameterName"], d["parameterValue"]) for d in self.fake.payload("SetProfileParameter")]
        self.assertEqual(
            got,
            [("Output", "Mode", "Simple"), ("SimpleOutput", "VBitrate", "6000"), ("SimpleOutput", "ABitrate", "160")],
        )

    def test_stream_service_is_custom_rtmp_with_srt_url(self):
        self.begin()
        self.assertEqual(
            self.fake.payload("SetStreamServiceSettings"),
            [{"streamServiceType": "rtmp_custom", "streamServiceSettings": {"server": self.URL, "key": "", "use_auth": False}}],
        )

    def test_remembers_previous_profile(self):
        self.begin()
        self.assertEqual(self.previous.read_text(), "Other")

    def test_switches_to_existing_galaxy_profile_instead_of_creating(self):
        self.fake.profiles = ["Other", "Galaxy"]
        self.begin()
        self.assertEqual(self.fake.payload("SetCurrentProfile"), [{"profileName": "Galaxy"}])
        self.assertNotIn("CreateProfile", self.fake.kinds())

    def test_custom_profile_name_is_used(self):
        self.begin(OBS_PROFILE="Stream")
        self.assertEqual(self.fake.payload("CreateProfile"), [{"profileName": "Stream"}])

    def test_already_on_galaxy_profile_is_not_switched_or_remembered(self):
        self.fake.current = "Galaxy"
        self.begin()
        self.assertNotIn("CreateProfile", self.fake.kinds())
        self.assertNotIn("SetCurrentProfile", self.fake.kinds())
        self.assertFalse(self.previous.exists())
        self.assertIn("StartStream", self.fake.kinds())

    def test_refuses_when_obs_is_already_streaming(self):
        self.fake.streaming = True
        with self.assertRaisesRegex(RuntimeError, "already streaming"):
            self.begin()
        self.assertEqual(self.fake.kinds(), ["GetStreamStatus"])
        self.assertFalse(self.previous.exists())

    def test_raises_when_stream_never_becomes_active(self):
        with mock.patch.object(obs, "wait_stream", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "did not start streaming"):
                self.begin()


class WaitReadyTests(ObsFlowCase):
    def test_retries_on_oserror_until_connected(self):
        attempts = [OSError("refused"), OSError("refused")]

        def client(cfg):
            if attempts:
                raise attempts.pop()
            return self.fake

        with mock.patch.object(obs, "Client", client):
            obs.wait_ready(make_cfg())
        self.assertEqual(attempts, [])

    def test_gives_up_after_deadline(self):
        with mock.patch.object(obs, "Client", side_effect=OSError):
            with mock.patch.object(obs.time, "time", side_effect=[0, 31]):
                with self.assertRaisesRegex(RuntimeError, "OBS is not running"):
                    obs.wait_ready(make_cfg())


class EndTests(ObsFlowCase):
    def end(self):
        obs.end(make_cfg())

    def test_does_nothing_when_current_profile_is_not_galaxy(self):
        self.previous.write_text("Other")
        self.fake.streaming = True
        self.end()
        self.assertEqual(self.fake.kinds(), ["GetProfileList"])
        self.assertTrue(self.previous.exists())

    def test_stops_stream_and_restores_previous_profile(self):
        self.fake.current, self.fake.streaming = "Galaxy", True
        self.fake.profiles = ["Other", "Galaxy"]
        self.previous.write_text("Other\n")
        self.end()
        self.assertFalse(self.fake.streaming)
        self.assertEqual(self.fake.payload("SetCurrentProfile"), [{"profileName": "Other"}])
        self.assertIn("StopStream", self.fake.kinds())
        self.assertFalse(self.previous.exists())

    def test_does_not_stop_stream_that_is_not_running(self):
        self.fake.current = "Galaxy"
        self.previous.write_text("Other")
        self.fake.profiles = ["Other", "Galaxy"]
        self.end()
        self.assertNotIn("StopStream", self.fake.kinds())
        self.assertEqual(self.fake.current, "Other")

    def test_skips_restore_when_previous_profile_no_longer_exists(self):
        self.fake.current, self.fake.profiles = "Galaxy", ["Galaxy"]
        self.previous.write_text("Deleted")
        self.end()
        self.assertNotIn("SetCurrentProfile", self.fake.kinds())
        self.assertFalse(self.previous.exists())

    def test_without_previous_file_leaves_profile_alone(self):
        self.fake.current = "Galaxy"
        self.end()
        self.assertNotIn("SetCurrentProfile", self.fake.kinds())

    def test_unreachable_obs_is_logged_and_ignored(self):
        for error in (OSError("down"), RuntimeError("auth")):
            self.fake.error = error
            self.end()
            self.assertEqual(self.fake.calls, [])


if __name__ == "__main__":
    unittest.main()


class CanvasTests(ObsFlowCase):
    def begin(self, **overrides):
        obs.begin(make_cfg(OBS_FPS="60", **overrides), self.URL)

    def test_matching_canvas_is_left_alone(self):
        self.fake.video = {
            "baseWidth": 1920, "baseHeight": 1080, "outputWidth": 1920, "outputHeight": 1080,
            "fpsNumerator": 60, "fpsDenominator": 1,
        }
        self.begin()
        self.assertNotIn("SetVideoSettings", self.fake.kinds())
        self.assertNotIn("GetVirtualCamStatus", self.fake.kinds())

    def test_running_virtual_camera_is_paused_and_restored(self):
        self.fake.camera = True
        self.begin()
        kinds = self.fake.kinds()
        self.assertLess(kinds.index("StopVirtualCam"), kinds.index("SetVideoSettings"))
        self.assertLess(kinds.index("SetVideoSettings"), kinds.index("StartVirtualCam"))
        self.assertTrue(self.fake.camera)

    def test_stopped_virtual_camera_stays_stopped(self):
        self.begin()
        self.assertNotIn("StartVirtualCam", self.fake.kinds())
        self.assertFalse(self.fake.camera)

    def test_rejected_change_explains_what_to_stop_and_restores_camera(self):
        self.fake.camera = True
        self.fake.video_error = RuntimeError("Video settings cannot be changed while an output is active.")
        with self.assertRaises(RuntimeError) as caught:
            self.begin()
        self.assertIn("stop any recording or stream in OBS", str(caught.exception))
        self.assertTrue(self.fake.camera)
        self.assertNotIn("StartStream", self.fake.kinds())

