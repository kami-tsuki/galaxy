import argparse
import getpass
import json
import subprocess
import sys

from . import api, config, jobs, pc, player, session, tv


def build_parser():
    parser = argparse.ArgumentParser(prog="galaxy")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("wake")
    sub.add_parser("pair")
    connect = sub.add_parser("connect")
    connect.add_argument("--source", default="")
    connect.add_argument("--audio", default="", choices=("", *player.AUDIO_MODES))
    connect.add_argument("--app", default="")
    tv_parser = sub.add_parser("tv")
    tv_parser.add_argument("state", choices=("on", "off"))
    power = sub.add_parser("power")
    power.add_argument("action", choices=tuple(pc.POWER_COMMANDS))
    secret = sub.add_parser("set")
    secret.add_argument("key", choices=config.SECRETS)
    return parser


def pair(cfg):
    subprocess.run(
        ["flatpak", "run", "--env=QT_QPA_PLATFORM=offscreen", "com.moonlight_stream.Moonlight", "pair", cfg["PC_HOST"]]
    )


def run(args, cfg):
    if args.command == "serve":
        api.serve(cfg)
    elif args.command == "connect":
        jobs.exclusive(session.connect, cfg, args.source, args.audio, args.app)
    elif args.command == "stop":
        jobs.exclusive(session.disconnect, cfg)
    elif args.command == "status":
        print(json.dumps(session.status(cfg), indent=2))
    elif args.command == "wake":
        pc.wake(cfg)
    elif args.command == "pair":
        pair(cfg)
    elif args.command == "tv":
        jobs.exclusive(tv.switch, cfg, args.state == "on")
    elif args.command == "power":
        pc.power(cfg, args.action)
    elif args.command == "set":
        config.save_secret(args.key, getpass.getpass(f"{args.key}: "))
        print("saved")


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args, config.load())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(f"galaxy: {error}")
