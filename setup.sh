#!/bin/bash

set -e

echo "Updating and installing dependencies..."
sudo apt update
sudo apt install -y python3-pip cec-utils wakeonlan python3-gpiozero

echo "Installing python packages..."
pip3 install python-dotenv

echo "Setting permissions on scripts..."
chmod +x launch-game.sh

echo "Copying systemd service..."
sudo cp moonlight-button.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable moonlight-button.service
sudo systemctl start moonlight-button.service

echo "Setup complete. Check status with:"
echo "  sudo systemctl status moonlight-button.service"
