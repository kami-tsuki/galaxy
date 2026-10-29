import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import config, jobs, pc, session, tv
from .config import ROOT
from .log import log

MAX_BODY = 4096
INDEX = ROOT / "galaxy" / "web" / "index.html"


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
                return self.reply(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            if not self.authorized():
                return
            if route == "/v1/status":
                try:
                    return self.reply(200, session.status(cfg))
                except Exception as error:
                    log(f"status failed: {error}")
                    return self.reply(502, {"error": str(error)})
            self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return
            route = urlparse(self.path).path
            try:
                if route == "/v1/connect":
                    options = self.body()
                    for key in ("source", "audio", "app"):
                        if not isinstance(options.get(key, ""), str):
                            raise ValueError(f"{key} must be a string")
                    source, audio, app = (options.get(key, "") for key in ("source", "audio", "app"))
                    session.validate(cfg, source, audio, app)
                    jobs.submit(session.connect, cfg, source, audio, app, log=log)
                elif route == "/v1/stop":
                    jobs.submit(session.disconnect, cfg, log=log)
                elif route == "/v1/wake":
                    pc.wake(cfg)
                elif route in ("/v1/tv/on", "/v1/tv/off"):
                    jobs.submit(tv.switch, cfg, route.endswith("on"), report=False, log=log)
                elif route.startswith("/v1/") and route[4:] in pc.POWER_COMMANDS:
                    pc.power(cfg, route[4:])
                else:
                    return self.reply(404, {"error": "not found"})
            except jobs.Busy as error:
                return self.reply(409, {"error": str(error)})
            except (ValueError, KeyError) as error:
                return self.reply(400, {"error": str(error)})
            except Exception as error:
                return self.reply(502, {"error": str(error)})
            self.reply(202, {"accepted": route})

    return Handler


def serve(cfg):
    if not cfg["API_TOKEN"]:
        raise SystemExit("API_TOKEN is not set")
    server = ThreadingHTTPServer((cfg["API_BIND"], int(cfg["API_PORT"])), make_handler(cfg))
    log(f"listening on {cfg['API_BIND']}:{cfg['API_PORT']}")
    server.serve_forever()
