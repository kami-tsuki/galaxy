#!/bin/bash
set -e

# Load env variables safely
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

log() {
  echo "[$(date '+%d.%m.%Y %H:%M:%S')] [$1] [LaunchGame] $2" >> "$LOG_FILE"
}

# Cleanup existing stale or running PID
if [ -f "$PID_FILE" ]; then
  if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    log "WARN" "Launch-game is already running with PID $(cat $PID_FILE). Killing it."
    kill "$(cat $PID_FILE)" || true
    sleep 2
  fi
  rm -f "$PID_FILE"
fi

start_stream() {
  log "INFO" "Starting launch sequence"
  log "INFO" "Powering on TV..."
  /usr/bin/cec-client -s -d 1 <<< "on 0"

  sleep 2

  log "INFO" "Sending Wake-on-LAN..."
  /usr/bin/wakeonlan "$PC_MAC"

  log "INFO" "Waiting for PC to boot (30s)..."
  sleep 30

  log "INFO" "Starting Moonlight stream..."
  export XDG_RUNTIME_DIR="/tmp/xdg"
  mkdir -p "$XDG_RUNTIME_DIR"
  "$(which moonlight)" stream -app "$MOONLIGHT_APP" "$MOONLIGHT_HOST" >> "$LOG_FILE" 2>&1 &

  echo $! > "$PID_FILE"
}

stop_stream() {
  log "INFO" "Stopping Moonlight stream and powering off TV..."
  if [ -f "$PID_FILE" ]; then
    kill "$(cat $PID_FILE)" && rm "$PID_FILE"
  fi
  /usr/bin/cec-client -s -d 1 <<< "standby 0"
  log "INFO" "Shutdown complete."
}

case "$1" in
  start)
    start_stream
    ;;
  stop)
    stop_stream
    ;;
  *)
    echo "Usage: $0 {start|stop}"
    exit 1
    ;;
esac
