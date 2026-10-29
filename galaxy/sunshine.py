import hashlib
import hmac
import http.client
import json
import socket
import ssl
import time
from base64 import b64encode

from . import jobs, pc

IGNORED_KEYS = ("platform", "version", "status")
ERRORS = (OSError, RuntimeError, ValueError)


def tls_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def fingerprint(cfg, timeout=8):
    with socket.create_connection((cfg["PC_HOST"], int(cfg["SUNSHINE_UI_PORT"])), timeout=timeout) as sock:
        with tls_context().wrap_socket(sock, server_hostname=cfg["PC_HOST"]) as tls:
            return hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()


def api(cfg, method, path, body=None):
    if not cfg["SUNSHINE_USER"]:
        raise RuntimeError("SUNSHINE_USER is not configured, run: python3 -m galaxy set SUNSHINE_USER")
    credentials = b64encode(f"{cfg['SUNSHINE_USER']}:{cfg['SUNSHINE_PASS']}".encode()).decode()
    connection = http.client.HTTPSConnection(
        cfg["PC_HOST"], int(cfg["SUNSHINE_UI_PORT"]), timeout=15, context=tls_context()
    )
    try:
        connection.connect()
        pinned = cfg["SUNSHINE_CERT_SHA256"].strip().lower()
        if pinned:
            seen = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
            if not hmac.compare_digest(seen, pinned):
                raise RuntimeError("Sunshine's certificate changed, if you reinstalled it run: python3 -m galaxy pin")
        connection.request(
            method,
            path,
            body=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read()
    finally:
        connection.close()
    if response.status in (401, 403):
        raise RuntimeError("Sunshine rejected the login, check SUNSHINE_USER and SUNSHINE_PASS")
    if response.status >= 400:
        raise RuntimeError(f"Sunshine answered {response.status} for {path}")
    return json.loads(raw) if raw else {}


def settings(cfg):
    return {key: value for key, value in api(cfg, "GET", "/api/config").items() if key not in IGNORED_KEYS}


def current_output(cfg):
    def read():
        try:
            return settings(cfg).get("output_name", "")
        except ERRORS:
            return None

    return jobs.cached("sunshine-output", 8, read)


def wait_restart(cfg):
    deadline = time.time() + 20
    while time.time() < deadline and pc.sunshine_up(cfg, 1):
        jobs.check_cancel()
        time.sleep(1)
    deadline = time.time() + 60
    while time.time() < deadline:
        jobs.check_cancel()
        if pc.sunshine_up(cfg, 1):
            try:
                settings(cfg)
                return
            except ERRORS:
                pass
        time.sleep(2)
    raise RuntimeError("Sunshine did not come back after restart")


def select_output(cfg, device_id):
    current = settings(cfg)
    if current.get("output_name") == device_id:
        return False
    current["output_name"] = device_id
    api(cfg, "POST", "/api/config", current)
    try:
        api(cfg, "POST", "/api/restart", {})
    except OSError:
        pass
    wait_restart(cfg)
    jobs.invalidate("sunshine-output")
    return True
