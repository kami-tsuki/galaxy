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
LOG_FILE=/home/<usr>/galaxy/logs.log    # Path to main log file
PID_FILE=/home/<usr>/galaxy/launch-game.pid  # Path to PID file for process tracking

# Advanced Monitoring Configuration (Optional - New in Enhanced Version)
HEALTH_CHECK_INTERVAL=30                # Health check interval in seconds (default: 30)
CONNECTION_TIMEOUT=10                   # Network connection timeout in seconds (default: 10)  
MAX_RESTART_ATTEMPTS=3                  # Maximum automatic restart attempts (default: 3)
PROCESS_CHECK_INTERVAL=5                # Process monitoring interval in seconds (default: 5)
```

### Advanced Configuration Options

The enhanced version includes additional monitoring and error handling configuration:

#### Health Monitoring Settings
```bash
# How often to perform comprehensive health checks (seconds)
HEALTH_CHECK_INTERVAL=30

# Timeout for network connectivity tests (seconds)  
CONNECTION_TIMEOUT=10

# How often to check process state (seconds)
PROCESS_CHECK_INTERVAL=5
```

#### Error Recovery Settings  
```bash
# Maximum attempts to restart failed streams before entering error state
MAX_RESTART_ATTEMPTS=3

# These settings help balance responsiveness vs system load
# Lower values = more responsive but higher CPU usage
# Higher values = less responsive but lower system impact
```

#### Performance Tuning
For different system configurations, you may want to adjust these values:

**High-Performance Systems** (Raspberry Pi 4+):
```bash
HEALTH_CHECK_INTERVAL=15    # More frequent monitoring
PROCESS_CHECK_INTERVAL=3    # Faster process checks  
CONNECTION_TIMEOUT=5        # Shorter timeouts
```

**Low-Power Systems** (Raspberry Pi 3B or older):
```bash
HEALTH_CHECK_INTERVAL=60    # Less frequent monitoring
PROCESS_CHECK_INTERVAL=10   # Slower process checks
CONNECTION_TIMEOUT=15       # Longer timeouts for slower networks
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

#### `button-handler.py` - Enhanced Main Service
The core Python service that handles button presses and LED control with comprehensive monitoring and error handling.

**Enhanced Features:**
- **State Management**: Robust state machine with 6 states (IDLE, STARTING, RUNNING, STOPPING, ERROR, UNKNOWN)
- **Health Monitoring**: Background thread performing regular system health checks
- **Process Monitoring**: Continuous monitoring of Moonlight process state
- **Connection Monitoring**: Network connectivity checks to gaming PC
- **Error Recovery**: Automatic error detection and recovery mechanisms
- **Advanced Logging**: Multi-level logging with separate error logs and thread information

**Key Functions:**
- `_health_monitor()`: Background health monitoring with PID file validation
- `_process_monitor()`: Continuous process state verification
- `_is_process_running()`: Enhanced process detection with psutil integration
- `_perform_preflight_checks()`: Pre-start validation checks
- `_handle_start_failure()`: Intelligent retry logic with backoff
- `_force_cleanup()`: Emergency cleanup for stuck processes

**LED Status Indicators:**
- **Solid Off**: System idle
- **Slow Blink** (0.5s): Starting stream sequence
- **Solid On**: Stream running successfully  
- **Fast Blink** (0.1s): Stopping stream
- **Very Fast Blink** (0.05s): Error state - check logs

**Enhanced Error Handling:**
- **GPIO Protection**: Comprehensive GPIO initialization with error recovery
- **Process Validation**: Continuous verification that PID file matches actual running process
- **Network Monitoring**: Regular connectivity checks to gaming PC
- **Resource Monitoring**: System resource usage tracking (CPU, RAM, disk)
- **Timeout Protection**: All operations have configurable timeouts
- **Automatic Cleanup**: Orphaned process detection and cleanup

**Monitoring Features:**
- **Health Checks**: Regular validation of system state every 30 seconds (configurable)
- **Process Tracking**: Real-time process state monitoring every 5 seconds (configurable)
- **Connection Testing**: Network connectivity verification to gaming PC
- **State Validation**: Automatic correction of state mismatches
- **Debouncing**: Smart button press filtering to prevent accidental triggers

**Dependencies:**
- `psutil`: Advanced process and system monitoring
- `gpiozero`: Hardware GPIO control with enhanced error handling
- `python-dotenv`: Environment variable loading
- `threading`: Background monitoring threads
- `socket`: Network connectivity testing
- `signal`: Graceful shutdown handling

**Configuration Options** (via .env):
```bash
HEALTH_CHECK_INTERVAL=30        # Health check frequency (seconds)
CONNECTION_TIMEOUT=10           # Network timeout (seconds) 
MAX_RESTART_ATTEMPTS=3          # Maximum retry attempts
PROCESS_CHECK_INTERVAL=5        # Process monitoring frequency (seconds)
```

#### `launch-game.sh` - Enhanced Streaming Controller
Advanced bash script that orchestrates the complete streaming workflow with comprehensive error handling, monitoring, and validation.

**Enhanced Features v2.0.0:**
- **Comprehensive Error Handling**: Full error recovery with detailed logging and rollback capabilities
- **Network Connectivity Testing**: Smart connectivity checks before and during operations
- **Advanced Process Management**: Graceful process termination with fallback to force-kill
- **Intelligent Boot Detection**: Dynamic PC boot detection instead of fixed wait times  
- **Retry Logic**: Configurable retry mechanisms for all network operations
- **Dependency Validation**: Automatic checking of all required system dependencies
- **Signal Handling**: Proper cleanup on script interruption or termination
- **Status Monitoring**: Comprehensive status checking and process validation

**Enhanced Start Sequence:**
1. **Pre-flight Checks**: Validates dependencies and environment configuration
2. **Process Cleanup**: Safely terminates any existing streaming processes
3. **TV Power Control**: Powers on TV via CEC with timeout and error handling
4. **Network Testing**: Tests initial PC connectivity before Wake-on-LAN
5. **Smart Wake-on-LAN**: Multiple retry attempts with packet validation
6. **Intelligent Boot Wait**: Dynamic connectivity testing during boot wait
7. **Stream Launch**: Enhanced Moonlight launch with comprehensive error capture
8. **Process Validation**: Confirms successful stream establishment

**Enhanced Stop Sequence:**
1. **Graceful Termination**: SIGTERM followed by SIGKILL if needed
2. **Orphan Cleanup**: Finds and terminates any orphaned Moonlight processes
3. **TV Power Off**: CEC standby command with error handling
4. **Resource Cleanup**: Removes temporary files and runtime directories
5. **Status Validation**: Confirms complete shutdown

**New Command Options:**
```bash
# Basic usage
./launch-game.sh start          # Start streaming
./launch-game.sh stop           # Stop streaming  
./launch-game.sh status         # Check current status

# Advanced usage with options
./launch-game.sh start --verbose    # Verbose output
./launch-game.sh start --debug      # Debug mode with detailed logging
./launch-game.sh start --dry-run    # Show what would be done
./launch-game.sh help               # Show detailed help
```

**Enhanced Error Detection:**
- **MAC Address Validation**: Regex validation of MAC address format
- **IP Address Validation**: Format checking for gaming PC IP
- **Dependency Checking**: Verification of all required commands (cec-client, wakeonlan, moonlight, ping, nc)
- **Process State Monitoring**: Continuous validation of process health
- **Network Connectivity**: Multi-layer connectivity testing (ping + port checks)
- **Resource Availability**: Checks for required files and permissions

**Smart Network Operations:**
- **Pre-Wake Testing**: Checks if PC is already awake before Wake-on-LAN
- **Connectivity Retries**: Configurable retry logic for network operations
- **Port-Specific Testing**: Tests Sunshine port (47989) availability
- **Timeout Management**: All network operations have configurable timeouts
- **Connection Validation**: Multi-step verification of PC readiness

**Advanced Logging Features:**
- **Millisecond Timestamps**: High-precision timing for debugging
- **Thread IDs**: Process identification for multi-process debugging
- **Multiple Log Levels**: DEBUG, INFO, WARN, ERROR with appropriate routing
- **Structured Output**: Consistent formatting for log parsing
- **Error Capture**: Comprehensive error output capture and logging

**Configuration Options** (via .env):
```bash
# Timing Configuration
BOOT_WAIT_TIME=30               # Maximum PC boot wait (seconds)
CONNECTION_TIMEOUT=10           # Network operation timeout
PROCESS_WAIT_TIMEOUT=60         # Process startup wait timeout

# Retry Configuration  
MAX_RETRIES=3                   # Maximum retry attempts
RETRY_DELAY=5                   # Delay between retries
WOL_RETRIES=2                   # Wake-on-LAN retry attempts

# Hardware Configuration
CEC_TIMEOUT=5                   # CEC command timeout

# Advanced Options
MOONLIGHT_EXTRA_ARGS=""         # Additional Moonlight arguments
DEBUG=false                     # Enable debug output
VERBOSE=false                   # Enable verbose output
```

**Performance Optimizations:**
- **Early PC Detection**: Skips Wake-on-LAN if PC already responsive
- **Parallel Operations**: Network tests run concurrently where possible
- **Smart Timeouts**: Adaptive timeouts based on network conditions
- **Resource Cleanup**: Automatic cleanup of temporary resources
- **Process Monitoring**: Efficient process state checking

**Dependencies:**
- `cec-client`: TV control via HDMI-CEC
- `wakeonlan`: Wake-on-LAN packet transmission
- `moonlight`: Game streaming client
- `ping`: Network connectivity testing  
- `nc` (netcat): Port-specific connectivity testing
- `ps`, `kill`: Process management
- `timeout`: Command timeout handling

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
Monitor Galaxy's detailed logs with enhanced error tracking:
```bash
# View recent logs (main log with all events)
tail -n 50 /home/<usr>/galaxy/logs.log

# Follow logs in real-time
tail -f /home/<usr>/galaxy/logs.log

# View error-only log (new feature)
tail -f /home/<usr>/galaxy/logs_errors.log

# Search for specific events
grep "ERROR" /home/<usr>/galaxy/logs.log
grep "Button pressed" /home/<usr>/galaxy/logs.log
grep "State changed" /home/<usr>/galaxy/logs.log
grep "Health check" /home/<usr>/galaxy/logs.log

# Monitor process state changes
grep "Process.*is.*healthy\|Process.*no longer exists\|PID file" /home/<usr>/galaxy/logs.log

# Check network connectivity issues  
grep "Network connectivity\|Cannot connect\|Cannot reach" /home/<usr>/galaxy/logs.log
```

#### Enhanced Log Analysis
The new logging system provides detailed information with timestamps, thread names, and context:

**Log Format:**
```
[DD.MM.YYYY HH:MM:SS.fff] [LEVEL] [ThreadName] [ButtonHandler] Message
```

**Log Levels:**
- **DEBUG**: Detailed diagnostic information
- **INFO**: General operational messages
- **WARNING**: Important issues that don't stop operation  
- **ERROR**: Serious problems requiring attention

**Key Log Patterns to Monitor:**
```bash
# System health monitoring
grep "Health check\|Resource usage\|State mismatch" logs.log

# Process management
grep "Process.*healthy\|PID file.*cleaned\|Force cleanup" logs.log

# Network issues
grep "connectivity\|Cannot reach\|timeout" logs.log

# Hardware problems
grep "GPIO\|LED.*failed\|Button" logs.log

# State transitions
grep "State changed.*→" logs.log
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

#### 🚀 Enhanced Launch Script Issues

**New Diagnostic Commands:**
```bash
# Check script status and detailed diagnostics
./launch-game.sh status --verbose

# Test script with debug output (doesn't actually run)
./launch-game.sh start --dry-run --debug

# Manual dependency check
./launch-game.sh help  # Shows all dependencies

# Test individual components
ping -c 1 192.168.x.y                    # Test PC connectivity
nc -z -w 5 192.168.x.y 47989             # Test Sunshine port
echo "scan" | cec-client -s -d 1          # Test CEC connectivity
wakeonlan xx:yy:xx:yy:xx:yy               # Test Wake-on-LAN
```

**Enhanced Error Messages:**
The enhanced script provides much more detailed error information:

```bash
# Environment validation errors:
[timestamp] [ERROR] [LaunchGame] Missing required environment variables: PC_MAC, MOONLIGHT_HOST
[timestamp] [ERROR] [LaunchGame] Invalid MAC address format: xx:yy:zz:aa:bb:cc

# Dependency errors:
[timestamp] [ERROR] [LaunchGame] Missing required dependencies: netcat-openbsd, cec-utils

# Network connectivity errors:
[timestamp] [ERROR] [LaunchGame] PC is not responding after boot sequence
[timestamp] [ERROR] [LaunchGame] Network connectivity test failed after 3 attempts

# Process management errors:
[timestamp] [ERROR] [LaunchGame] Moonlight process failed to start or exited immediately
[timestamp] [ERROR] [LaunchGame] Process 1234 died during startup (after 15s)
```

**Smart Troubleshooting Features:**
1. **Automatic Diagnostics**: Script automatically identifies common issues
2. **Detailed Error Context**: Each error includes specific remediation steps
3. **Component Testing**: Individual component validation before operations
4. **Network Path Analysis**: Multi-layer network connectivity testing
5. **Process Health Monitoring**: Continuous validation of process state

**Common Issues & Enhanced Solutions:**

**Script Fails with "Missing dependencies":**
```bash
# The script now automatically checks for:
# - cec-client, wakeonlan, moonlight, ping, nc
# Install missing dependencies:
sudo apt install cec-utils wakeonlan netcat-openbsd iputils-ping

# Check what's missing:
./launch-game.sh start --debug  # Will show specific missing commands
```

**"PC is not responding after boot sequence":**
```bash
# Enhanced diagnostics will show:
# - Whether Wake-on-LAN packets were sent successfully
# - Network connectivity test results
# - Specific timeout values and retry attempts

# Check detailed network path:
./launch-game.sh status --verbose  # Shows current PC connectivity
ping -c 5 192.168.x.y              # Manual connectivity test
nc -z -w 10 192.168.x.y 47989      # Test Sunshine specifically
```

**"Moonlight process failed to start":**
```bash
# Enhanced error capture shows exact Moonlight error:
grep "Moonlight error output" /path/to/logs.log

# Common Moonlight issues the script now detects:
# - App name not found in Sunshine
# - Network connectivity lost during launch
# - Authentication/pairing issues
# - Resource conflicts

# Test Moonlight manually:
moonlight list 192.168.x.y                    # List available apps
moonlight stream -app "Steam Big Picture" 192.168.x.y  # Manual test
```

**Performance Tuning for Enhanced Script:**
```bash
# For faster systems (reduce timeouts):
BOOT_WAIT_TIME=20               # Reduce boot wait
CONNECTION_TIMEOUT=5            # Faster network timeouts
PROCESS_WAIT_TIMEOUT=30         # Reduce process wait

# For slower systems (increase timeouts):  
BOOT_WAIT_TIME=60               # Longer boot wait
CONNECTION_TIMEOUT=15           # More patient network timeouts
MAX_RETRIES=5                   # More retry attempts

# For debugging (enable verbose logging):
DEBUG=true                      # Show all debug information
VERBOSE=true                    # Enable console output
```
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

#### 🔄 Enhanced Error States & Recovery

**Symptoms:** LED blinking very fast (0.05s) - Error state

**New Error Detection Features:**
The enhanced button handler now detects and handles many error conditions automatically:

1. **Stale PID Files**: Automatically detects and cleans up PID files pointing to non-existent processes
2. **Process State Mismatches**: Corrects situations where internal state doesn't match actual process state  
3. **Stuck State Detection**: Identifies when system is stuck in STARTING/STOPPING states too long
4. **Orphaned Processes**: Finds and cleans up abandoned Moonlight processes
5. **Network Connectivity Issues**: Monitors connection to gaming PC and warns of issues

**Automatic Recovery Actions:**
```bash
# The system now automatically:
# - Cleans stale PID files
# - Kills orphaned processes  
# - Resets state mismatches
# - Provides detailed error logging
# - Attempts intelligent retries
```

**Manual Recovery Steps:**
```bash
# If system enters error state, check error log:
tail -n 20 /home/<usr>/galaxy/logs_errors.log

# Check system resource usage:
grep "High.*usage\|Resource usage" /home/<usr>/galaxy/logs.log

# Force reset the system:
sudo systemctl restart moonlight-button.service

# Check for hardware issues:
python3 test-button-led.py
```

**Advanced Diagnostics:**
```bash
# Check process monitoring thread health:
grep "ProcessMonitor\|HealthMonitor" /home/<usr>/galaxy/logs.log

# Verify state transitions are working:
grep "State changed.*→" /home/<usr>/galaxy/logs.log | tail -10

# Check network connectivity monitoring:
grep "Network connectivity.*OK\|Cannot reach" /home/<usr>/galaxy/logs.log

# Monitor automatic cleanup actions:
grep "cleaned up\|Force cleanup\|Killing orphaned" /home/<usr>/galaxy/logs.log
```

#### 📊 System Health Monitoring  

**Real-time Health Checks:**
The system now performs comprehensive health monitoring every 30 seconds:

```bash
# Monitor health check results:
grep "Health check\|Resource usage" /home/<usr>/galaxy/logs.log | tail -10

# Check for resource warnings:
grep "High.*usage" /home/<usr>/galaxy/logs.log

# Verify process monitoring:
grep "Process.*is.*healthy" /home/<usr>/galaxy/logs.log | tail -5
```

**Health Check Components:**
- **PID File Validation**: Ensures PID file points to actual Moonlight process
- **Process State Verification**: Confirms process is running and responding
- **Network Connectivity**: Tests connection to gaming PC
- **System Resources**: Monitors CPU, RAM, and disk usage
- **State Consistency**: Validates internal state matches reality

**Interpreting Health Warnings:**
```bash
# High resource usage warnings:
[timestamp] [WARNING] [HealthMonitor] [ButtonHandler] High memory usage: 92.1%

# Network connectivity issues:
[timestamp] [WARNING] [HealthMonitor] [ButtonHandler] Cannot connect to 192.168.x.x:47989

# Process state problems:
[timestamp] [WARNING] [HealthMonitor] [ButtonHandler] Process 1234 is zombie
```
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
