# Galaxy

Automated Moonlight streaming launcher triggered by a physical button on a Raspberry Pi with LED feedback.

---

## Features

- Powers on your TV via HDMI-CEC
- Sends Wake-on-LAN to your gaming PC
- Starts Moonlight streaming in Steam Big Picture mode
- Button toggles stream on/off
- LED blinks during start/stop phases
- Logs all actions for debugging
- PID tracking to avoid double runs

---

## Setup

1. Clone this repo and `cd galaxy`.

2. Copy `.env.example` to `.env` and edit your setup variables:

```bash
cp .env.example .env
nano .env
````

3. Run the setup script:

```bash
chmod +x setup.sh
./setup.sh
```

4. Verify the systemd service:

```bash
sudo systemctl status moonlight-button.service
```

5. Connect your button to GPIO pin from `.env` (default 17) and an LED to the LED GPIO (default 27).

6. Press the button to toggle stream and LED feedback.

---

## Troubleshooting

* If the stream doesn't start, check `logs.log` for errors.
* Ensure WoL is enabled on your PC network adapter.
* Verify TV CEC name matches your device.
* Use `journalctl -u moonlight-button.service` for service logs.

---

## License

MIT License
