import subprocess
import time

from .config import flag


def cec(cfg, command):
    try:
        result = subprocess.run(
            ["cec-client", "-s", "-d", "1", cfg["CEC_DEVICE"]],
            input=command.encode(),
            capture_output=True,
            timeout=25,
        )
        return result.stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
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
    for _ in range(3):
        if power_state(cfg) == wanted:
            return True
        cec(cfg, "on 0" if on else "standby 0")
        time.sleep(6)
    return power_state(cfg) == wanted
