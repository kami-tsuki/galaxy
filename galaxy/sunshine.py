import base64
import json
import ssl
import time
import urllib.error
import urllib.request

from . import jobs, pc

IGNORED_KEYS = ("platform", "version", "status")


def api(cfg, method, path, body=None):
    if not cfg["SUNSHINE_USER"]:
        raise RuntimeError("SUNSHINE_USER is not configured, run: galaxy set SUNSHINE_USER")
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


def settings(cfg):
    return {key: value for key, value in api(cfg, "GET", "/api/config").items() if key not in IGNORED_KEYS}


def current_output(cfg):
    def read():
        try:
            return settings(cfg).get("output_name", "")
        except (OSError, RuntimeError, ValueError):
            return None

    return jobs.cached("sunshine-output", 8, read)


def wait_restart(cfg):
    deadline = time.time() + 20
    while time.time() < deadline and pc.sunshine_up(cfg, 1):
        time.sleep(1)
    deadline = time.time() + 60
    while time.time() < deadline:
        if pc.sunshine_up(cfg, 1):
            try:
                settings(cfg)
                return
            except (OSError, RuntimeError, ValueError):
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
