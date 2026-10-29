import base64
import hashlib
import io
import json
import socket
import threading
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from galaxy import config, jobs

real_sleep = time.sleep
TOKEN = "t" * config.MIN_TOKEN_LENGTH


def make_cfg(**overrides):
    cfg = dict(config.DEFAULTS)
    cfg.update(
        PC_HOST="192.0.2.10",
        PC_MAC="aa:bb:cc:dd:ee:ff",
        PI_HOST="192.0.2.20",
        DISPLAYS="main=dev-main,second=dev-second",
        SUNSHINE_USER="user",
        SUNSHINE_PASS="pass",
        API_TOKEN=TOKEN,
    )
    cfg.update(overrides)
    return cfg


def reset_jobs():
    jobs._cache.clear()
    jobs.update(phase="idle", error="", warning="", source="", obs_active=False, intent="down", request={})
    jobs.clear_cancel()
    if jobs._job_lock.locked():
        jobs._job_lock.release()


def wait_idle(timeout=3):
    deadline = time.time() + timeout
    while jobs.busy() and time.time() < deadline:
        real_sleep(0.005)
    return not jobs.busy()


class JobsCase(unittest.TestCase):
    def setUp(self):
        reset_jobs()
        self.addCleanup(reset_jobs)


def decode_frame(read):
    first, second = read(2)
    size = second & 0x7F
    if size == 126:
        size = int.from_bytes(read(2), "big")
    elif size == 127:
        size = int.from_bytes(read(8), "big")
    mask = read(4) if second & 0x80 else b""
    payload = read(size)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return {"fin": bool(first & 0x80), "opcode": first & 0x0F, "masked": bool(mask), "payload": payload}


def decode_bytes(data):
    stream = io.BytesIO(data)
    frame = decode_frame(stream.read)
    frame["rest"] = stream.read()
    return frame


def server_frame(opcode, payload):
    header = bytearray([0x80 | opcode])
    if len(payload) < 126:
        header.append(len(payload))
    else:
        header.append(126)
        header += len(payload).to_bytes(2, "big")
    return bytes(header) + payload


def expected_auth(password, salt, challenge):
    secret = base64.b64encode(hashlib.new("sha256", password.encode() + salt.encode()).digest())
    return base64.b64encode(hashlib.new("sha256", secret + challenge.encode()).digest()).decode()


class FakeObsServer:
    SALT = "test-salt"
    CHALLENGE = "test-challenge"

    def __init__(self, password="", failures=None, ping_before_response=False, handshake_status="101 Switching Protocols"):
        self.password = password
        self.failures = failures or {}
        self.responses = {}
        self.ping_before_response = ping_before_response
        self.handshake_status = handshake_status
        self.requests = []
        self.pongs = []
        self.identify = None
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(5)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.listener.close()

    def serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            try:
                self.handle(conn)
            except (OSError, EOFError):
                pass
            finally:
                conn.close()

    @staticmethod
    def reader(conn):
        def read(count):
            data = b""
            while len(data) < count:
                chunk = conn.recv(count - len(data))
                if not chunk:
                    raise EOFError
                data += chunk
            return data

        return read

    def handle(self, conn):
        read = self.reader(conn)
        head = b""
        while b"\r\n\r\n" not in head:
            head += read(1)
        conn.sendall(f"HTTP/1.1 {self.handshake_status}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n".encode())
        if not self.handshake_status.startswith("101"):
            return
        hello = {"obsWebSocketVersion": "5.0.0", "rpcVersion": 1}
        if self.password:
            hello["authentication"] = {"salt": self.SALT, "challenge": self.CHALLENGE}
        self.send_json(conn, {"op": 0, "d": hello})
        frame = decode_frame(read)
        self.identify = json.loads(frame["payload"])["d"]
        if self.password and self.identify.get("authentication") != expected_auth(self.password, self.SALT, self.CHALLENGE):
            conn.sendall(server_frame(8, (4009).to_bytes(2, "big") + b"Authentication failed."))
            return
        self.send_json(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})
        while True:
            frame = decode_frame(read)
            if frame["opcode"] == 10:
                self.pongs.append(frame["payload"])
            elif frame["opcode"] == 8:
                return
            elif frame["opcode"] == 1:
                self.answer(conn, json.loads(frame["payload"]))

    def answer(self, conn, message):
        data = message["d"]
        kind = data["requestType"]
        self.requests.append((kind, data["requestData"]))
        if self.ping_before_response:
            conn.sendall(server_frame(9, b"hb"))
        if kind in self.failures:
            status = {"result": False, "code": 600, "comment": self.failures[kind]}
            body = {"requestType": kind, "requestId": data["requestId"], "requestStatus": status}
        else:
            status = {"result": True, "code": 100}
            body = {
                "requestType": kind,
                "requestId": data["requestId"],
                "requestStatus": status,
                "responseData": self.responses.get(kind, {}),
            }
        self.send_json(conn, {"op": 7, "d": body})

    @staticmethod
    def send_json(conn, message):
        conn.sendall(server_frame(1, json.dumps(message).encode()))


def start_patch(case, target, name, **kwargs):
    patcher = mock.patch.object(target, name, **kwargs)
    mocked = patcher.start()
    case.addCleanup(patcher.stop)
    return mocked


class TempDirCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text)
        return path
