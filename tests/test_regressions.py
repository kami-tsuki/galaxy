import json
import socket
import threading
import unittest
from unittest import mock

from galaxy import obs, pc, player, session
from tests.helpers import make_cfg
from tests.test_api import ApiCase


class ValidationRegressionTests(unittest.TestCase):
    def test_resolution_with_trailing_newline_is_rejected(self):
        with self.assertRaises(ValueError):
            player.write_session(make_cfg(), "Desktop", "both", "1920x1080\n", path="unused")

    def test_mac_with_trailing_newline_is_rejected(self):
        with self.assertRaises(RuntimeError):
            pc.magic_packet("aa:bb:cc:dd:ee:ff\n")


class HandshakeRegressionTests(unittest.TestCase):
    def test_rejected_handshake_closes_the_socket(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        accepted = []

        def serve():
            connection, _ = server.accept()
            accepted.append(connection)
            connection.recv(4096)
            connection.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        closed = []
        real_close = socket.socket.close

        def tracking_close(sock):
            closed.append(sock)
            return real_close(sock)

        with mock.patch.object(socket.socket, "close", tracking_close):
            with self.assertRaises(RuntimeError):
                obs.Ws("127.0.0.1", server.getsockname()[1])
        thread.join(3)
        for connection in accepted:
            connection.close()
        server.close()
        self.assertTrue(closed)


class ObsTimeoutRegressionTests(unittest.TestCase):
    def test_timeout_names_the_dialog_cause(self):
        client = obs.Client.__new__(obs.Client)
        client.ws = mock.Mock()
        client.ws.recv.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError) as caught:
            client.call("GetVersion")
        self.assertIn("dialog", str(caught.exception))


class StatusErrorRegressionTests(ApiCase):
    def test_status_failure_is_a_502_not_a_dropped_connection(self):
        self.patch(session, "status", side_effect=OSError("boom"))
        response, data = self.request("GET", "/v1/status")
        self.assertEqual(response.status, 502)
        self.assertEqual(json.loads(data), {"error": "boom"})
