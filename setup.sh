#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"

sudo apt-get update
sudo apt-get install -y cage flatpak cec-utils python3 openssh-client

sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo flatpak install -y --noninteractive flathub com.moonlight_stream.Moonlight

sudo install -d -m 0755 /etc/galaxy
if [ ! -f /etc/galaxy/galaxy.env ]; then
    sudo install -m 0640 -o root -g "$TARGET_USER" "$DIR/.env.example" /etc/galaxy/galaxy.env
    token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sudo sed -i "s|^API_TOKEN=.*|API_TOKEN=$token|" /etc/galaxy/galaxy.env
fi

for unit in galaxy.service galaxy-stream.service; do
    sed -e "s|@USER@|$TARGET_USER|g" -e "s|@DIR@|$DIR|g" "$DIR/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done

echo "$TARGET_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start galaxy-stream.service, /usr/bin/systemctl stop galaxy-stream.service" \
    | sudo tee /etc/sudoers.d/galaxy >/dev/null
sudo chmod 0440 /etc/sudoers.d/galaxy
sudo visudo -cf /etc/sudoers.d/galaxy

sudo loginctl enable-linger "$TARGET_USER"
sudo systemctl daemon-reload
sudo systemctl enable --now galaxy.service

echo "Edit /etc/galaxy/galaxy.env, then: python3 $DIR/galaxy.py pair"
