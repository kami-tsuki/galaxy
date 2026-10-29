# Galaxy

Control a gaming PC from a Raspberry Pi that is connected to a TV. Galaxy wakes the PC, switches the TV on, picks which screen to stream and starts a Moonlight session to the TV. It is driven by a CLI, a small HTTP API and a web page on the Pi.

The old GPIO button and LED version is archived in [`legacy/`](legacy).

## How it works

```
PC (Windows)                         Pi 5 (Raspberry Pi OS Trixie)             TV
Sunshine  <---- Moonlight stream ----  cage + Moonlight (Flatpak)  --HDMI-->  Philips
OBS (optional, websocket)              galaxy.py (CLI + API on :8787)         CEC power
```

| Part | Role |
|---|---|
| `galaxy.py` | CLI and API: start, stop, status, wake, TV power, display selection, PC power |
| `galaxy.service` | runs the API on the Pi |
| `galaxy-stream.service` | runs `cage` with Moonlight on the TV (tty1), started and stopped by Galaxy |
| `setup.sh` | installs everything on the Pi |
| `set-sunshine.sh` | stores the Sunshine login on the Pi without echoing it |

## Requirements

- Raspberry Pi 5 with Raspberry Pi OS Trixie (also works on Pi 4), connected to the TV over HDMI
- Windows PC with [Sunshine](https://github.com/LizardByte/Sunshine) (`winget install LizardByte.Sunshine`) and an NVIDIA, AMD or Intel encoder
- Wake-on-LAN enabled on the PC (BIOS and network adapter) if the PC should be woken
- Optional: OBS with the built-in WebSocket server

## Install on the Pi

```
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy
./setup.sh
sudo nano /etc/galaxy/galaxy.env
./set-sunshine.sh
python3 galaxy.py pair
```

`setup.sh` installs `cage`, Flatpak, Moonlight and `cec-utils`, writes `/etc/galaxy/galaxy.env` with a generated API token, installs both units, adds a sudoers rule limited to starting and stopping the stream unit, and enables lingering for the user.

Pairing: `galaxy.py pair` waits for a PIN. Enter it in the Sunshine web UI under **PIN**. The default PIN used by the pairing command is set with `--pin` when you run Moonlight directly:

```
flatpak run --env=QT_QPA_PLATFORM=offscreen com.moonlight_stream.Moonlight pair <pc-ip> --pin 4821
```

## Configuration

`/etc/galaxy/galaxy.env` (a local `.env` next to `galaxy.py` is also read). Defaults are in [`.env.example`](.env.example).

| Key | Meaning |
|---|---|
| `PC_HOST`, `PC_MAC`, `PC_BROADCAST` | PC address, MAC for Wake-on-LAN, subnet broadcast |
| `PC_SSH` | `user@host` for sleep, shutdown, restart and lock (needs OpenSSH server and a key on the PC) |
| `SUNSHINE_APP` | Sunshine app to stream, for example `Desktop` or `Steam Big Picture` |
| `SUNSHINE_USER`, `SUNSHINE_PASS`, `SUNSHINE_UI_PORT` | Sunshine web login, used to switch the captured display |
| `DISPLAYS` | `name={device id}` pairs; the device ids are in the Sunshine log under "Currently available display devices" |
| `OBS_PASS`, `OBS_PORT`, `OBS_MONITOR` | OBS WebSocket password and port; monitor index where the OBS projector opens |
| `TV_CEC`, `TV_OFF_ON_STOP`, `CEC_DEVICE` | CEC control; `CEC_DEVICE` is the `/dev/cecN` node of the HDMI port used |
| `MOONLIGHT_ARGS` | Moonlight options; `--audio-on-host` keeps the PC speakers playing while the TV also gets sound |
| `AUDIO_DEVICE` | ALSA device for the TV, for example `plughw:CARD=vc4hdmi1,DEV=0`; the connected HDMI port shows a monitor name in `/proc/asound/cardN/eld#0.0` |
| `API_BIND`, `API_PORT`, `API_TOKEN` | HTTP API |

## Usage

```
galaxy.py start [--display NAME]
galaxy.py stop
galaxy.py status
galaxy.py display [NAME]
galaxy.py wake
galaxy.py tv on|off
galaxy.py sleep|shutdown|restart|lock
```

`start` switches the TV on, wakes the PC if Sunshine does not answer, then starts the stream unit. `stop` stops the stream and puts the TV in standby.

`display NAME` writes `output_name` through the Sunshine API and restarts Sunshine, so run it before `start`, or use `start --display NAME`. Choices come from `DISPLAYS`; with `OBS_PASS` set there is also `obs`, which selects the `tv` display, starts the OBS virtual camera and opens an OBS program projector on `OBS_MONITOR`. Sunshine captures screens only, so the virtual camera content reaches the stream through that projector.

## HTTP API

Open `http://<pi-ip>:8787` for the web page. The API needs `Authorization: Bearer <API_TOKEN>`.

| Method | Path | Action |
|---|---|---|
| GET | `/v1/status` | phase, PC state, stream state, current display, available displays |
| POST | `/v1/start?display=NAME` | start a session |
| POST | `/v1/stop` | stop the session |
| POST | `/v1/display/NAME` | select the captured display |
| POST | `/v1/wake` | send Wake-on-LAN |
| POST | `/v1/tv/on`, `/v1/tv/off` | TV power |
| POST | `/v1/sleep`, `/v1/shutdown`, `/v1/restart`, `/v1/lock` | PC power over SSH |

## Notes

- Moonlight runs inside `cage` on tty1. The stream unit clears the inheritable capability set with `setpriv`, because the login session grants one and Flatpak's sandbox refuses to start with it.
- The Pi has no sound server, so Moonlight uses ALSA directly. ALSA's default is the first HDMI port, which is often not the one with the TV, hence `AUDIO_DEVICE`.
- Wi-Fi is enough for 1080p60 but a cable gives lower latency for games.
- Give the Pi and the PC fixed addresses in the router.

## License

MIT, see [LICENSE](LICENSE).
