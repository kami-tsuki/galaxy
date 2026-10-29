import base64
import hashlib
import json
import os
import socket
import time
from pathlib import Path

from .log import log

CLOSE_REASONS = {4009: "authentication failed, check OBS_PASS", 4008: "OBS rejected the identify message"}


def previous_profile_file():
    return Path(f"/run/user/{os.getuid()}/galaxy-obs-previous")


def auth_response(password, salt, challenge):
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def encode_frame(opcode, payload, mask):
    header = bytearray([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header.append(0x80 | size)
    elif size < 65536:
        header.append(0x80 | 126)
        header += size.to_bytes(2, "big")
    else:
        header.append(0x80 | 127)
        header += size.to_bytes(8, "big")
    return bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


class Ws:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=8)
        self.buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            "GET / HTTP/1.1",
            f"Host: {host}:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
            "Sec-WebSocket-Protocol: obswebsocket.json",
            "",
            "",
        ]
        try:
            self.sock.sendall("\r\n".join(lines).encode())
            while b"\r\n\r\n" not in self.buf:
                self.buf += self.chunk()
            head, self.buf = self.buf.split(b"\r\n\r\n", 1)
            if b" 101 " not in head.split(b"\r\n")[0]:
                raise RuntimeError("OBS websocket handshake failed")
        except BaseException:
            self.sock.close()
            raise

    def chunk(self):
        data = self.sock.recv(4096)
        if not data:
            raise RuntimeError("OBS closed the connection")
        return data

    def read(self, count):
        while len(self.buf) < count:
            self.buf += self.chunk()
        data, self.buf = self.buf[:count], self.buf[count:]
        return data

    def send_frame(self, opcode, payload):
        self.sock.sendall(encode_frame(opcode, payload, os.urandom(4)))

    def send(self, message):
        self.send_frame(1, json.dumps(message).encode())

    def recv(self):
        while True:
            first, second = self.read(2)
            size = second & 0x7F
            if size == 126:
                size = int.from_bytes(self.read(2), "big")
            elif size == 127:
                size = int.from_bytes(self.read(8), "big")
            payload = self.read(size)
            opcode = first & 0x0F
            if opcode == 1:
                return json.loads(payload)
            if opcode == 9:
                self.send_frame(10, payload)
            elif opcode == 8:
                code = int.from_bytes(payload[:2], "big") if len(payload) >= 2 else 0
                raise RuntimeError(f"OBS closed the connection ({CLOSE_REASONS.get(code, f'code {code}')})")

    def close(self):
        self.sock.close()


class Client:
    def __init__(self, cfg):
        self.ws = Ws(cfg["PC_HOST"], int(cfg["OBS_PORT"]))
        try:
            hello = self.ws.recv()["d"]
            identify = {"rpcVersion": 1}
            auth = hello.get("authentication")
            if auth:
                identify["authentication"] = auth_response(cfg["OBS_PASS"], auth["salt"], auth["challenge"])
            self.ws.send({"op": 1, "d": identify})
            while self.ws.recv()["op"] != 2:
                pass
        except BaseException:
            self.ws.close()
            raise

    def call(self, request_type, data=None):
        self.ws.send({"op": 6, "d": {"requestType": request_type, "requestId": "galaxy", "requestData": data or {}}})
        while True:
            try:
                message = self.ws.recv()
            except TimeoutError:
                raise RuntimeError("OBS did not answer, close any dialog that is open in OBS on the PC")
            if message["op"] == 7:
                break
        status = message["d"]["requestStatus"]
        if not status["result"]:
            raise RuntimeError(status.get("comment") or f"OBS request {request_type} failed")
        return message["d"].get("responseData", {})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.ws.close()


def wait_ready(cfg, seconds=30):
    deadline = time.time() + seconds
    while True:
        try:
            with Client(cfg):
                return
        except OSError:
            if time.time() > deadline:
                raise RuntimeError("OBS is not running on the PC, or its WebSocket server is off")
            time.sleep(3)


def wait_stream(client, wanted, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if client.call("GetStreamStatus")["outputActive"] == wanted:
            return True
        time.sleep(1)
    return False


def profile_parameters(cfg):
    return (
        ("Output", "Mode", "Simple"),
        ("SimpleOutput", "VBitrate", cfg["OBS_BITRATE"]),
        ("SimpleOutput", "ABitrate", "160"),
    )


def begin(cfg, url):
    wait_ready(cfg)
    name = cfg["OBS_PROFILE"]
    with Client(cfg) as client:
        if client.call("GetStreamStatus")["outputActive"]:
            raise RuntimeError("OBS is already streaming, stop that stream first")
        info = client.call("GetProfileList")
        if info["currentProfileName"] != name:
            previous_profile_file().write_text(info["currentProfileName"])
            client.call("SetCurrentProfile" if name in info["profiles"] else "CreateProfile", {"profileName": name})
        fps = int(cfg["OBS_FPS"])
        client.call(
            "SetVideoSettings",
            {
                "baseWidth": 1920,
                "baseHeight": 1080,
                "outputWidth": 1920,
                "outputHeight": 1080,
                "fpsNumerator": fps,
                "fpsDenominator": 1,
            },
        )
        for category, parameter, value in profile_parameters(cfg):
            client.call(
                "SetProfileParameter",
                {"parameterCategory": category, "parameterName": parameter, "parameterValue": value},
            )
        client.call(
            "SetStreamServiceSettings",
            {
                "streamServiceType": "rtmp_custom",
                "streamServiceSettings": {"server": url, "key": "", "use_auth": False},
            },
        )
        client.call("StartStream")
        if not wait_stream(client, True, 20):
            raise RuntimeError("OBS did not start streaming to the Pi")


def end(cfg):
    name = cfg["OBS_PROFILE"]
    try:
        client = Client(cfg)
    except (OSError, RuntimeError) as error:
        log(f"obs end skipped: {error}")
        return
    with client:
        info = client.call("GetProfileList")
        if info["currentProfileName"] != name:
            return
        if client.call("GetStreamStatus")["outputActive"]:
            client.call("StopStream")
            wait_stream(client, False, 10)
        path = previous_profile_file()
        if path.is_file():
            previous = path.read_text().strip()
            if previous in info["profiles"]:
                client.call("SetCurrentProfile", {"profileName": previous})
            path.unlink()
