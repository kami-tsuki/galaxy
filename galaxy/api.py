import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import config, jobs, pc, session, tv, watchdog
from .log import log

MAX_BODY = 4096
REQUEST_TIMEOUT = 10
FAILED_AUTH_DELAY = 0.3
INDEX = Path(__file__).resolve().parent / "web" / "index.html"
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
}
POWER_ROUTES = {f"/v1/{action}": action for action in pc.POWER_COMMANDS}


def make_handler(source):
    provider = source if callable(source) else (lambda: source)

    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT

        def log_message(self, fmt, *args):
            log(f"{self.address_string()} {fmt % args}")

        def reply(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, cfg):
            token = cfg["API_TOKEN"].encode()
            header = self.headers.get("Authorization", "")
            supplied = header[7:].encode() if header.lower().startswith("bearer ") else b""
            if len(token) >= config.MIN_TOKEN_LENGTH and hmac.compare_digest(supplied, token):
                return True
            time.sleep(FAILED_AUTH_DELAY)
            self.reply(401, {"error": "unauthorized"})
            return False

        def body(self):
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ValueError("bad Content-Length")
            if size < 0 or size > MAX_BODY:
                raise ValueError("bad body size")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("body must be a JSON object")
            return data

        def do_GET(self):
            route = urlparse(self.path).path
            if route == "/":
                return self.reply(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            cfg = provider()
            if not self.authorized(cfg):
                return
            if route == "/v1/status":
                try:
                    return self.reply(200, session.status(cfg))
                except Exception as error:
                    log(f"status failed: {error}")
                    return self.reply(502, {"error": str(error)})
            self.reply(404, {"error": "not found"})

        def connect(self, cfg):
            options = self.body()
            for key in ("source", "audio", "app"):
                if not isinstance(options.get(key, ""), str):
                    raise ValueError(f"{key} must be a string")
            source, audio, app = (options.get(key, "") for key in ("source", "audio", "app"))
            session.resolve(cfg, source, audio, app)
            jobs.submit(session.connect, cfg, source, audio, app)

        def do_POST(self):
            cfg = provider()
            if not self.authorized(cfg):
                return
            route = urlparse(self.path).path
            done = False
            try:
                if route == "/v1/connect":
                    self.connect(cfg)
                elif route == "/v1/stop":
                    jobs.update(intent="down")
                    jobs.request_cancel()
                    jobs.submit(session.disconnect, cfg, wait=True)
                elif route == "/v1/wake":
                    pc.wake(cfg)
                    done = True
                elif route in ("/v1/tv/on", "/v1/tv/off"):
                    jobs.submit(tv.switch, cfg, route.endswith("on"), report=False)
                elif route in POWER_ROUTES:
                    pc.power(cfg, POWER_ROUTES[route])
                    done = True
                else:
                    return self.reply(404, {"error": "not found"})
            except jobs.Busy as error:
                return self.reply(409, {"error": str(error)})
            except ValueError as error:
                return self.reply(400, {"error": str(error)})
            except Exception as error:
                return self.reply(502, {"error": str(error)})
            self.reply(200 if done else 202, {"accepted": route})

    return Handler


def serve(provider):
    cfg = provider()
    if len(cfg["API_TOKEN"]) < config.MIN_TOKEN_LENGTH:
        raise SystemExit(f"API_TOKEN must be at least {config.MIN_TOKEN_LENGTH} characters, run: python3 -m galaxy set API_TOKEN")
    server = ThreadingHTTPServer((cfg["API_BIND"], int(cfg["API_PORT"])), make_handler(provider))
    if watchdog.enabled(cfg):
        watchdog.start(provider)
    log(f"listening on {cfg['API_BIND']}:{cfg['API_PORT']}")
    server.serve_forever()
