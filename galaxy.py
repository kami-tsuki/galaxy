#!/usr/bin/env python3
import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
ENV_FILE = Path("/etc/galaxy/galaxy.env")
ENV_FILES = (ENV_FILE, ROOT / ".env")
STREAM_UNIT = "galaxy-stream.service"
DEFAULTS = {
    "PC_HOST": "",
    "PC_MAC": "",
    "PC_BROADCAST": "255.255.255.255",
    "PC_SSH": "",
    "SUNSHINE_APP": "Desktop",
    "APPS": "Desktop,Steam Big Picture",
    "SUNSHINE_PORT": "47989",
    "SUNSHINE_UI_PORT": "47990",
    "SUNSHINE_USER": "",
    "SUNSHINE_PASS": "",
    "DISPLAYS": "",
    "DISPLAY_RES": "main=3840x1080,tv=1920x1080,obs=1920x1080",
    "OBS_PORT": "4455",
    "OBS_PASS": "",
    "OBS_MONITOR": "1",
    "BOOT_WAIT": "120",
    "TV_CEC": "true",
    "TV_OFF_ON_STOP": "true",
    "CEC_DEVICE": "/dev/cec1",
    "API_BIND": "0.0.0.0",
    "API_PORT": "8787",
    "API_TOKEN": "",
}
SECRET_KEYS = ("SUNSHINE_USER", "SUNSHINE_PASS", "OBS_PASS", "API_TOKEN")
PC_COMMANDS = {
    "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    "shutdown": "shutdown /s /t 0",
    "restart": "shutdown /r /t 0",
}
AUDIO_MODES = {
    "both": ("--audio-on-host", "alsa"),
    "tv": ("--no-audio-on-host", "alsa"),
    "pc": ("--audio-on-host", "dummy"),
}
MAX_BODY = 4096
RESOLUTION = re.compile(r"^\d{3,5}x\d{3,5}$")
MAC = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")

state = {"phase": "idle", "error": "", "warning": "", "display": "", "since": time.time()}
state_lock = threading.Lock()
job_lock = threading.Lock()
cache = {}


class Busy(RuntimeError):
    pass


def load_config():
    cfg = dict(DEFAULTS)
    for path in ENV_FILES:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    for key in DEFAULTS:
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


def flag(cfg, key):
    return cfg[key].lower() in ("1", "true", "yes", "on")


def pairs(text):
    result = {}
    for item in text.split(","):
        if "=" in item:
            name, value = item.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def set_state(**values):
    with state_lock:
        state.update(values, since=time.time())


def set_phase(phase, error=""):
    set_state(phase=phase, error=error)


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def cached(key, ttl, producer):
    now = time.time()
    entry = cache.get(key)
    if entry and now - entry[0] < ttl:
        return entry[1]
    value = producer()
    cache[key] = (now, value)
    return value


def exclusive(function, *args):
    if not job_lock.acquire(blocking=False):
        raise Busy("another action is running")
    try:
        return function(*args)
    finally:
        job_lock.release()


def submit(function, *args, report=True):
    if not job_lock.acquire(blocking=False):
        raise Busy("another action is running")

    def target():
        try:
            function(*args)
        except Exception as error:
            log(f"{function.__name__} failed: {error}")
            if report:
                set_phase("error", str(error))
        finally:
            job_lock.release()

    threading.Thread(target=target, daemon=True).start()


def sunshine_up(cfg, timeout=2):
    if not cfg["PC_HOST"]:
        return False
    try:
        with socket.create_connection((cfg["PC_HOST"], int(cfg["SUNSHINE_PORT"])), timeout=timeout):
            return True
    except OSError:
        return False


def wake(cfg):
    if not MAC.match(cfg["PC_MAC"]):
        raise RuntimeError("PC_MAC is not a valid MAC address")
    mac = bytes.fromhex(cfg["PC_MAC"].replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac * 16
    targets = {cfg["PC_BROADCAST"], "255.255.255.255"}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in targets:
            for port in (7, 9):
                sock.sendto(packet, (target, port))


def cec(cfg, command):
    try:
        result = subprocess.run(
            ["cec-client", "-s", "-d", "1", cfg["CEC_DEVICE"]],
            input=command.encode(),
            capture_output=True,
            timeout=25,
        )
        return result.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError) as error:
        log(f"cec failed: {error}")
        return ""


def tv_power(cfg):
    for line in cec(cfg, "pow 0").splitlines():
        if line.startswith("power status:"):
            text = line.split(":", 1)[1].strip()
            if text == "on" or text.endswith("to on"):
                return "on"
            if text == "standby" or text.endswith("to standby"):
                return "standby"
    return "unknown"


def tv(cfg, on):
    if not flag(cfg, "TV_CEC"):
        return True
    wanted = "on" if on else "standby"
    for _ in range(3):
        if tv_power(cfg) == wanted:
            return True
        cec(cfg, "on 0" if on else "standby 0")
        time.sleep(6)
    return tv_power(cfg) == wanted


def systemctl(action):
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    return subprocess.run(prefix + ["systemctl", action, STREAM_UNIT], capture_output=True, text=True)


def stream_active():
    return subprocess.run(["systemctl", "is-active", "--quiet", STREAM_UNIT]).returncode == 0


def pc_power(cfg, action):
    if not cfg["PC_SSH"]:
        raise RuntimeError("PC_SSH is not configured")
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", cfg["PC_SSH"], PC_COMMANDS[action]],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 255:
        raise RuntimeError(result.stderr.strip() or "PC is not reachable over SSH")


def displays(cfg):
    result = pairs(cfg["DISPLAYS"])
    if cfg["OBS_PASS"] and "tv" in result:
        result["obs"] = result["tv"]
    return result


def apps(cfg):
    return [item.strip() for item in cfg["APPS"].split(",") if item.strip()]


class Ws:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=8)
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
        self.sock.sendall("\r\n".join(lines).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("OBS closed the connection")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("OBS websocket handshake failed")

    def read(self, count):
        while len(self.buf) < count:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("OBS closed the connection")
            self.buf += chunk
        data, self.buf = self.buf[:count], self.buf[count:]
        return data

    def frame(self, opcode, payload):
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
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, message):
        self.frame(1, json.dumps(message).encode())

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
                self.frame(10, payload)
            elif opcode == 8:
                code = int.from_bytes(payload[:2], "big") if len(payload) >= 2 else 0
                reasons = {4009: "authentication failed, check OBS_PASS", 4008: "OBS rejected the identify message"}
                raise RuntimeError(f"OBS closed the connection ({reasons.get(code, f'code {code}')})")


def obs_request(cfg, request_type, data=None):
    ws = Ws(cfg["PC_HOST"], int(cfg["OBS_PORT"]))
    try:
        hello = ws.recv()["d"]
        identify = {"rpcVersion": 1}
        auth = hello.get("authentication")
        if auth:
            secret = base64.b64encode(hashlib.sha256((cfg["OBS_PASS"] + auth["salt"]).encode()).digest()).decode()
            identify["authentication"] = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()
            ).decode()
        ws.send({"op": 1, "d": identify})
        while ws.recv()["op"] != 2:
            pass
        ws.send({"op": 6, "d": {"requestType": request_type, "requestId": "galaxy", "requestData": data or {}}})
        while True:
            message = ws.recv()
            if message["op"] == 7:
                break
        status = message["d"]["requestStatus"]
        if not status["result"]:
            raise RuntimeError(status.get("comment", f"OBS request {request_type} failed"))
        return message["d"].get("responseData", {})
    finally:
        ws.sock.close()


def obs_wait(cfg, seconds=30):
    deadline = time.time() + seconds
    while True:
        try:
            obs_request(cfg, "GetVersion")
            return
        except OSError:
            if time.time() > deadline:
                raise RuntimeError("OBS is not running or its WebSocket server is off")
            time.sleep(3)


def obs_show(cfg):
    obs_wait(cfg)
    with state_lock:
        camera = state.get("obs_camera", False)
        projector = state.get("obs_projector", False)
    if not camera:
        try:
            obs_request(cfg, "StartVirtualCam")
        except RuntimeError as error:
            log(f"virtual cam: {error}")
        set_state(obs_camera=True)
    if not projector:
        obs_request(
            cfg,
            "OpenVideoMixProjector",
            {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM", "monitorIndex": int(cfg["OBS_MONITOR"])},
        )
        set_state(obs_projector=True)


def obs_leave(cfg):
    with state_lock:
        camera = state.get("obs_camera", False)
    set_state(obs_projector=False)
    if camera:
        try:
            obs_request(cfg, "StopVirtualCam")
        except (OSError, RuntimeError) as error:
            log(f"virtual cam stop: {error}")
        set_state(obs_camera=False)


def sunshine_api(cfg, method, path, body=None):
    if not cfg["SUNSHINE_USER"]:
        raise RuntimeError("SUNSHINE_USER is not configured, run: galaxy.py set SUNSHINE_USER")
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    credentials = base64.b64encode(f"{cfg['SUNSHINE_USER']}:{cfg['SUNSHINE_PASS']}".encode()).decode()
    request = urllib.request.Request(
        f"https://{cfg['PC_HOST']}:{cfg['SUNSHINE_UI_PORT']}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, context=context, timeout=15) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Sunshine answered {error.code}, check SUNSHINE_USER and SUNSHINE_PASS")
    return json.loads(raw) if raw else {}


def sunshine_config(cfg):
    data = sunshine_api(cfg, "GET", "/api/config")
    return {key: value for key, value in data.items() if key not in ("platform", "version", "status")}


def current_output(cfg):
    def read():
        try:
            return sunshine_config(cfg).get("output_name", "")
        except (OSError, RuntimeError, ValueError):
            return None

    return cached("output", 8, read)


def display_name(cfg, online):
    known = displays(cfg)
    with state_lock:
        chosen = state["display"]
    output = current_output(cfg) if online else None
    if output is None:
        return chosen
    if chosen and known.get(chosen) == output:
        return chosen
    for name, ident in known.items():
        if ident == output and name != "obs":
            return name
    return ""


def wait_sunshine_restart(cfg):
    deadline = time.time() + 20
    while time.time() < deadline and sunshine_up(cfg, 1):
        time.sleep(1)
    deadline = time.time() + 60
    while time.time() < deadline:
        if sunshine_up(cfg, 1):
            try:
                sunshine_config(cfg)
                return
            except (OSError, RuntimeError, ValueError):
                pass
        time.sleep(2)
    raise RuntimeError("Sunshine did not come back after restart")


def select_display(cfg, name):
    known = displays(cfg)
    if name not in known:
        raise RuntimeError(f"unknown display '{name}', choose from: {', '.join(known) or 'none configured'}")
    if not sunshine_up(cfg):
        raise RuntimeError("PC is not online")
    if stream_active():
        systemctl("stop")
    if sunshine_config(cfg).get("output_name") != known[name]:
        settings = sunshine_config(cfg)
        settings["output_name"] = known[name]
        sunshine_api(cfg, "POST", "/api/config", settings)
        try:
            sunshine_api(cfg, "POST", "/api/restart", {})
        except OSError:
            pass
        wait_sunshine_restart(cfg)
        cache.pop("output", None)
    if name == "obs":
        obs_show(cfg)
    else:
        obs_leave(cfg)
    set_state(display=name)


def session_file():
    return Path(f"/run/user/{os.getuid()}/galaxy-session.env")


def read_session():
    result = {}
    try:
        for line in session_file().read_text().splitlines():
            key, _, value = line.partition("=")
            result[key] = value.strip('"')
    except OSError:
        pass
    audio = ""
    for mode, (flags, driver) in AUDIO_MODES.items():
        if result.get("AUDIO_FLAGS") == flags and result.get("AUDIO_DRIVER") == driver:
            audio = mode
    return {"app": result.get("SUNSHINE_APP", ""), "audio": audio}


def write_session(cfg, app, audio, resolution):
    if audio not in AUDIO_MODES:
        raise RuntimeError(f"unknown audio mode '{audio}', choose from: {', '.join(AUDIO_MODES)}")
    if app not in apps(cfg) and app != cfg["SUNSHINE_APP"]:
        raise RuntimeError(f"unknown app '{app}', choose from: {', '.join(apps(cfg))}")
    if not RESOLUTION.match(resolution):
        raise RuntimeError(f"invalid resolution '{resolution}'")
    if any(char in app for char in '"\\$\n') or app.startswith("-"):
        raise RuntimeError("invalid app name")
    flags, driver = AUDIO_MODES[audio]
    path = session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'SUNSHINE_APP="{app}"\nAUDIO_FLAGS="{flags}"\nAUDIO_DRIVER={driver}\nRESOLUTION_FLAGS="--resolution {resolution}"\n'
    )


def confirm_stream(seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not stream_active():
            raise RuntimeError("Moonlight exited right after starting, check: journalctl -u galaxy-stream")
        time.sleep(1)


def validate_options(cfg, display, audio, app):
    if display and display not in displays(cfg):
        raise ValueError(f"unknown display '{display}', choose from: {', '.join(displays(cfg)) or 'none configured'}")
    if audio and audio not in AUDIO_MODES:
        raise ValueError(f"unknown audio mode '{audio}', choose from: {', '.join(AUDIO_MODES)}")
    if app and app not in apps(cfg):
        raise ValueError(f"unknown app '{app}', choose from: {', '.join(apps(cfg))}")


def start(cfg, display="", audio="", app="", fresh=False):
    if not cfg["PC_HOST"]:
        raise RuntimeError("PC_HOST is not configured")
    validate_options(cfg, display, audio, app)
    fresh = fresh or bool(display or audio or app)
    if stream_active():
        if not fresh:
            set_phase("streaming")
            return
        systemctl("stop")
    previous = read_session()
    audio = audio or previous["audio"] or "both"
    app = app or previous["app"] or cfg["SUNSHINE_APP"]
    set_state(warning="")
    set_phase("tv")
    outcome = {}
    tv_thread = threading.Thread(target=lambda: outcome.update(ok=tv(cfg, True)), daemon=True)
    tv_thread.start()
    if not sunshine_up(cfg):
        set_phase("waking")
        deadline = time.time() + int(cfg["BOOT_WAIT"])
        while time.time() < deadline and not sunshine_up(cfg):
            wake(cfg)
            time.sleep(5)
        if not sunshine_up(cfg):
            raise RuntimeError("PC did not come up")
    if display:
        set_phase("display")
        select_display(cfg, display)
    chosen = display or display_name(cfg, True) or "tv"
    resolution = pairs(cfg["DISPLAY_RES"]).get(chosen, "1920x1080")
    write_session(cfg, app, audio, resolution)
    tv_thread.join(timeout=120)
    if not outcome.get("ok", True):
        set_state(warning="The TV did not confirm that it is on")
    set_phase("connecting")
    result = systemctl("start")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "stream unit failed to start")
    confirm_stream()
    set_phase("streaming")


def stop(cfg):
    set_phase("stopping")
    systemctl("stop")
    if flag(cfg, "TV_OFF_ON_STOP"):
        tv(cfg, False)
    set_phase("idle")


def status(cfg):
    active = stream_active()
    with state_lock:
        snapshot = dict(state)
    phase = snapshot["phase"]
    error = snapshot["error"]
    if phase == "streaming" and not active and not job_lock.locked():
        phase, error = "error", "The stream ended unexpectedly"
        set_phase(phase, error)
    elif active and phase in ("idle", "error") and not job_lock.locked():
        phase, error = "streaming", ""
    session = read_session()
    online = cached("online", 3, lambda: sunshine_up(cfg))
    return {
        "phase": phase,
        "error": error,
        "warning": snapshot["warning"],
        "stream": active,
        "busy": job_lock.locked(),
        "pc_online": online,
        "pc_host": cfg["PC_HOST"],
        "app": session["app"] or cfg["SUNSHINE_APP"],
        "apps": apps(cfg),
        "audio": session["audio"] or "both",
        "audio_modes": list(AUDIO_MODES),
        "display": display_name(cfg, online) if online else snapshot["display"],
        "displays": list(displays(cfg)),
    }


def set_env(key, value):
    if key not in DEFAULTS:
        raise RuntimeError(f"unknown setting '{key}'")
    if "\n" in value:
        raise RuntimeError("value must be one line")
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.is_file() else []
    out, found = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            line, found = f"{key}={value}", True
        out.append(line)
    if not found:
        out.append(f"{key}={value}")
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    subprocess.run(prefix + ["tee", str(ENV_FILE)], input=("\n".join(out) + "\n").encode(), stdout=subprocess.DEVNULL, check=True)


def make_handler(cfg):
    token = cfg["API_TOKEN"].encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log(f"{self.address_string()} {fmt % args}")

        def reply(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            header = self.headers.get("Authorization", "")
            supplied = header[7:].encode() if header.lower().startswith("bearer ") else b""
            if bool(token) and hmac.compare_digest(supplied, token):
                return True
            time.sleep(0.3)
            self.reply(401, {"error": "unauthorized"})
            return False

        def body(self):
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ValueError("bad Content-Length")
            if size > MAX_BODY:
                raise ValueError("body too large")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("body must be a JSON object")
            return data

        def do_GET(self):
            route = urlparse(self.path).path
            if route == "/":
                return self.reply(200, (ROOT / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
            if not self.authorized():
                return
            if route == "/v1/status":
                return self.reply(200, status(cfg))
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return
            parsed = urlparse(self.path)
            route = parsed.path
            try:
                if route == "/v1/connect":
                    options = self.body()
                elif route == "/v1/start":
                    options = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                else:
                    options = {}
                if route in ("/v1/connect", "/v1/start"):
                    for key in ("display", "audio", "app"):
                        if not isinstance(options.get(key, ""), str):
                            raise ValueError(f"{key} must be a string")
                    display, audio, app = options.get("display", ""), options.get("audio", ""), options.get("app", "")
                    validate_options(cfg, display, audio, app)
                    submit(start, cfg, display, audio, app, route == "/v1/connect")
                elif route.startswith("/v1/display/"):
                    name = route[len("/v1/display/"):]
                    if name not in displays(cfg):
                        raise ValueError(f"unknown display '{name}'")
                    submit(select_display, cfg, name)
                elif route == "/v1/stop":
                    submit(stop, cfg)
                elif route == "/v1/wake":
                    wake(cfg)
                elif route in ("/v1/tv/on", "/v1/tv/off"):
                    submit(tv, cfg, route.endswith("on"), report=False)
                elif route.startswith("/v1/") and route[4:] in PC_COMMANDS:
                    pc_power(cfg, route[4:])
                else:
                    return self.reply(404, {"error": "not found"})
            except Busy as error:
                return self.reply(409, {"error": str(error)})
            except (ValueError, KeyError) as error:
                return self.reply(400, {"error": str(error)})
            except Exception as error:
                return self.reply(502, {"error": str(error)})
            self.reply(202, {"accepted": route})

    return Handler


def serve(cfg):
    if not cfg["API_TOKEN"]:
        sys.exit("API_TOKEN is not set")
    server = ThreadingHTTPServer((cfg["API_BIND"], int(cfg["API_PORT"])), make_handler(cfg))
    log(f"listening on {cfg['API_BIND']}:{cfg['API_PORT']}")
    server.serve_forever()


def pair(cfg):
    subprocess.run(
        ["flatpak", "run", "--env=QT_QPA_PLATFORM=offscreen", "com.moonlight_stream.Moonlight", "pair", cfg["PC_HOST"]]
    )


def main():
    parser = argparse.ArgumentParser(prog="galaxy")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "stop", "status", "wake", "pair", *PC_COMMANDS):
        sub.add_parser(name)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--display", default="")
    start_parser.add_argument("--audio", default="", choices=("", *AUDIO_MODES))
    start_parser.add_argument("--app", default="")
    display_parser = sub.add_parser("display")
    display_parser.add_argument("name", nargs="?")
    tv_parser = sub.add_parser("tv")
    tv_parser.add_argument("state", choices=("on", "off"))
    set_parser = sub.add_parser("set")
    set_parser.add_argument("key", choices=SECRET_KEYS)
    args = parser.parse_args()
    cfg = load_config()
    try:
        if args.command == "serve":
            serve(cfg)
        elif args.command == "start":
            exclusive(start, cfg, args.display, args.audio, args.app)
        elif args.command == "stop":
            exclusive(stop, cfg)
        elif args.command == "status":
            print(json.dumps(status(cfg), indent=2))
        elif args.command == "wake":
            wake(cfg)
        elif args.command == "pair":
            pair(cfg)
        elif args.command == "display":
            if args.name:
                exclusive(select_display, cfg, args.name)
            else:
                print(json.dumps(displays(cfg), indent=2))
        elif args.command == "tv":
            exclusive(tv, cfg, args.state == "on")
        elif args.command == "set":
            set_env(args.key, getpass.getpass(f"{args.key}: "))
            print("saved")
        else:
            pc_power(cfg, args.command)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"galaxy: {error}")


if __name__ == "__main__":
    main()
