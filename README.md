# 🌌 Galaxy

<div align="center">
  
**Automated Moonlight streaming launcher with physical button control for Raspberry Pi**

![GitHub stars](https://img.shields.io/github/stars/kami-tsuki/galaxy?style=flat-square)
![GitHub license](https://img.shields.io/github/license/kami-tsuki/galaxy?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi-brightgreen?style=flat-square)
![Python](https://img.shields.io/badge/python-3.7%2B-blue?style=flat-square)

*Transform your Raspberry Pi into a one-button gaming console controller*

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [The Problem & Solution](#-the-problem--solution)
- [Features](#-features)
- [Hardware Requirements](#-hardware-requirements)
- [Hardware Setup](#-hardware-setup)
- [Software Requirements](#-software-requirements)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [File Structure](#-file-structure)
- [Service Management](#-service-management)
- [Customization](#-customization)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🎯 Overview

Galaxy is an IoT solution that transforms your Raspberry Pi into a smart gaming hub controller. With a single button press, it orchestrates your entire gaming setup: powers on your TV, wakes up your gaming PC, and launches Moonlight streaming - creating a console-like experience for PC gaming.

## 🔧 The Problem & Solution

### The Problem
Modern PC gaming setups often involve multiple steps to start a gaming session:
- Manually turning on the TV
- Waking up the gaming PC
- Launching streaming software
- Configuring display settings
- Managing multiple remotes and inputs

### The Solution
Galaxy automates this entire workflow into a single button press, providing:
- **Seamless Integration**: One button controls your entire gaming ecosystem
- **Physical Interface**: Dedicated hardware button for reliable control
- **Smart Power Management**: Automatic TV and PC power control
- **Visual Feedback**: LED indicators for system status
- **Reliability**: Process monitoring and error recovery

## ✨ Features

- 🔌 **Smart TV Control**: Powers on/off TV via HDMI-CEC commands
- 💻 **PC Wake Management**: Sends Wake-on-LAN packets to boot your gaming PC
- 🎮 **Moonlight Integration**: Automatically launches game streaming
- 🔘 **One-Button Operation**: Simple press to start/stop entire gaming session
- 💡 **LED Feedback**: Visual status indicators with different blink patterns
- 📊 **Comprehensive Logging**: Detailed logs for debugging and monitoring
- 🔒 **Process Protection**: PID tracking prevents multiple instances
- 🔄 **Auto-Recovery**: Systemd service ensures reliability
- ⚡ **Fast Response**: Optimized timing for quick startup

## 🛠 Hardware Requirements

### Essential Components
- **Raspberry Pi** (3B+ or newer recommended)
- **MicroSD Card** (16GB+ Class 10)
- **Momentary Push Button** (normally open)
- **LED** (any color, 3mm or 5mm)
- **Resistors**:
  - 10kΩ (pull-down for button)
  - 220Ω (current limiting for LED)
- **Breadboard and Jumper Wires**

### Optional Enhancements
- **Enclosure** for clean installation
- **Tactile switch** for better feel
- **Status LED in different color**

## 🔌 Hardware Setup

### Wiring Diagram

```
Raspberry Pi GPIO Layout:
┌─────────────────────────────────┐
│  3V3  (1) (2)  5V               │
│  GPIO2(3) (4)  5V               │
│  GPIO3(5) (6)  GND              │
│  GPIO4(7) (8)  GPIO14           │
│  GND  (9) (10) GPIO15           │
│  GPIO17(11)(12) GPIO18          │  ← Button GPIO (default)
│  GPIO27(13)(14) GND             │  ← LED GPIO (default)
│  GPIO22(15)(16) GPIO23          │
│  3V3 (17)(18) GPIO24           │
│  GPIO10(19)(20) GND             │
│  GPIO9(21)(22) GPIO25           │
│  GPIO11(23)(24) GPIO8           │
│  GND (25)(26) GPIO7             │
└─────────────────────────────────┘
```

### Button Wiring
```
[3.3V] ──── [10kΩ Resistor] ──── [GPIO 17] ──── [Button] ──── [GND]
```

### LED Wiring
```
[GPIO 27] ──── [220Ω Resistor] ──── [LED Anode] ──── [LED Cathode] ──── [GND]
```

### Step-by-Step Assembly

1. **Power off** your Raspberry Pi
2. **Connect the button**:
   - One terminal to GPIO 17 (pin 11)
   - Other terminal to GND (pin 9)
   - Add 10kΩ pull-down resistor between GPIO 17 and GND
3. **Connect the LED**:
   - Anode (longer leg) to GPIO 27 (pin 13) via 220Ω resistor
   - Cathode (shorter leg) to GND (pin 14)
4. **Double-check connections** before powering on

## 💻 Software Requirements

### Gaming PC Setup
Your gaming PC needs to be configured for remote streaming and wake-on-LAN.

#### Sunshine (Game Streaming Host)
**Sunshine** is the open-source game streaming host that runs on your PC.

📎 **Links:**
- [Sunshine GitHub](https://github.com/LizardByte/Sunshine)
- [Sunshine Documentation](https://docs.lizardbyte.dev/projects/sunshine/en/latest/)
- [Download Latest Release](https://github.com/LizardByte/Sunshine/releases)

**Installation:**
1. Download and install Sunshine on your gaming PC
2. Configure apps in Sunshine web interface (usually `https://localhost:47990`)
3. Add "Steam Big Picture" or your preferred gaming launcher
4. Note down your PC's IP address and MAC address

#### Wake-on-LAN Setup
1. **BIOS Settings**:
   - Enable "Wake on LAN" or "Power on by PCIe device"
   - Enable "ErP Ready" (may need to be disabled)

2. **Network Adapter Settings** (Windows):
   ```
   Device Manager → Network Adapters → Right-click your adapter → Properties
   → Power Management → ✓ Allow this device to wake the computer
   → Advanced → Wake on Magic Packet → Enabled
   ```

3. **Test WoL**:
   ```bash
   wakeonlan YOUR_PC_MAC_ADDRESS
   ```

### Raspberry Pi Setup
#### Moonlight Client
**Moonlight** is the streaming client that receives the game stream.

📎 **Links:**
- [Moonlight Official Site](https://moonlight-stream.org/)
- [Moonlight GitHub](https://github.com/moonlight-stream)
- [Moonlight Qt (Recommended)](https://github.com/moonlight-stream/moonlight-qt)

**Installation:**
```bash
# Add Moonlight repository
echo 'deb http://archive.itimmer.nl/raspbian/moonlight buster main' | sudo tee /etc/apt/sources.list.d/moonlight.list
wget -qO - http://archive.itimmer.nl/raspbian/moonlight/public.key | sudo apt-key add -
sudo apt update
sudo apt install moonlight-qt
```

#### CEC-Utils for TV Control
```bash
sudo apt install cec-utils
```

## 🚀 Installation

### Quick Start
```bash
# Clone the repository
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy

# Copy and edit configuration
cp .env.example .env
nano .env

# Run automated setup
chmod +x setup.sh
./setup.sh
```

### Manual Installation
If you prefer manual setup or need to customize the installation:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip cec-utils wakeonlan python3-gpiozero git

# Install Python packages
pip3 install python-dotenv

# Clone repository
git clone https://github.com/kami-tsuki/galaxy.git
cd galaxy

# Set permissions
chmod +x launch-game.sh
chmod +x setup.sh

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Install systemd service
sudo cp moonlight-button.service /etc/systemd/system/
# Edit service file paths
sudo systemctl daemon-reload
sudo systemctl enable moonlight-button.service
sudo systemctl start moonlight-button.service
```

## ⚙️ Configuration

### Environment Variables (.env)

The `.env` file contains all configuration parameters for your setup:

```bash
# TV Configuration
TV_CEC_NAME=TV                          # CEC name of your TV (usually "TV" or "0")

# Gaming PC Configuration  
PC_MAC=XX:YY:XX:YY:XX:YY                # MAC address of your gaming PC's network adapter
MOONLIGHT_HOST=192.168.x.y              # IP address of your gaming PC
MOONLIGHT_APP="Steam Big Picture"       # App name configured in Sunshine

# Hardware Configuration
BUTTON_GPIO=17                          # GPIO pin for the button (BCM numbering)
LED_GPIO=27                             # GPIO pin for the LED (BCM numbering)

# System Paths
LOG_FILE=/home/<usr>/galaxy/logs.log    # Path to log file
PID_FILE=/home/<usr>/galaxy/launch-game.pid  # Path to PID file for process tracking
```

### Finding Your Configuration Values

#### PC MAC Address
```bash
# On Windows
ipconfig /all | findstr "Physical Address"

# On Linux
ip link show | grep "link/ether"

# On macOS  
ifconfig | grep "ether"
```

#### PC IP Address
```bash
# On Windows
ipconfig | findstr "IPv4"

# On Linux/macOS
ip addr show | grep "inet "
```

#### TV CEC Name
```bash
# Test CEC communication
echo "scan" | cec-client -s -d 1
```

## 📁 File Structure

```
galaxy/
├── 📄 README.md                    # This documentation
├── 📄 LICENSE                      # MIT License
├── ⚙️ .env                         # Your configuration (create from .env.example)
├── ⚙️ .env.example                 # Configuration template
├── 🐍 button-handler.py            # Main Python service
├── 📜 launch-game.sh               # Streaming workflow script
├── 🔧 setup.sh                     # Automated installation script
├── 🔧 moonlight-button.service     # Systemd service definition template
├── 🧪 test-button-led.py           # Hardware testing utility
├── 📊 logs.log                     # Runtime logs (created automatically)
└── 📋 launch-game.pid              # Process ID file (created automatically)
```

### File Explanations

#### `button-handler.py` - Main Service
The core Python service that handles button presses and LED control.

**Key Functions:**
- `is_running()`: Checks if Moonlight stream is active via PID file
- `on_button_press()`: Main event handler for button presses
- **LED Patterns**:
  - Slow blink (0.5s): Starting stream
  - Fast blink (0.1s): Stopping stream
  - Solid off: Idle state

**Dependencies:**
- `gpiozero`: Hardware GPIO control
- `python-dotenv`: Environment variable loading
- `subprocess`: External command execution
- `logging`: Custom formatted logging

#### `launch-game.sh` - Streaming Controller
Bash script that orchestrates the streaming workflow.

**Start Sequence:**
1. Powers on TV via CEC command
2. Sends Wake-on-LAN packet to PC
3. Waits 30 seconds for PC boot
4. Launches Moonlight with specified app
5. Saves process PID for tracking

**Stop Sequence:**
1. Kills Moonlight process
2. Powers off TV via CEC
3. Cleans up PID file

#### `setup.sh` - Installation Automation
Automated setup script that:
- Updates system packages
- Installs required dependencies
- Sets file permissions
- Configures systemd service
- Starts the service

#### `moonlight-button.service` - Systemd Service
Service definition for automatic startup and management.

**Configuration:**
```ini
[Unit]
Description=Moonlight Button Handler    # Service description
After=network.target                   # Start after network is ready

[Service]  
User=tsuki                            # Run as specific user
ExecStart=/usr/bin/python3 /path/to/galaxy/button-handler.py  # Command to run
Restart=on-failure                    # Auto-restart on crash
WorkingDirectory=/path/to/galaxy      # Working directory
Environment="XDG_RUNTIME_DIR=/run/user/1000"  # Environment variables

[Install]
WantedBy=multi-user.target           # Enable for multi-user mode
```

#### `test-button-led.py` - Hardware Tester
Simple test script to verify hardware connections:
- Press button → LED blinks 5 times
- Useful for debugging hardware issues
- Run before main service installation

## 🔧 Service Management

### Systemd Service Commands

```bash
# Check service status
sudo systemctl status moonlight-button.service

# Start service
sudo systemctl start moonlight-button.service

# Stop service  
sudo systemctl stop moonlight-button.service

# Restart service
sudo systemctl restart moonlight-button.service

# Enable auto-start on boot
sudo systemctl enable moonlight-button.service

# Disable auto-start
sudo systemctl disable moonlight-button.service

# View service logs
sudo journalctl -u moonlight-button.service

# Follow service logs in real-time
sudo journalctl -u moonlight-button.service -f
```

### Service Configuration Customization

To customize the service, edit `/etc/systemd/system/moonlight-button.service`:

```bash
sudo nano /etc/systemd/system/moonlight-button.service
```

**Common Customizations:**

1. **Change User:**
   ```ini
   User=pi  # Change from 'pi' to your username
   ```

2. **Add Environment Variables:**
   ```ini
   Environment="DISPLAY=:0"
   Environment="PULSE_SERVER=unix:/run/user/1000/pulse/native"
   ```

3. **Modify Restart Behavior:**
   ```ini
   Restart=always                    # Always restart
   RestartSec=10                     # Wait 10 seconds before restart
   ```

4. **Add Dependencies:**
   ```ini
   After=network.target graphical.target
   Wants=graphical.target
   ```

After editing, reload the service:
```bash
sudo systemctl daemon-reload
sudo systemctl restart moonlight-button.service
```

## 🎨 Customization

### Timing Adjustments

#### Boot Wait Time
Edit `launch-game.sh` to adjust PC boot wait time:
```bash
# Change from 30 seconds to your preference
log "INFO" "Waiting for PC to boot (45s)..."
sleep 45
```

#### LED Blink Patterns
Modify `button-handler.py` LED timing:
```python
# Slow blink for starting (current: 0.5s on/off)
led.blink(on_time=1.0, off_time=0.5)

# Fast blink for stopping (current: 0.1s on/off)  
led.blink(on_time=0.05, off_time=0.05)
```

### GPIO Pin Changes
1. **Update `.env` file:**
   ```bash
   BUTTON_GPIO=18  # New button pin
   LED_GPIO=22     # New LED pin
   ```

2. **Rewire hardware** to match new pins

3. **Restart service:**
   ```bash
   sudo systemctl restart moonlight-button.service
   ```

### Adding Multiple Apps
Modify `launch-game.sh` to support app selection:
```bash
# Add app parameter support
APP_NAME="${1:-$MOONLIGHT_APP}"
moonlight stream -app "$APP_NAME" "$MOONLIGHT_HOST"
```

### Custom CEC Commands
Add custom TV commands in `launch-game.sh`:
```bash
# Switch to specific HDMI input
/usr/bin/cec-client -s -d 1 <<< "tx 40:82:31:00"  # HDMI 1
/usr/bin/cec-client -s -d 1 <<< "tx 40:82:32:00"  # HDMI 2
```

## 🔍 Troubleshooting

### Real-Time Monitoring

#### Application Logs
Monitor Galaxy's detailed logs:
```bash
# View recent logs
tail -n 50 /home/<usr>/galaxy/logs.log

# Follow logs in real-time
tail -f /home/<usr>/galaxy/logs.log

# Search for specific events
grep "ERROR" /home/<usr>/galaxy/logs.log
grep "Button pressed" /home/<usr>/galaxy/logs.log
```

#### Service Logs
Monitor systemd service status:
```bash
# View recent service logs
sudo journalctl -u moonlight-button.service -n 50

# Follow service logs in real-time
sudo journalctl -u moonlight-button.service -f

# View logs since last boot
sudo journalctl -u moonlight-button.service -b

# Filter by priority (error, warning, info)
sudo journalctl -u moonlight-button.service -p err
```

### Common Issues & Solutions

#### 🔘 Button Not Responding
**Symptoms:** No LED activity when button is pressed

**Diagnosis:**
```bash
# Test hardware connections
cd /home/<usr>/galaxy
python3 test-button-led.py
```

**Solutions:**
1. **Check wiring** - Verify GPIO connections
2. **Check pull-down resistor** - Ensure 10kΩ resistor is present
3. **Test GPIO pin:**
   ```bash
   # Test button pin manually
   gpio -g mode 17 in
   gpio -g read 17  # Should show 0, then 1 when pressed
   ```

#### 💡 LED Not Working
**Symptoms:** Button works but no LED feedback

**Solutions:**
1. **Check LED polarity** - Ensure anode to GPIO, cathode to GND
2. **Check resistor** - Verify 220Ω current limiting resistor
3. **Test LED manually:**
   ```bash
   # Turn LED on manually
   gpio -g mode 27 out
   gpio -g write 27 1  # LED should turn on
   gpio -g write 27 0  # LED should turn off
   ```

#### 📺 TV Not Responding to CEC
**Symptoms:** Logs show CEC commands but TV doesn't respond

**Diagnosis:**
```bash
# Test CEC connectivity
echo "scan" | cec-client -s -d 1
echo "pow 0" | cec-client -s -d 1  # Power on TV
```

**Solutions:**
1. **Enable CEC on TV** - Check TV settings for "HDMI Control" or "CEC"
2. **Check HDMI cable** - Must support CEC (most modern cables do)
3. **Try different CEC address:**
   ```bash
   # In .env file
   TV_CEC_NAME=0  # Instead of "TV"
   ```

#### 💻 PC Not Waking Up
**Symptoms:** WoL packet sent but PC doesn't boot

**Diagnosis:**
```bash
# Test WoL manually
wakeonlan xx:yy:xx:yy:xx:yy
```

**Solutions:**
1. **BIOS Settings:**
   - Enable "Wake on LAN"
   - Disable "ErP Ready" if present
   - Enable "Power on by PCIe"

2. **Network Adapter Settings** (Windows):
   - Device Manager → Network Adapter → Properties
   - Power Management → ✓ "Allow this device to wake the computer"
   - Advanced → "Wake on Magic Packet" → Enabled

3. **Check MAC address:**
   ```bash
   # Verify correct MAC in .env
   arp -a | grep YOUR_PC_IP
   ```

#### 🎮 Moonlight Not Starting
**Symptoms:** PC wakes up but stream doesn't start

**Diagnosis:**
```bash
# Test Moonlight manually
moonlight list 192.168.x.y  # List available apps
moonlight stream -app "Steam Big Picture" 192.168.x.y
```

**Solutions:**
1. **Sunshine Configuration:**
   - Verify Sunshine is running on PC
   - Check app name matches exactly
   - Ensure PC firewall allows Sunshine

2. **Network Issues:**
   - Verify PC IP address in `.env`
   - Check network connectivity: `ping 192.168.x.y`
   - Ensure both devices on same network

3. **Pairing Issues:**
   ```bash
   # Re-pair devices
   moonlight pair 192.168.x.y
   ```

#### 🔄 Service Keeps Restarting
**Symptoms:** Service shows "failed" or constantly restarting

**Diagnosis:**
```bash
# Check detailed service status
sudo systemctl status moonlight-button.service -l

# View full service logs
sudo journalctl -u moonlight-button.service --no-pager
```

**Solutions:**
1. **Fix file paths** in service file:
   ```bash
   sudo nano /etc/systemd/system/moonlight-button.service
   # Update paths to match your installation
   ```

2. **Check permissions:**
   ```bash
   ls -la /home/<usr>/galaxy/button-handler.py
   chmod +x /home/<usr>/galaxy/button-handler.py
   ```

3. **Python environment issues:**
   ```bash
   # Test Python script manually
   cd /home/<usr>/galaxy
   python3 button-handler.py
   ```

### Log Analysis Examples

#### Successful Start Sequence
```
[dt] [INFO] [ButtonHandler] Button pressed! Triggering actions.
[dt] [INFO] [ButtonHandler] Stream is not running. Starting it.
[dt] [INFO] [LaunchGame] Starting launch sequence
[dt] [INFO] [LaunchGame] Powering on TV...
[dt] [INFO] [LaunchGame] Sending Wake-on-LAN...
[dt] [INFO] [LaunchGame] Waiting for PC to boot (30s)...
[dt] [INFO] [LaunchGame] Starting Moonlight stream...
```

#### Error Example
```
[dt] [ERROR] [ButtonHandler] Error running launch-game: Command 'moonlight' failed
[dt] [INFO] [LaunchGame] PC may not be ready yet, try increasing boot wait time
```

### Performance Monitoring

#### Resource Usage
```bash
# Check CPU and memory usage
top -p $(pgrep -f button-handler)

# Monitor GPIO activity
watch -n 1 'gpio readall | grep -E "(17|27)"'
```

#### Network Monitoring
```bash
# Monitor network traffic during streaming
sudo tcpdump -i eth0 host 192.168.x.y

# Check WoL packet transmission  
sudo tcpdump -i eth0 port 9
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes
4. Test thoroughly on Raspberry Pi hardware
5. Commit your changes: `git commit -m 'Add amazing feature'`
6. Push to the branch: `git push origin feature/amazing-feature`
7. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with ❤️ for the gaming community**

*If this project helped you, please consider giving it a ⭐!*

</div>
