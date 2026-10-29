# Galaxy

Control a gaming PC from a Raspberry Pi that is connected to a TV. Open the web page, choose what to share and the sound, press Connect. Galaxy wakes the PC, switches the TV on and starts the picture on the TV, and brings it back if the stream drops.

| Source | Path | Notes |
|---|---|---|
| a PC screen (`main`, `second`, ...) | Sunshine on the PC, Moonlight on the Pi | the PC screen is captured as it is, sound on PC, TV or both |
| `obs` | OBS on the PC sends its output straight to the Pi over SRT, mpv plays it | uses no monitor, the picture is OBS's own canvas, sound comes from OBS |

The old GPIO button and LED version is archived in [`legacy/`](legacy).

## How it works

```
PC (Windows)                              Pi 5 (Raspberry Pi OS Trixie)                 TV
Sunshine  ---- Moonlight stream ---->     cage + Moonlight (Flatpak)        --HDMI-->  picture, sound
OBS       ---- SRT (caller) -------->     cage + mpv (SRT listener)                    CEC power
OBS WebSocket <-- control ---------       galaxy: web page, HTTP API, watchdog on :8787
```

| Module | Role |
|---|---|
| `galaxy/config.py` | settings and secrets |
| `galaxy/jobs.py` | state, one-action-at-a-time lock, cancel |
| `galaxy/pc.py` | Wake-on-LAN, boot wait, PC power over SSH |
| `galaxy/tv.py` | TV power over HDMI-CEC |
| `galaxy/sunshine.py` | Sunshine API with certificate pinning: screen selection |
| `galaxy/obs.py` | OBS WebSocket client, Galaxy profile, SRT stream |
| `galaxy/player.py` | systemd units for Moonlight and the OBS receiver, session file |
| `galaxy/session.py` | connect, disconnect, status |
| `galaxy/watchdog.py` | reconnects a dropped stream |
| `galaxy/api.py`, `galaxy/web/index.html` | HTTP API and control page |
| `galaxy/cli.py` | command line |
| `systemd/`, `pipewire/` | units and audio settings installed by `setup.sh` |
| `tests/` | unit tests |

## Requirements

- Raspberry Pi 5 (or 4) with Raspberry Pi OS Trixie, connected to the TV over HDMI
- Windows PC with [Sunshine](https://github.com/LizardByte/Sunshine) installed and running (`winget install LizardByte.Sunshine`), with its web login created
- Wake-on-LAN enabled on the PC (BIOS and network adapter) if it should be woken
- Optional, for the `obs` source: OBS 28 or newer with its WebSocket server enabled (Tools, WebSocket Server Settings)

## Install

On the Pi, from a clone of this repository (run all commands from the clone directory):

```
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy
./setup.sh
```

`setup.sh` is safe to re-run. It installs the packages (`cage`, Flatpak and Moonlight, `mpv`, PipeWire, `cec-utils`), creates `/etc/galaxy/galaxy.env` with a generated `API_TOKEN` (or adds missing keys to an existing file), installs the three units, a sudoers rule limited to starting and stopping the two player units, and turns on:

- PipeWire with a 1024-sample minimum buffer for Moonlight's sound,
- Wi-Fi power save off and a persistent system journal, so a disconnect or reboot leaves evidence,
- masking of the desktop portal services on a Pi without a desktop, which otherwise delay every Moonlight start by more than a minute.

Log out and back in once so the new groups apply to your own session. Then configure:

1. Edit `/etc/galaxy/galaxy.env` and set `PC_HOST`, `PC_MAC` and `DISPLAYS` (see below). Changes are picked up without a restart.
2. `python3 -m galaxy set SUNSHINE_USER` and `python3 -m galaxy set SUNSHINE_PASS` store the Sunshine web login without echoing it.
3. `python3 -m galaxy pair` starts Moonlight pairing and waits. Enter the PIN in the Sunshine web UI under **PIN**. It then pins Sunshine's certificate (`python3 -m galaxy pin` repeats that after a Sunshine reinstall).
4. Open `http://<pi-ip>:8787/#token=<API_TOKEN>` once; the page stores the token and removes it from the address bar. Give the Pi and the PC fixed addresses in the router.

### First-run checklist

- **Display ids**: in Sunshine's log (`C:\Program Files\Sunshine\config\sunshine.log`), under "Currently available display devices", each screen has a `device_id` and a `friendly_name`. Write them as `DISPLAYS=main={id},second={id}` and pick matching stream sizes in `DISPLAY_RES`.
- **CEC port**: `ls /dev/cec*`; `CEC_DEVICE` must be the HDMI port the TV is on (`cec-client -s -d 1 /dev/cec1` with `scan` shows the TV).
- **Check**: `python3 -m galaxy status` shows the phase, the PC state and the available sources. An empty source list means `DISPLAYS` is not set.

## Using the page

- **What to share**: the PC screens from `DISPLAYS`, plus `OBS output` when OBS is enabled.
- **What to show** (PC screens): the apps from `APPS`, which must exist in Sunshine.
- **Sound** (PC screens): `PC + TV`, `TV only` or `PC only`.
- **Connect**: wakes the PC if needed, switches the TV on, starts the picture. While connected the button reads **Disconnect**, or **Apply changes** after you change a choice. While a connection is being made it reads **Cancel**.

The page shows the real state reported by the Pi, so a second browser or a reload always agrees with what is running.

## Reliability

The watchdog runs inside the API service. While a session is meant to be up it reconnects when

- the stream process exited,
- the PC went offline for more than 10 seconds,
- less than about 4 KB/s arrives from the network for 20 seconds (a frozen stream).

It retries after 5, 15 and 45 seconds, at most three times in five minutes, then stops and shows an error. It never switches the TV off. Disconnect cancels a connect in progress. Set `WATCHDOG=false` to turn it off. It also logs changes in the Pi's power and thermal flags.

Wi-Fi is enough for 1080p60, but a cable is the most reliable choice. With Wi-Fi, prefer a non-DFS 5 GHz channel on the router.

## PC screens

Sunshine captures one screen at a time. Galaxy sets `output_name` through the Sunshine API (keeping all other Sunshine settings) and restarts Sunshine only when the screen actually changes.

Each screen has a stream resolution in `DISPLAY_RES`, so the picture keeps its proportions. A 32:9 monitor is streamed at `3840x1080` and appears with bars above and below on a 16:9 TV; a 1080p screen is streamed at `1920x1080`.

| Sound mode | Pi (TV) | PC speakers |
|---|---|---|
| `both` | plays | plays |
| `tv` | plays | muted by Moonlight |
| `pc` | silent | plays |

Moonlight's sound library only supports PipeWire and PulseAudio. `PC only` sets Moonlight's audio driver to `dummy`. The mode is written for each session to `/run/user/<uid>/galaxy-session.env`; `AUDIO_FLAGS`, `AUDIO_DRIVER` and `RESOLUTION_FLAGS` in `galaxy.env` are only defaults for a manual start.

The sound that reaches the TV is what Sunshine captures: the PC's default playback device. If your video plays through another device, change Windows' default output.

## OBS source

Set `OBS_ENABLED=true` and `OBS_PASS` (the OBS WebSocket password; without it the source stays hidden). On Connect Galaxy:

1. starts the SRT receiver on the Pi (`mpv` in `cage`, listening on `SRT_PORT`),
2. switches OBS to its own profile (`OBS_PROFILE`, created on first use) so your own profiles and stream settings stay untouched,
3. sets that profile to a 1920x1080 canvas at `OBS_FPS`, `OBS_BITRATE` kbps, with the Pi as the stream target,
4. starts the OBS stream.

On Disconnect it stops the OBS stream and switches OBS back to the profile you were using. If OBS is already streaming in another profile, Galaxy refuses instead of touching it. Close any dialog that is open in OBS, such as "OBS has crashed!": it blocks OBS from answering.

## Configuration

`/etc/galaxy/galaxy.env` is read on every request; a `.env` in the clone directory and environment variables with the same names override it. Defaults and examples are in [`.env.example`](.env.example).

| Key | Meaning |
|---|---|
| `PC_HOST`, `PC_MAC`, `PC_BROADCAST` | PC address, MAC for Wake-on-LAN, subnet broadcast |
| `PC_SSH` | `user@host` for sleep, shutdown and restart (needs OpenSSH server and a key on the PC) |
| `SUNSHINE_APP`, `APPS` | default app and the list offered in the page |
| `SUNSHINE_PORT`, `SUNSHINE_UI_PORT` | Sunshine stream and web UI ports |
| `SUNSHINE_USER`, `SUNSHINE_PASS` | Sunshine web login, set with `python3 -m galaxy set` |
| `SUNSHINE_CERT_SHA256` | pinned Sunshine certificate, set by `python3 -m galaxy pair` or `pin` |
| `DISPLAYS` | `name={device id}` pairs for the PC screens (the name `obs` is reserved) |
| `DISPLAY_RES` | `name=WxH` stream resolution per screen |
| `OBS_ENABLED`, `OBS_PASS`, `OBS_PORT`, `OBS_PROFILE`, `OBS_BITRATE`, `OBS_FPS` | OBS source |
| `SRT_PORT`, `PI_HOST` | SRT listener port; the Pi's address as seen from the PC (detected when empty) |
| `BOOT_WAIT` | seconds to wait for a woken PC |
| `TV_CEC`, `TV_OFF_ON_STOP`, `CEC_DEVICE` | CEC control of the TV |
| `WATCHDOG` | automatic reconnect, `true` or `false` |
| `API_BIND`, `API_PORT`, `API_TOKEN` | HTTP API; the token needs at least 24 characters |
| `MOONLIGHT_ARGS`, `RESOLUTION_FLAGS`, `AUDIO_FLAGS`, `AUDIO_DRIVER` | read only by the stream unit |

Secrets set with `python3 -m galaxy set` may not contain `"`, `'`, `\`, `$` or `#`. The player units do not receive the secret keys in their environment.

## CLI

```
python3 -m galaxy connect [--source NAME] [--audio both|tv|pc] [--app NAME]
python3 -m galaxy stop
python3 -m galaxy status
python3 -m galaxy wake
python3 -m galaxy tv on|off
python3 -m galaxy power sleep|shutdown|restart
python3 -m galaxy set SUNSHINE_USER|SUNSHINE_PASS|OBS_PASS|API_TOKEN
python3 -m galaxy pair
python3 -m galaxy pin
```

`connect`, `stop` and `tv` run in the calling process and do not share the API's lock; use the web page or the API while the service is running a session.

## HTTP API

Plain HTTP with `Authorization: Bearer <API_TOKEN>`; keep it on the home network and set `API_BIND` to the Pi's LAN address. Only one action runs at a time: a second connect gets `409`. Invalid options and incomplete configuration get `400`.

| Method | Path | Action |
|---|---|---|
| GET | `/` | the control page |
| GET | `/v1/status` | phase, PC and stream state, current source, app and sound, available choices |
| POST | `/v1/connect` | body `{"source","app","audio"}`, starts or replaces a session |
| POST | `/v1/stop` | cancels a running connect, then stops the session |
| POST | `/v1/wake` | Wake-on-LAN |
| POST | `/v1/tv/on`, `/v1/tv/off` | TV power |
| POST | `/v1/sleep`, `/v1/shutdown`, `/v1/restart` | PC power over SSH |

## Troubleshooting

| Symptom | Check |
|---|---|
| Page offline or "Token missing or wrong" | token in `/etc/galaxy/galaxy.env`; `systemctl status galaxy` |
| "SUNSHINE_USER is not configured" | `python3 -m galaxy set SUNSHINE_USER` and `SUNSHINE_PASS` |
| "Sunshine's certificate changed" | `python3 -m galaxy pin` after reinstalling Sunshine |
| TV never switches on | `ls /dev/cec*`, set `CEC_DEVICE`; enable HDMI-CEC on the TV |
| "PC did not come up" | Wake-on-LAN settings and `PC_MAC`; raise `BOOT_WAIT` |
| Stream drops | `journalctl -u galaxy` (watchdog lines), `journalctl -u galaxy-stream`, Wi-Fi quality; the journal survives reboots |
| No sound on the TV | `pactl list short sink-inputs` while streaming; `pw-top` should show no growing error count |
| OBS "did not answer" | close dialogs in OBS on the PC |

## Development

```
python -m unittest discover -s tests -t .
```

The tests use only the standard library and mock every subprocess, socket and sleep. CI runs them on Python 3.11 and 3.13.

## License

MIT, see [LICENSE](LICENSE).
