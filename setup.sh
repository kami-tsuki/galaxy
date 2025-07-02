#!/bin/bash

set -e

echo "=== Galaxy Setup Script ==="
echo "Installing dependencies and configuring system..."

echo "Updating package lists..."
sudo apt update

echo "Installing system dependencies..."
sudo apt install -y python3-pip cec-utils wakeonlan python3-gpiozero git netcat-openbsd iputils-ping

echo "Installing Python packages..."
pip3 install python-dotenv psutil

echo "Setting permissions on scripts..."
chmod +x launch-game.sh
chmod +x button-handler.py

echo "Creating log directory..."
mkdir -p logs

echo "Copying systemd service..."
sudo cp moonlight-button.service /etc/systemd/system/

echo "IMPORTANT: Edit the service file to match your installation path:"
echo "  sudo nano /etc/systemd/system/moonlight-button.service"
echo "Update the following paths:"
echo "  - ExecStart=/usr/bin/python3 /FULL/PATH/TO/galaxy/button-handler.py"
echo "  - WorkingDirectory=/FULL/PATH/TO/galaxy"
echo ""
read -p "Press Enter after you have edited the service file paths..."

echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable moonlight-button.service
sudo systemctl start moonlight-button.service

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Check service status: sudo systemctl status moonlight-button.service"
echo "2. View logs: tail -f logs.log"
echo "3. Monitor service logs: sudo journalctl -u moonlight-button.service -f"
echo ""
echo "Hardware setup:"
echo "- Connect button between GPIO ${BUTTON_GPIO:-17} and GND with 10kΩ pull-down resistor"
echo "- Connect LED between GPIO ${LED_GPIO:-27} and GND with 220Ω resistor"
echo ""
echo "Configuration:"
echo "- Edit .env file with your specific settings"
echo "- Test hardware with: python3 test-button-led.py"
