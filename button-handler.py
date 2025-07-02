import os
import sys
import time
import subprocess
import logging
from datetime import datetime
from gpiozero import Button, LED
from dotenv import load_dotenv

load_dotenv()

LOG_FILE = os.getenv("LOG_FILE", "./logs.log")
PID_FILE = os.getenv("PID_FILE", "./launch-game.pid")
BUTTON_GPIO = int(os.getenv("BUTTON_GPIO", "17"))
LED_GPIO = int(os.getenv("LED_GPIO", "27"))

class CustomFormatter(logging.Formatter):
    def format(self, record):
        timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S')
        return f"[{timestamp}] [{record.levelname}] [ButtonHandler] {record.getMessage()}"

logger = logging.getLogger()
logger.setLevel(logging.INFO)
handler = logging.FileHandler(LOG_FILE)
handler.setFormatter(CustomFormatter())
logger.addHandler(handler)

button = Button(BUTTON_GPIO)
led = LED(LED_GPIO)

def is_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        with open(f"/proc/{pid}/cmdline") as f:
            cmd = f.read()
        return "moonlight" in cmd
    except Exception:
        return False

def on_button_press():
    logger.info("Button pressed! Triggering actions.")
    if is_running():
        logger.info("Stream is running. Stopping it.")
        led.blink(on_time=0.1, off_time=0.1)
        subprocess.run(["./launch-game.sh", "stop"])
        led.off()
    else:
        logger.info("Stream is not running. Starting it.")
        led.blink(on_time=0.5, off_time=0.5)
        try:
            subprocess.run(["./launch-game.sh", "start"], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error running launch-game: {e}")
        finally:
            led.off()

logger.info("Button handler started. Waiting for press.")
button.when_pressed = on_button_press

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Button handler stopped by user.")
    sys.exit(0)
