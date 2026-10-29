import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path("/etc/galaxy/galaxy.env")
ENV_FILES = (ENV_FILE, ROOT / ".env")

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
    "DISPLAY_RES": "main=3840x1080,second=1920x1080",
    "OBS_ENABLED": "false",
    "OBS_PORT": "4455",
    "OBS_PASS": "",
    "OBS_PROFILE": "Galaxy",
    "OBS_BITRATE": "8000",
    "OBS_FPS": "60",
    "SRT_PORT": "9000",
    "PI_HOST": "",
    "BOOT_WAIT": "120",
    "TV_CEC": "true",
    "TV_OFF_ON_STOP": "true",
    "CEC_DEVICE": "/dev/cec1",
    "API_BIND": "0.0.0.0",
    "API_PORT": "8787",
    "API_TOKEN": "",
}
SECRETS = ("SUNSHINE_USER", "SUNSHINE_PASS", "OBS_PASS", "API_TOKEN")


def load(paths=ENV_FILES, environ=None):
    environ = os.environ if environ is None else environ
    cfg = dict(DEFAULTS)
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            cfg[key.strip()] = value.strip().strip('"').strip("'")
    for key in DEFAULTS:
        if key in environ:
            cfg[key] = environ[key]
    return cfg


def flag(cfg, key):
    return cfg[key].strip().lower() in ("1", "true", "yes", "on")


def pairs(text):
    result = {}
    for item in text.split(","):
        if "=" in item:
            name, value = item.split("=", 1)
            result[name.strip()] = value.strip()
    return result


def screens(cfg):
    return pairs(cfg["DISPLAYS"])


def apps(cfg):
    return [item.strip() for item in cfg["APPS"].split(",") if item.strip()]


def obs_enabled(cfg):
    return flag(cfg, "OBS_ENABLED") and bool(cfg["OBS_PASS"])


def sources(cfg):
    names = list(screens(cfg))
    if obs_enabled(cfg):
        names.append("obs")
    return names


def save_secret(key, value, path=ENV_FILE):
    if key not in SECRETS:
        raise RuntimeError(f"'{key}' cannot be set this way")
    if "\n" in value or "\r" in value:
        raise RuntimeError("value must be one line")
    path = Path(path)
    lines = path.read_text().splitlines() if path.is_file() else []
    out, found = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            line, found = f"{key}={value}", True
        out.append(line)
    if not found:
        out.append(f"{key}={value}")
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    subprocess.run(
        prefix + ["tee", str(path)], input=("\n".join(out) + "\n").encode(), stdout=subprocess.DEVNULL, check=True
    )
