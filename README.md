# Galaxy

Control a gaming PC from a Raspberry Pi that is connected to a TV. Open the web page, pick a screen, an app and the sound, press Connect. Galaxy wakes the PC, switches the TV on, selects the screen in Sunshine and starts a Moonlight session on the TV.

The old GPIO button and LED version is archived in [`legacy/`](legacy).

## How it works

```
PC (Windows)                          Pi 5 (Raspberry Pi OS Trixie)              TV
Sunshine  <---- Moonlight stream ----  cage + Moonlight (Flatpak)  --HDMI-->   screen, sound, CEC power
OBS (optional, WebSocket)              galaxy.py: web page, API and CLI on :8787
```

| File | Role |
|---|---|
| `galaxy.py` | CLI and HTTP API |
| `web/index.html` | the control page |
| `galaxy.service` | runs the API on the Pi |
| `galaxy-stream.service` | runs `cage` with Moonlight on tty1, started and stopped by Galaxy |
| `setup.sh` | installs and updates everything on the Pi, safe to re-run |

## Requirements

- Raspberry Pi 5 (or 4) with Raspberry Pi OS Trixie, connected to the TV over HDMI
- Windows PC with [Sunshine](https://github.com/LizardByte/Sunshine) (`winget install LizardByte.Sunshine`)
- Wake-on-LAN enabled on the PC (BIOS and network adapter) if it should be woken
- Optional: OBS with its WebSocket server enabled

## Install on the Pi

```
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy
./setup.sh
sudo nano /etc/galaxy/galaxy.env
python3 galaxy.py set SUNSHINE_USER
python3 galaxy.py set SUNSHINE_PASS
python3 galaxy.py pair
```

`setup.sh` installs `cage`, Flatpak, Moonlight and `cec-utils`, creates `/etc/galaxy/galaxy.env` with a generated `API_TOKEN` (or adds missing keys to an existing one), installs both units, a sudoers rule limited to starting and stopping the stream unit, and enables lingering for the user.

`pair` asks Moonlight to pair with the PC and waits. Enter the PIN in the Sunshine web UI under **PIN**. To choose the PIN yourself run Moonlight directly with `pair <pc-ip> --pin 4821`.

Secrets are stored with `galaxy.py set KEY` (`SUNSHINE_USER`, `SUNSHINE_PASS`, `OBS_PASS`, `API_TOKEN`). The value is typed without echo and written to the root-owned env file.

Open `http://<pi-ip>:8787/#token=<API_TOKEN>` once in a browser; the page stores the token and removes it from the address bar. Give the Pi and the PC fixed addresses in the router.

## Using the page

- **Screen to share**: the screens from `DISPLAYS`, plus `obs` when `OBS_PASS` is set.
- **What to show**: the apps from `APPS`, which must exist in Sunshine.
- **Sound**: `PC + TV`, `TV only` or `PC only`.
- **Connect**: wakes the PC if needed, switches the TV on, selects the screen, starts the stream. While connected the button reads **Disconnect**, or **Apply changes** after you change a choice.

The page shows the real state reported by the Pi, so a second browser or a reload always agrees with what is running.

## Screens and resolution

Sunshine captures one screen at a time. Galaxy sets `output_name` through the Sunshine API (keeping all other Sunshine settings) and restarts Sunshine only when the screen actually changes.

Each screen has a stream resolution in `DISPLAY_RES`, so the picture keeps its proportions. A 32:9 monitor is streamed at `3840x1080` and appears with bars above and below on a 16:9 TV; a 1080p screen is streamed at `1920x1080`.

`obs` selects the screen named `tv`, starts the OBS virtual camera and opens an OBS program projector on `OBS_MONITOR`. Sunshine captures screens only, so the OBS output reaches the stream through that projector. `OBS_MONITOR` is OBS's own monitor index, which can differ from the Windows display order. OBS cannot close a projector over its API: close the window in OBS yourself, or leave it. Switching to another screen stops the virtual camera.

## Sound

Moonlight runs on the Pi with ALSA directly (no sound server), writing to `AUDIO_DEVICE`, the HDMI port the TV is on. The connected port shows a monitor name in `/proc/asound/cardN/eld#0.0`.

| Mode | Pi (TV) | PC speakers |
|---|---|---|
| `both` | plays | plays |
| `tv` | plays | muted by Moonlight |
| `pc` | silent | plays |

The chosen mode is written for each session to `/run/user/<uid>/galaxy-session.env`; `AUDIO_FLAGS`, `AUDIO_DRIVER` and `RESOLUTION_FLAGS` in `galaxy.env` are only the defaults for a manual start.

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
| `OBS_PASS`, `OBS_PORT`, `OBS_MONITOR` | OBS WebSocket password, port and projector monitor |
| `TV_CEC`, `TV_OFF_ON_STOP`, `CEC_DEVICE` | CEC control; `CEC_DEVICE` is the `/dev/cecN` of the HDMI port in use |
| `MOONLIGHT_ARGS` | extra Moonlight options such as `--video-codec HEVC --fps 60` |
| `AUDIO_DEVICE` | ALSA device for the TV, for example `plughw:CARD=vc4hdmi1,DEV=0` |
| `API_BIND`, `API_PORT`, `API_TOKEN` | HTTP API; set `API_BIND` to the Pi's LAN address to avoid listening on every interface |

## CLI

```
galaxy.py start [--display NAME] [--audio both|tv|pc] [--app NAME]
galaxy.py stop
galaxy.py status
galaxy.py display [NAME]
galaxy.py wake
galaxy.py tv on|off
galaxy.py sleep|shutdown|restart
galaxy.py set KEY
galaxy.py pair
```

`start` with options replaces a running session. `stop` stops the stream and puts the TV in standby when `TV_OFF_ON_STOP` is true.

## HTTP API

Plain HTTP with `Authorization: Bearer <API_TOKEN>`; keep it on the home network. Only one action runs at a time: a second one gets `409`. Invalid options get `400`.

| Method | Path | Action |
|---|---|---|
| GET | `/` | the control page |
| GET | `/v1/status` | phase, PC and stream state, current screen, app and sound, available choices |
| POST | `/v1/connect` | body `{"display","app","audio"}`, starts or replaces a session |
| POST | `/v1/start?display=&app=&audio=` | like the CLI `start` |
| POST | `/v1/stop` | stop the session |
| POST | `/v1/display/NAME` | select the screen |
| POST | `/v1/wake` | Wake-on-LAN |
| POST | `/v1/tv/on`, `/v1/tv/off` | TV power |
| POST | `/v1/sleep`, `/v1/shutdown`, `/v1/restart` | PC power over SSH |

## Notes

- The stream unit clears the inheritable capability set with `setpriv`, because the login session grants one and Flatpak's sandbox refuses to start with it.
- After a stop the login prompt returns on tty1; with `TV_OFF_ON_STOP=true` the TV is off anyway.
- `sleep` uses `SetSuspendState`, which hibernates if hibernation is enabled in Windows.
- Wi-Fi is enough for 1080p60; a cable gives lower latency for games.

## License

MIT, see [LICENSE](LICENSE).
