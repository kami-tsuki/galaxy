#!/bin/bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_USER="${SUDO_USER:-$USER}"
if [ "$TARGET_USER" = "root" ]; then
    echo "run this as a normal user with sudo rights, not as root" >&2
    exit 1
fi
TARGET_UID="$(id -u "$TARGET_USER")"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
UNITS="galaxy.service galaxy-stream.service galaxy-obs.service"

sudo apt-get update
sudo apt-get install -y cage flatpak mpv cec-utils python3 openssh-client util-linux pipewire pipewire-pulse wireplumber pulseaudio-utils

sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo flatpak install -y --noninteractive flathub com.moonlight_stream.Moonlight

sudo usermod -aG video,render,input,audio "$TARGET_USER"

sudo install -d -m 0755 /etc/galaxy
if [ ! -f /etc/galaxy/galaxy.env ]; then
    sudo install -m 0640 -o root -g "$TARGET_USER" "$DIR/.env.example" /etc/galaxy/galaxy.env
    token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sudo sed -i "s|^API_TOKEN=.*|API_TOKEN=$token|" /etc/galaxy/galaxy.env
else
    while IFS= read -r line; do
        key="${line%%=*}"
        sudo grep -q "^$key=" /etc/galaxy/galaxy.env || echo "$line" | sudo tee -a /etc/galaxy/galaxy.env >/dev/null
    done < <(grep -E '^[A-Z_]+=' "$DIR/.env.example")
fi

for unit in $UNITS; do
    sed -e "s|@USER@|$TARGET_USER|g" -e "s|@UID@|$TARGET_UID|g" -e "s|@DIR@|$DIR|g" -e "s|@HOME@|$TARGET_HOME|g" "$DIR/systemd/$unit" \
        | sudo tee "/etc/systemd/system/$unit" >/dev/null
done

rules=""
for unit in galaxy-stream.service galaxy-obs.service; do
    for action in start stop; do
        rules="$rules${rules:+, }/usr/bin/systemctl $action $unit"
    done
done
echo "$TARGET_USER ALL=(root) NOPASSWD: $rules" | sudo tee /etc/sudoers.d/galaxy >/dev/null
sudo chmod 0440 /etc/sudoers.d/galaxy
sudo visudo -cf /etc/sudoers.d/galaxy

sudo loginctl enable-linger "$TARGET_USER"
until [ -d "/run/user/$TARGET_UID" ]; do sleep 1; done
user_ctl() { sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user "$@"; }
user_ctl enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
user_ctl mask xdg-desktop-portal.service xdg-desktop-portal-gtk.service
sudo systemctl daemon-reload
sudo systemctl enable galaxy.service
sudo systemctl restart galaxy.service

echo "Next, from $DIR:"
echo "  sudo nano /etc/galaxy/galaxy.env"
echo "  python3 -m galaxy set SUNSHINE_USER"
echo "  python3 -m galaxy set SUNSHINE_PASS"
echo "  python3 -m galaxy pair"
