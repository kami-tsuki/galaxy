import subprocess
import time

from .config import flag
from .log import log

ATTEMPTS = 3
SETTLE_SECONDS = 6


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
        log(f"cec-client failed: {error}")
        return ""


def parse_power(output):
    for line in output.splitlines():
        if line.startswith("power status:"):
            text = line.split(":", 1)[1].strip()
            if text == "on" or text.endswith("to on"):
                return "on"
            if text == "standby" or text.endswith("to standby"):
                return "standby"
    return "unknown"


def power_state(cfg):
    return parse_power(cec(cfg, "pow 0"))


def switch(cfg, on):
    if not flag(cfg, "TV_CEC"):
        return True
    wanted = "on" if on else "standby"
    for attempt in range(ATTEMPTS):
        if power_state(cfg) == wanted:
            return True
        cec(cfg, "on 0" if on else "standby 0")
        if attempt < ATTEMPTS - 1:
            time.sleep(SETTLE_SECONDS)
    time.sleep(SETTLE_SECONDS)
    return power_state(cfg) == wanted
