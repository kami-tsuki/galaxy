# Galaxy

Control a gaming PC from a Raspberry Pi that is connected to a TV. Open the web page, choose what to share and the sound, press Connect. Galaxy wakes the PC, switches the TV on and starts the picture on the TV.

Two kinds of source are available:

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
OBS WebSocket <-- control ---------       galaxy: web page, HTTP API, CLI on :8787
```

| Module | Role |
|---|---|
| `galaxy/config.py` | settings, secrets |
| `galaxy/jobs.py` | state, one-action-at-a-time lock, cache |
| `galaxy/pc.py` | Wake-on-LAN, boot wait, PC power over SSH |
| `galaxy/tv.py` | TV power over HDMI-CEC |
| `galaxy/sunshine.py` | Sunshine API: screen selection |
| `galaxy/obs.py` | OBS WebSocket client, Galaxy profile, SRT stream |
| `galaxy/player.py` | systemd units for Moonlight and the OBS receiver, session file |
| `galaxy/session.py` | connect, disconnect, status |
| `galaxy/api.py`, `galaxy/web/index.html` | HTTP API and control page |
| `galaxy/cli.py` | command line |
| `systemd/` | `galaxy.service` (API), `galaxy-stream.service`, `galaxy-obs.service` |
| `setup.sh` | install and update on the Pi, safe to re-run |
| `tests/` | unit tests (`python -m unittest discover -s tests -t .`) |

## Requirements

- Raspberry Pi 5 (or 4) with Raspberry Pi OS Trixie, connected to the TV over HDMI
- Windows PC with [Sunshine](https://github.com/LizardByte/Sunshine) (`winget install LizardByte.Sunshine`)
- Wake-on-LAN enabled on the PC (BIOS and network adapter) if it should be woken
- Optional, for the `obs` source: OBS 28 or newer with its WebSocket server enabled (Tools, WebSocket Server Settings)

## Install on the Pi

```
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy
./setup.sh
sudo nano /etc/galaxy/galaxy.env
python3 -m galaxy set SUNSHINE_USER
python3 -m galaxy set SUNSHINE_PASS
python3 -m galaxy pair
```

`setup.sh` installs `cage`, Flatpak, Moonlight, `mpv` and `cec-utils`, creates `/etc/galaxy/galaxy.env` with a generated `API_TOKEN` (or adds missing keys to an existing one), installs the three units, a sudoers rule limited to starting and stopping the two player units, and enables lingering for the user.

`pair` asks Moonlight to pair with the PC and waits. Enter the PIN in the Sunshine web UI under **PIN**. To choose the PIN yourself run Moonlight directly with `pair <pc-ip> --pin 4821`.

Secrets are stored with `python3 -m galaxy set KEY` (`SUNSHINE_USER`, `SUNSHINE_PASS`, `OBS_PASS`, `API_TOKEN`). The value is typed without echo and written to the root-owned env file.

Open `http://<pi-ip>:8787/#token=<API_TOKEN>` once in a browser; the page stores the token and removes it from the address bar. Give the Pi and the PC fixed addresses in the router.

## Using the page

- **What to share**: the PC screens from `DISPLAYS`, plus `OBS output` when OBS is enabled.
- **What to show** (PC screens): the apps from `APPS`, which must exist in Sunshine.
- **Sound** (PC screens): `PC + TV`, `TV only` or `PC only`.
- **Connect**: wakes the PC if needed, switches the TV on, starts the picture. While connected the button reads **Disconnect**, or **Apply changes** after you change a choice.

The page shows the real state reported by the Pi, so a second browser or a reload always agrees with what is running.

## PC screens

Sunshine captures one screen at a time. Galaxy sets `output_name` through the Sunshine API (keeping all other Sunshine settings) and restarts Sunshine only when the screen actually changes.

Each screen has a stream resolution in `DISPLAY_RES`, so the picture keeps its proportions. A 32:9 monitor is streamed at `3840x1080` and appears with bars above and below on a 16:9 TV; a 1080p screen is streamed at `1920x1080`.

| Sound mode | Pi (TV) | PC speakers |
|---|---|---|
| `both` | plays | plays |
| `tv` | plays | muted by Moonlight |
| `pc` | silent | plays |

Moonlight's sound library only supports PipeWire and PulseAudio, so `setup.sh` installs PipeWire with its PulseAudio bridge for the user and Moonlight (Flatpak) plays through it. The Pi's only connected HDMI port is the default output. `PC only` sets Moonlight's audio driver to `dummy`, so nothing plays on the TV. The chosen mode is written for each session to `/run/user/<uid>/galaxy-session.env`; `AUDIO_FLAGS`, `AUDIO_DRIVER` and `RESOLUTION_FLAGS` in `galaxy.env` are only the defaults for a manual start.

## OBS source

Set `OBS_ENABLED=true` and `OBS_PASS` (the OBS WebSocket password). On Connect Galaxy:

1. starts the SRT receiver on the Pi (`mpv` in `cage`, listening on `SRT_PORT`),
2. switches OBS to its own profile (`OBS_PROFILE`, created on first use) so your own profiles and stream settings stay untouched,
3. sets that profile to a 1920x1080 canvas at `OBS_FPS`, `OBS_BITRATE` kbps, with the Pi as the stream target,
4. starts the OBS stream.

On Disconnect it stops the OBS stream and switches OBS back to the profile you were using. If OBS is already streaming in another profile, Galaxy refuses instead of touching it. The picture and sound are whatever OBS outputs in the selected scene collection.

## Configuration

`/etc/galaxy/galaxy.env`, defaults and examples in [`.env.example`](.env.example).

| Key | Meaning |
|---|---|
| `PC_HOST`, `PC_MAC`, `PC_BROADCAST` | PC address, MAC for Wake-on-LAN, subnet broadcast |
| `PC_SSH` | `user@host` for sleep, shutdown and restart (needs OpenSSH server and a key on the PC) |
| `SUNSHINE_APP`, `APPS` | default app and the list offered in the page |
| `SUNSHINE_USER`, `SUNSHINE_PASS`, `SUNSHINE_UI_PORT` | Sunshine web login, used to switch the screen |
| `DISPLAYS` | `name={device id}` pairs; the ids are in the Sunshine log under "Currently available display devices" |
| `DISPLAY_RES` | `name=WxH` stream resolution per screen |
| `OBS_ENABLED`, `OBS_PASS`, `OBS_PORT`, `OBS_PROFILE`, `OBS_BITRATE`, `OBS_FPS` | OBS source |
| `SRT_PORT`, `PI_HOST` | SRT listener port; the Pi's address as seen from the PC (detected when empty) |
| `TV_CEC`, `TV_OFF_ON_STOP`, `CEC_DEVICE`, `BOOT_WAIT` | CEC control (`CEC_DEVICE` is the `/dev/cecN` of the HDMI port in use), seconds to wait for the PC |
| `MOONLIGHT_ARGS` | extra Moonlight options |
| `API_BIND`, `API_PORT`, `API_TOKEN` | HTTP API; set `API_BIND` to the Pi's LAN address to avoid listening on every interface |

## CLI

```
python3 -m galaxy connect [--source NAME] [--audio both|tv|pc] [--app NAME]
python3 -m galaxy stop
python3 -m galaxy status
python3 -m galaxy wake
python3 -m galaxy tv on|off
python3 -m galaxy power sleep|shutdown|restart
python3 -m galaxy set KEY
python3 -m galaxy pair
```

`connect` replaces a running session. `stop` stops the picture and puts the TV in standby when `TV_OFF_ON_STOP` is true.

## HTTP API

Plain HTTP with `Authorization: Bearer <API_TOKEN>`; keep it on the home network. Only one action runs at a time: a second one gets `409`. Invalid options get `400`.

| Method | Path | Action |
|---|---|---|
| GET | `/` | the control page |
| GET | `/v1/status` | phase, PC and stream state, current source, app and sound, available choices |
| POST | `/v1/connect` | body `{"source","app","audio"}`, starts or replaces a session |
| POST | `/v1/stop` | stop the session |
| POST | `/v1/wake` | Wake-on-LAN |
| POST | `/v1/tv/on`, `/v1/tv/off` | TV power |
| POST | `/v1/sleep`, `/v1/shutdown`, `/v1/restart` | PC power over SSH |

## Notes

- The desktop portal services are masked for the user: Moonlight waits for them on every start, which delayed it by more than a minute on a Pi without a desktop.
- The player units clear the inheritable capability set with `setpriv`, because the login session grants one and Flatpak's sandbox refuses to start with it.
- After a stop the login prompt returns on tty1; with `TV_OFF_ON_STOP=true` the TV is off anyway.
- `sleep` uses `SetSuspendState`, which hibernates if hibernation is enabled in Windows.
- Wi-Fi is enough for 1080p60; a cable gives lower latency for games.

## License

MIT, see [LICENSE](LICENSE).
