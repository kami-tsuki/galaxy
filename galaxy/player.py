import os
import re
import subprocess
import time
from pathlib import Path

from . import config

MOONLIGHT = "galaxy-stream.service"
OBS = "galaxy-obs.service"
UNITS = (MOONLIGHT, OBS)
AUDIO_MODES = {
    "both": ("--audio-on-host", "alsa"),
    "tv": ("--no-audio-on-host", "alsa"),
    "pc": ("--audio-on-host", "dummy"),
}
RESOLUTION = re.compile(r"^\d{3,5}x\d{3,5}$")


def session_path():
    return Path(f"/run/user/{os.getuid()}/galaxy-session.env")


def control(action, unit):
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    result = subprocess.run(prefix + ["systemctl", action, unit], capture_output=True, text=True)
    if result.returncode != 0 and action == "start":
        raise RuntimeError(result.stderr.strip() or f"{unit} failed to start")


def active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def stop_all():
    for unit in UNITS:
        if active(unit):
            control("stop", unit)


def confirm(unit, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not active(unit):
            raise RuntimeError(f"{unit} exited right after starting, check: journalctl -u {unit}")
        time.sleep(1)


def write_session(cfg, app, audio, resolution, path=None):
    if audio not in AUDIO_MODES:
        raise ValueError(f"unknown audio mode '{audio}', choose from: {', '.join(AUDIO_MODES)}")
    if app not in config.apps(cfg) and app != cfg["SUNSHINE_APP"]:
        raise ValueError(f"unknown app '{app}', choose from: {', '.join(config.apps(cfg))}")
    if not RESOLUTION.fullmatch(resolution):
        raise ValueError(f"invalid resolution '{resolution}'")
    if any(char in app for char in '"\\$\n') or app.startswith("-"):
        raise ValueError("invalid app name")
    flags, driver = AUDIO_MODES[audio]
    path = Path(path) if path else session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'SUNSHINE_APP="{app}"\nAUDIO_FLAGS="{flags}"\nAUDIO_DRIVER={driver}\nRESOLUTION_FLAGS="--resolution {resolution}"\n'
    )


def read_session(path=None):
    values = {}
    try:
        for line in (Path(path) if path else session_path()).read_text().splitlines():
            key, _, value = line.partition("=")
            values[key] = value.strip('"')
    except OSError:
        pass
    audio = ""
    for mode, (flags, driver) in AUDIO_MODES.items():
        if values.get("AUDIO_FLAGS") == flags and values.get("AUDIO_DRIVER") == driver:
            audio = mode
    return {"app": values.get("SUNSHINE_APP", ""), "audio": audio}
