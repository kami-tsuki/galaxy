import subprocess
import threading
import time
from pathlib import Path

from . import config, jobs, pc, player, session
from .log import log

INTERVAL = 5
OFFLINE_SECONDS = 10
STALL_SECONDS = 20
MIN_RX_BYTES_PER_SECOND = 4000
BACKOFF = (5, 15, 45)
WINDOW = 300
HEALTHY_RESET = 60
POWER_CHECK_SECONDS = 30


def default_interface(route_path="/proc/net/route"):
    try:
        for line in Path(route_path).read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 2 and fields[1] == "00000000":
                return fields[0]
    except OSError:
        pass
    return ""


def rx_bytes(interface, dev_path="/proc/net/dev"):
    try:
        for line in Path(dev_path).read_text().splitlines():
            name, _, rest = line.partition(":")
            if name.strip() == interface:
                return int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return None


def power_flags():
    try:
        output = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=3).stdout
        return int(output.strip().split("=")[1], 16)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


class Watchdog:
    def __init__(self, provider, clock=time.time, sleep=time.sleep):
        self.provider = provider
        self.clock = clock
        self.sleep = sleep
        self.attempts = []
        self.last_power = 0
        self.last_power_check = 0
        self.reset()

    def reset(self):
        self.healthy_since = None
        self.offline_since = None
        self.stalled_since = None
        self.last_rx = None

    def rx_rate(self, now):
        current = rx_bytes(default_interface())
        previous, self.last_rx = self.last_rx, (current, now) if current is not None else None
        if previous is None or current is None or now <= previous[1]:
            return None
        return (current - previous[0]) / (now - previous[1])

    def problem(self, cfg, now):
        if not player.any_active():
            return "the stream process exited"
        if pc.sunshine_up(cfg, 1):
            self.offline_since = None
        else:
            self.offline_since = self.offline_since or now
            if now - self.offline_since >= OFFLINE_SECONDS:
                return "the PC went offline"
        rate = self.rx_rate(now)
        if rate is not None and rate < MIN_RX_BYTES_PER_SECOND:
            self.stalled_since = self.stalled_since or now
            if now - self.stalled_since >= STALL_SECONDS:
                return "no video data is arriving"
        else:
            self.stalled_since = None
        return None

    def reconnect(self, cfg, request, reason, now):
        self.attempts = [moment for moment in self.attempts if now - moment < WINDOW]
        if len(self.attempts) >= len(BACKOFF):
            log(f"giving up after {len(self.attempts)} reconnects, last reason: {reason}")
            jobs.update(intent="down")
            jobs.set_phase("error", f"The stream kept dropping ({reason}), reconnecting stopped")
            self.reset()
            return
        delay = BACKOFF[len(self.attempts)]
        log(f"{reason}, reconnecting in {delay}s (attempt {len(self.attempts) + 1})")
        jobs.set_phase("reconnecting")
        self.sleep(delay)
        if jobs.snapshot()["intent"] != "up":
            return
        self.attempts.append(self.clock())
        self.reset()
        try:
            jobs.submit(
                session.connect, cfg, request.get("source", ""), request.get("audio", ""), request.get("app", "")
            )
        except jobs.Busy:
            pass

    def check_power(self, now):
        if now - self.last_power_check < POWER_CHECK_SECONDS:
            return
        self.last_power_check = now
        flags = power_flags()
        if flags is not None and flags != self.last_power:
            log(f"power or thermal status changed: {flags:#x}")
            self.last_power = flags

    def tick(self):
        now = self.clock()
        self.check_power(now)
        snapshot = jobs.snapshot()
        if snapshot["intent"] != "up" or jobs.busy():
            self.reset()
            return
        cfg = self.provider()
        reason = self.problem(cfg, now)
        if reason is None:
            self.healthy_since = self.healthy_since or now
            if now - self.healthy_since >= HEALTHY_RESET:
                self.attempts.clear()
            return
        self.healthy_since = None
        self.reconnect(cfg, snapshot["request"], reason, now)

    def run(self):
        while True:
            self.sleep(INTERVAL)
            try:
                self.tick()
            except Exception as error:
                log(f"watchdog error: {error}")


def start(provider):
    thread = threading.Thread(target=Watchdog(provider).run, daemon=True, name="watchdog")
    thread.start()
    return thread


def enabled(cfg):
    return config.flag(cfg, "WATCHDOG")
