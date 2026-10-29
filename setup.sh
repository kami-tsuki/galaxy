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
ENV_FILE=/etc/galaxy/galaxy.env
UNITS="galaxy.service galaxy-stream.service galaxy-obs.service"

user_ctl() {
    sudo -u "$TARGET_USER" XDG_RUNTIME_DIR="/run/user/$TARGET_UID" systemctl --user "$@"
}

env_value() {
    sudo grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-
}

if ! ping -c1 -W3 deb.debian.org >/dev/null 2>&1; then
    echo "no network connection, setup needs to download packages" >&2
    exit 1
fi

sudo apt-get update
sudo apt-get install -y cage flatpak mpv cec-utils python3 openssh-client util-linux pipewire pipewire-pulse wireplumber pulseaudio-utils iw

sudo flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
sudo flatpak install -y --noninteractive flathub com.moonlight_stream.Moonlight

sudo usermod -aG video,render,input,audio "$TARGET_USER"

sudo install -d -m 0755 /etc/galaxy
if [ ! -f "$ENV_FILE" ]; then
    sudo install -m 0640 -o root -g "$TARGET_USER" "$DIR/.env.example" "$ENV_FILE"
else
    sudo sh -c "[ -z \"\$(tail -c1 $ENV_FILE)\" ] || echo >> $ENV_FILE"
    while IFS= read -r line; do
        key="${line%%=*}"
        sudo grep -q "^$key=" "$ENV_FILE" || echo "$line" | sudo tee -a "$ENV_FILE" >/dev/null
    done < <(grep -E '^[A-Z_0-9]+=' "$DIR/.env.example")
fi
if [ "$(env_value API_TOKEN | wc -c)" -lt 25 ]; then
    token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
    sudo sed -i "s|^API_TOKEN=.*|API_TOKEN=$token|" "$ENV_FILE"
fi

for unit in $UNITS; do
    sed -e "s|@USER@|$TARGET_USER|g" -e "s|@UID@|$TARGET_UID|g" -e "s|@DIR@|$DIR|g" "$DIR/systemd/$unit" \
        | sudo tee "/etc/systemd/system/$unit" >/dev/null
done

rules=""
for unit in galaxy-stream.service galaxy-obs.service; do
    for action in start stop; do
        rules="$rules${rules:+, }/usr/bin/systemctl $action $unit"
    done
done
sudoers="$(mktemp)"
echo "$TARGET_USER ALL=(root) NOPASSWD: $rules" > "$sudoers"
sudo visudo -cf "$sudoers"
sudo install -m 0440 -o root -g root "$sudoers" /etc/sudoers.d/galaxy
rm -f "$sudoers"

sudo install -d /etc/NetworkManager/conf.d
printf '[connection]\nwifi.powersave = 2\n' | sudo tee /etc/NetworkManager/conf.d/90-galaxy-wifi.conf >/dev/null
sudo nmcli general reload conf >/dev/null 2>&1 || true
for interface in $(iw dev | awk '$1 == "Interface" {print $2}'); do
    sudo iw dev "$interface" set power_save off || true
done

sudo install -d /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=100M\n' | sudo tee /etc/systemd/journald.conf.d/90-galaxy.conf >/dev/null
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
sudo journalctl --flush

sudo loginctl enable-linger "$TARGET_USER"
for _ in $(seq 1 30); do
    [ -d "/run/user/$TARGET_UID" ] && break
    sleep 1
done
if [ ! -d "/run/user/$TARGET_UID" ]; then
    echo "the user session for $TARGET_USER did not start" >&2
    exit 1
fi

sudo -u "$TARGET_USER" mkdir -p "$TARGET_HOME/.config/pipewire"
sudo -u "$TARGET_USER" cp -r "$DIR/pipewire/." "$TARGET_HOME/.config/pipewire/"
user_ctl enable pipewire.socket pipewire-pulse.socket wireplumber.service
user_ctl restart pipewire.service pipewire-pulse.service wireplumber.service
if [ "$(systemctl get-default)" != "graphical.target" ]; then
    user_ctl mask xdg-desktop-portal.service xdg-desktop-portal-gtk.service
fi

sudo systemctl daemon-reload
sudo systemctl enable galaxy.service
sudo systemctl restart galaxy.service

echo
echo "Installed. Log out and back in once so the new groups apply to your own session."
echo "Next, from $DIR:"
echo "  sudo nano $ENV_FILE        set PC_HOST, PC_MAC and DISPLAYS"
echo "  python3 -m galaxy set SUNSHINE_USER"
echo "  python3 -m galaxy set SUNSHINE_PASS"
echo "  python3 -m galaxy pair      pairs Moonlight and pins Sunshine's certificate"
echo "Open http://$(hostname -I | cut -d' ' -f1):8787/#token=\$(sudo grep ^API_TOKEN= $ENV_FILE | cut -d= -f2)"
