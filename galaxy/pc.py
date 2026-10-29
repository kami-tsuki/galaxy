import re
import socket
import subprocess
import time

from . import jobs

MAC = re.compile(r"^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")
POWER_COMMANDS = {
    "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    "shutdown": "shutdown /s /t 0",
    "restart": "shutdown /r /t 0",
}


def sunshine_up(cfg, timeout=2):
    if not cfg["PC_HOST"]:
        return False
    try:
        with socket.create_connection((cfg["PC_HOST"], int(cfg["SUNSHINE_PORT"])), timeout=timeout):
            return True
    except OSError:
        return False


def online(cfg):
    return jobs.cached("pc-online", 3, lambda: sunshine_up(cfg))


def magic_packet(mac):
    if not MAC.fullmatch(mac):
        raise RuntimeError("PC_MAC is not a valid MAC address")
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16


def wake(cfg):
    packet = magic_packet(cfg["PC_MAC"])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in {cfg["PC_BROADCAST"], "255.255.255.255"}:
            for port in (7, 9):
                sock.sendto(packet, (target, port))


def boot(cfg, on_wait=lambda: None):
    if sunshine_up(cfg):
        return
    on_wait()
    deadline = time.time() + int(cfg["BOOT_WAIT"])
    while time.time() < deadline and not sunshine_up(cfg):
        wake(cfg)
        time.sleep(5)
    if not sunshine_up(cfg):
        raise RuntimeError("PC did not come up")


def power(cfg, action):
    if action not in POWER_COMMANDS:
        raise ValueError(f"unknown power action '{action}'")
    if not cfg["PC_SSH"]:
        raise RuntimeError("PC_SSH is not configured")
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", cfg["PC_SSH"], POWER_COMMANDS[action]],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 255:
        raise RuntimeError(result.stderr.strip() or "PC is not reachable over SSH")


def local_address(cfg):
    if cfg["PI_HOST"]:
        return cfg["PI_HOST"]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((cfg["PC_HOST"], 9))
        return sock.getsockname()[0]
