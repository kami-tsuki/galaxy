#!/usr/bin/env python3
import argparse
import base64
import hashlib
import hmac
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILES = (Path("/etc/galaxy/galaxy.env"), ROOT / ".env")
STREAM_UNIT = "galaxy-stream.service"
DEFAULTS = {
    "PC_HOST": "",
    "PC_MAC": "",
    "PC_BROADCAST": "255.255.255.255",
    "PC_SSH": "",
    "SUNSHINE_APP": "Desktop",
    "SUNSHINE_PORT": "47989",
    "SUNSHINE_UI_PORT": "47990",
    "SUNSHINE_USER": "",
    "SUNSHINE_PASS": "",
    "DISPLAYS": "",
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
PC_COMMANDS = {
    "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    "shutdown": "shutdown /s /t 0",
    "restart": "shutdown /r /t 0",
    "lock": "rundll32.exe user32.dll,LockWorkStation",
}

state = {"phase": "idle", "error": "", "since": time.time()}
state_lock = threading.Lock()
job_lock = threading.Lock()


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


def set_phase(phase, error=""):
    with state_lock:
        state.update(phase=phase, error=error, since=time.time())


def log(message):
    print(time.strftime("%H:%M:%S"), message, flush=True)


def sunshine_up(cfg, timeout=2):
    try:
        with socket.create_connection((cfg["PC_HOST"], int(cfg["SUNSHINE_PORT"])), timeout=timeout):
            return True
    except OSError:
        return False


def wake(cfg):
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
            return line.split(":", 1)[1].strip()
    return "unknown"


def tv(cfg, on):
    if not flag(cfg, "TV_CEC"):
        return
    wanted = "on" if on else "standby"
    for _ in range(4):
        if tv_power(cfg) == wanted:
            return
        cec(cfg, "on 0" if on else "standby 0")
        time.sleep(6)


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
    if result.returncode not in (0, 255) and result.stderr.strip():
        raise RuntimeError(result.stderr.strip())


def displays(cfg):
    result = {}
    for item in cfg["DISPLAYS"].split(","):
        if "=" in item:
            name, ident = item.split("=", 1)
            result[name.strip()] = ident.strip()
    if cfg["OBS_PASS"] and "tv" in result:
        result["obs"] = result["tv"]
    return result


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

    def send(self, message):
        payload = json.dumps(message).encode()
        header = bytearray([0x81])
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
            if opcode == 8:
                code = int.from_bytes(payload[:2], "big") if len(payload) >= 2 else 0
                reason = {4009: "authentication failed, check OBS_PASS", 4008: "OBS rejected the identify message"}.get(code, f"code {code}")
                raise RuntimeError(f"OBS closed the connection ({reason})")


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
            raise RuntimeError(status.get("comment", "OBS request failed"))
        return message["d"].get("responseData", {})
    finally:
        ws.sock.close()


def obs_show(cfg):
    try:
        obs_request(cfg, "StartVirtualCam")
    except RuntimeError as error:
        log(f"virtual cam: {error}")
    obs_request(
        cfg,
        "OpenVideoMixProjector",
        {"videoMixType": "OBS_WEBSOCKET_VIDEO_MIX_TYPE_PROGRAM", "monitorIndex": int(cfg["OBS_MONITOR"])},
    )


def sunshine_api(cfg, method, path, body=None):
    if not cfg["SUNSHINE_USER"]:
        raise RuntimeError("SUNSHINE_USER is not configured")
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
    with urllib.request.urlopen(request, context=context, timeout=15) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def select_display(cfg, name):
    known = displays(cfg)
    if name not in known:
        raise RuntimeError(f"unknown display '{name}', choose from: {', '.join(known) or 'none configured'}")
    if stream_active():
        systemctl("stop")
    sunshine_api(cfg, "POST", "/api/config", {"output_name": known[name]})
    try:
        sunshine_api(cfg, "POST", "/api/restart", {})
    except OSError:
        pass
    time.sleep(3)
    deadline = time.time() + 40
    while time.time() < deadline and not sunshine_up(cfg):
        time.sleep(2)
    if not sunshine_up(cfg):
        raise RuntimeError("Sunshine did not come back after restart")
    if name == "obs":
        obs_show(cfg)
    with state_lock:
        state["display"] = name


def start(cfg, display=""):
    if not cfg["PC_HOST"]:
        raise RuntimeError("PC_HOST is not configured")
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("another action is running")
    try:
        if display and not stream_active():
            set_phase("display")
            select_display(cfg, display)
        if stream_active():
            set_phase("streaming")
            return
        set_phase("tv")
        tv(cfg, True)
        if not sunshine_up(cfg):
            set_phase("waking")
            deadline = time.time() + int(cfg["BOOT_WAIT"])
            while time.time() < deadline and not sunshine_up(cfg):
                wake(cfg)
                time.sleep(5)
            if not sunshine_up(cfg):
                raise RuntimeError("PC did not come up")
        set_phase("connecting")
        result = systemctl("start")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "stream unit failed to start")
        set_phase("streaming")
    except Exception as error:
        set_phase("error", str(error))
        raise
    finally:
        job_lock.release()


def stop(cfg):
    if not job_lock.acquire(blocking=False):
        raise RuntimeError("another action is running")
    try:
        set_phase("stopping")
        systemctl("stop")
        if flag(cfg, "TV_OFF_ON_STOP"):
            tv(cfg, False)
        set_phase("idle")
    except Exception as error:
        set_phase("error", str(error))
        raise
    finally:
        job_lock.release()


def status(cfg):
    active = stream_active()
    with state_lock:
        snapshot = dict(state)
    if snapshot["phase"] == "streaming" and not active:
        snapshot["phase"] = "idle"
    if active and snapshot["phase"] == "idle":
        snapshot["phase"] = "streaming"
    return {
        "phase": snapshot["phase"],
        "error": snapshot["error"],
        "stream": active,
        "pc_online": sunshine_up(cfg) if cfg["PC_HOST"] else False,
        "pc_host": cfg["PC_HOST"],
        "app": cfg["SUNSHINE_APP"],
        "display": snapshot.get("display", ""),
        "displays": list(displays(cfg)),
        "busy": job_lock.locked(),
    }


def run_async(function, *args):
    def target():
        try:
            function(*args)
        except Exception as error:
            log(f"{function.__name__} failed: {error}")

    threading.Thread(target=target, daemon=True).start()


PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Galaxy</title>
<style>
:root{color-scheme:dark light;font-family:system-ui,sans-serif}
body{margin:0;display:grid;place-items:center;min-height:100vh;background:#0e1020;color:#e8e8f0}
main{width:min(92vw,420px);display:grid;gap:14px}
h1{margin:0;font-size:1.4rem}
#s{padding:12px 14px;border-radius:10px;background:#1a1d36}
button{padding:14px;border:0;border-radius:10px;background:#4b5cff;color:#fff;font-size:1rem}
button.alt{background:#2a2e55}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
input{padding:12px;border-radius:10px;border:1px solid #34396b;background:#12142a;color:inherit}
</style>
<main>
<h1>Galaxy</h1>
<div id="s">...</div>
<div class="row"><button onclick="call('start')">Start</button><button class="alt" onclick="call('stop')">Stop</button></div>
<div class="row"><button class="alt" onclick="call('wake')">Wake PC</button><button class="alt" onclick="call('sleep')">Sleep PC</button></div>
<div class="row" id="d"></div>
<div class="row"><button class="alt" onclick="call('tv/on')">TV on</button><button class="alt" onclick="call('tv/off')">TV off</button></div>
<input id="t" type="password" placeholder="API token" onchange="localStorage.setItem('t',this.value)">
</main>
<script>
const t=document.getElementById('t');t.value=localStorage.getItem('t')||'';
const h=()=>({Authorization:'Bearer '+t.value});
async function call(p){await fetch('/v1/'+p,{method:'POST',headers:h()});refresh()}
async function refresh(){try{const r=await fetch('/v1/status',{headers:h()});const j=await r.json();
document.getElementById('s').textContent=r.ok?j.phase+' | PC '+(j.pc_online?'online':'offline')+(j.display?' | '+j.display:'')+(j.error?' | '+j.error:''):'unauthorized';if(r.ok)document.getElementById('d').innerHTML=j.displays.map(n=>`<button class="alt" onclick="call('display/${n}')">${n}</button>`).join('')}catch(e){}}
refresh();setInterval(refresh,3000);
</script>
"""


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

        def query(self):
            from urllib.parse import parse_qs, urlparse

            return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

        def authorized(self):
            header = self.headers.get("Authorization", "")
            supplied = header[7:].encode() if header.startswith("Bearer ") else b""
            return bool(token) and hmac.compare_digest(supplied, token)

        def do_GET(self):
            if self.path == "/":
                return self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
            if not self.authorized():
                return self.reply(401, {"error": "unauthorized"})
            if self.path == "/v1/status":
                return self.reply(200, status(cfg))
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return self.reply(401, {"error": "unauthorized"})
            route = self.path.split("?", 1)[0]
            try:
                if route == "/v1/start":
                    run_async(start, cfg, self.query().get("display", ""))
                elif route.startswith("/v1/display/"):
                    run_async(select_display, cfg, route[len("/v1/display/"):])
                elif route == "/v1/stop":
                    run_async(stop, cfg)
                elif route == "/v1/wake":
                    wake(cfg)
                elif route == "/v1/tv/on":
                    run_async(tv, cfg, True)
                elif route == "/v1/tv/off":
                    run_async(tv, cfg, False)
                elif route.startswith("/v1/") and route[4:] in PC_COMMANDS:
                    pc_power(cfg, route[4:])
                else:
                    return self.reply(404, {"error": "not found"})
            except Exception as error:
                return self.reply(500, {"error": str(error)})
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
    for name in ("serve", "start", "stop", "status", "wake", "pair", *PC_COMMANDS):
        sub.add_parser(name)
    start_parser = sub.choices["start"]
    start_parser.add_argument("--display", default="")
    display_parser = sub.add_parser("display")
    display_parser.add_argument("name", nargs="?")
    tv_parser = sub.add_parser("tv")
    tv_parser.add_argument("state", choices=("on", "off"))
    args = parser.parse_args()
    cfg = load_config()
    try:
        if args.command == "serve":
            serve(cfg)
        elif args.command == "start":
            start(cfg, args.display)
        elif args.command == "display":
            if args.name:
                select_display(cfg, args.name)
            else:
                print(json.dumps(displays(cfg), indent=2))
        elif args.command == "stop":
            stop(cfg)
        elif args.command == "status":
            print(json.dumps(status(cfg), indent=2))
        elif args.command == "wake":
            wake(cfg)
        elif args.command == "pair":
            pair(cfg)
        elif args.command == "tv":
            tv(cfg, args.state == "on")
        else:
            pc_power(cfg, args.command)
    except (RuntimeError, ValueError) as error:
        sys.exit(f"galaxy: {error}")


if __name__ == "__main__":
    main()
