import argparse
import getpass
import json
import subprocess
import sys

from . import api, config, pc, player, session, sunshine, tv


def build_parser():
    parser = argparse.ArgumentParser(prog="python3 -m galaxy")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the API and the web page")
    sub.add_parser("stop", help="stop the picture and switch the TV off")
    sub.add_parser("status", help="print the current state")
    sub.add_parser("wake", help="send Wake-on-LAN to the PC")
    sub.add_parser("pair", help="pair Moonlight with Sunshine and pin Sunshine's certificate")
    sub.add_parser("pin", help="pin Sunshine's current certificate")
    connect = sub.add_parser("connect", help="start or replace a session")
    connect.add_argument("--source", default="")
    connect.add_argument("--audio", default="", choices=("", *player.AUDIO_MODES))
    connect.add_argument("--app", default="")
    tv_parser = sub.add_parser("tv", help="switch the TV on or off")
    tv_parser.add_argument("state", choices=("on", "off"))
    power = sub.add_parser("power", help="sleep, shut down or restart the PC over SSH")
    power.add_argument("action", choices=tuple(pc.POWER_COMMANDS))
    setting = sub.add_parser("set", help="store a secret in /etc/galaxy/galaxy.env without echoing it")
    setting.add_argument("key", choices=config.SECRETS)
    return parser


def require_host(cfg):
    if not cfg["PC_HOST"]:
        raise RuntimeError("PC_HOST is not configured, set it in /etc/galaxy/galaxy.env")


def pin(cfg):
    require_host(cfg)
    config.save_setting("SUNSHINE_CERT_SHA256", sunshine.fingerprint(cfg))
    print("pinned the current Sunshine certificate")


def pair(cfg):
    require_host(cfg)
    subprocess.run(
        ["flatpak", "run", "--env=QT_QPA_PLATFORM=offscreen", "com.moonlight_stream.Moonlight", "pair", cfg["PC_HOST"]],
        check=True,
    )
    pin(cfg)


def run(args, cfg):
    if args.command == "serve":
        api.serve(config.load)
    elif args.command == "connect":
        session.connect(cfg, args.source, args.audio, args.app)
    elif args.command == "stop":
        session.disconnect(cfg)
    elif args.command == "status":
        print(json.dumps(session.status(cfg), indent=2))
    elif args.command == "wake":
        pc.wake(cfg)
    elif args.command == "pair":
        pair(cfg)
    elif args.command == "pin":
        pin(cfg)
    elif args.command == "tv":
        tv.switch(cfg, args.state == "on")
    elif args.command == "power":
        pc.power(cfg, args.action)
    elif args.command == "set":
        config.save_setting(args.key, getpass.getpass(f"{args.key}: "))
        print("saved, restart is not needed")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args, config.load())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"galaxy: {error}")
