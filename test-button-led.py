from gpiozero import Button, LED
from time import sleep
import signal
import sys

BUTTON_PIN = 17
LED_PIN = 27

button = Button(BUTTON_PIN)
led = LED(LED_PIN)

def on_button_press():
    print("Button pressed! Blinking LED...")
    for _ in range(5):
        led.on()
        sleep(0.2)
        led.off()
        sleep(0.2)

button.when_pressed = on_button_press

print("Test running. Press the button to blink LED.")
print("Press Ctrl+C to exit.")

try:
    signal.pause()
except KeyboardInterrupt:
    print("\nExiting.")
    led.off()
    sys.exit(0)
