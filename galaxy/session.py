import threading
import time

from . import config, jobs, obs, pc, player, sunshine, tv
from .log import log


def validate(cfg, source, audio, app):
    if source and source not in config.sources(cfg):
        raise ValueError(f"unknown source '{source}', choose from: {', '.join(config.sources(cfg)) or 'none configured'}")
    if audio and audio not in player.AUDIO_MODES:
        raise ValueError(f"unknown audio mode '{audio}', choose from: {', '.join(player.AUDIO_MODES)}")
    if app and app not in config.apps(cfg):
        raise ValueError(f"unknown app '{app}', choose from: {', '.join(config.apps(cfg))}")


def obs_in_use():
    return player.active(player.OBS) or jobs.snapshot().get("obs_active", False)


def finish_obs(cfg):
    if config.obs_enabled(cfg) and pc.sunshine_up(cfg):
        obs.end(cfg)
    jobs.update(obs_active=False)


def release(cfg):
    was_obs = obs_in_use()
    player.stop_all()
    if was_obs:
        finish_obs(cfg)


def display_name(cfg, online):
    screens = config.screens(cfg)
    chosen = jobs.snapshot()["source"]
    output = sunshine.current_output(cfg) if online else None
    if output is None:
        return chosen
    if chosen in screens and screens[chosen] == output:
        return chosen
    for name, ident in screens.items():
        if ident == output:
            return name
    return ""


def start_screen(cfg, source, app, audio, tv_thread):
    jobs.set_phase("display")
    sunshine.select_output(cfg, config.screens(cfg)[source])
    resolution = config.pairs(cfg["DISPLAY_RES"]).get(source, "1920x1080")
    player.write_session(cfg, app, audio, resolution)
    tv_thread.join(timeout=120)
    jobs.set_phase("connecting")
    player.control("start", player.MOONLIGHT)
    player.confirm(player.MOONLIGHT)


def start_obs(cfg, tv_thread):
    jobs.set_phase("connecting")
    tv_thread.join(timeout=120)
    player.control("start", player.OBS)
    time.sleep(2)
    player.confirm(player.OBS, 4)
    jobs.update(obs_active=True)
    obs.begin(cfg, f"srt://{pc.local_address(cfg)}:{cfg['SRT_PORT']}?mode=caller&pkt_size=1316")
    player.confirm(player.OBS, 6)


def connect(cfg, source="", audio="", app=""):
    if not cfg["PC_HOST"]:
        raise RuntimeError("PC_HOST is not configured")
    validate(cfg, source, audio, app)
    saved = player.read_session()
    source = source or jobs.snapshot()["source"] or "main"
    if source not in config.sources(cfg):
        raise RuntimeError(f"source '{source}' is not available")
    audio = audio or saved["audio"] or "both"
    app = app or saved["app"] or cfg["SUNSHINE_APP"]
    jobs.update(warning="", source=source)
    was_obs = obs_in_use()
    player.stop_all()
    jobs.set_phase("tv")
    outcome = {}
    tv_thread = threading.Thread(target=lambda: outcome.update(ok=tv.switch(cfg, True)), daemon=True)
    tv_thread.start()
    try:
        pc.boot(cfg, on_wait=lambda: jobs.set_phase("waking"))
        if was_obs:
            finish_obs(cfg)
        if source == "obs":
            start_obs(cfg, tv_thread)
        else:
            start_screen(cfg, source, app, audio, tv_thread)
    except BaseException:
        try:
            release(cfg)
        except Exception as error:
            log(f"cleanup failed: {error}")
        raise
    if not outcome.get("ok", True):
        jobs.update(warning="The TV did not confirm that it is on")
    jobs.set_phase("streaming")


def disconnect(cfg):
    jobs.set_phase("stopping")
    release(cfg)
    if config.flag(cfg, "TV_OFF_ON_STOP"):
        tv.switch(cfg, False)
    jobs.set_phase("idle")


def status(cfg):
    snap = jobs.snapshot()
    moonlight = player.active(player.MOONLIGHT)
    receiver = player.active(player.OBS)
    live = moonlight or receiver
    phase, error = snap["phase"], snap["error"]
    if phase == "streaming" and not live and not jobs.busy():
        phase, error = "error", "The stream ended unexpectedly"
        jobs.set_phase(phase, error)
    elif live and phase in ("idle", "error") and not jobs.busy():
        phase, error = "streaming", ""
    saved = player.read_session()
    online = pc.online(cfg)
    if receiver:
        source = "obs"
    elif jobs.busy():
        source = snap["source"]
    elif online:
        source = display_name(cfg, online)
    else:
        source = snap["source"]
    return {
        "phase": phase,
        "error": error,
        "warning": snap["warning"],
        "stream": live,
        "busy": jobs.busy(),
        "pc_online": online,
        "pc_host": cfg["PC_HOST"],
        "source": source,
        "sources": config.sources(cfg),
        "app": saved["app"] or cfg["SUNSHINE_APP"],
        "apps": config.apps(cfg),
        "audio": saved["audio"] or "both",
        "audio_modes": list(player.AUDIO_MODES),
    }
