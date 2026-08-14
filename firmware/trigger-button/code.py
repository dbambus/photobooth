# SPDX-FileCopyrightText: 2018 Kattni Rembor for Adafruit Industries
#
# SPDX-License-Identifier: MIT

"""Trigger button for the photobooth, running on an Adafruit KB2040.

Based on the CircuitPython Essentials HID Keyboard example. The board
enumerates as a plain USB keyboard; photobooth itself has no knowledge of
this device beyond the keypress it receives (see
photobooth/gui/Qt5Gui/Controller.py, _handleKeypressEvent).

Wiring (each pin uses the internal pull-up, so a press pulls it to ground):
  D2 - message button, types a fixed string
  D3 - shutter button, sends Shift+Space to trigger the photobooth
  D4 - NeoPixel status LED, cycles through a slow rainbow while idle

Shift+Space rather than plain Space is intentional and does not need to be
"just Space": Qt reports the same Key_Space for both, since Space has no
shifted variant to remap to - only the (unused) modifier bit differs.
"""
import time

import board
import digitalio
import neopixel
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from adafruit_hid.keycode import Keycode

pixel = neopixel.NeoPixel(
    board.D4, 1, brightness=0.2, auto_write=True, pixel_order=neopixel.GRBW
)

# One entry per pin in keypress_pins. A string is typed out as-is; a
# Keycode is sent together with control_key held down.
keypress_pins = [board.D2, board.D3]
keys_pressed = ["Ich Liebe Dich!\n", Keycode.SPACE]
control_key = Keycode.SHIFT

# The keyboard object!
time.sleep(1)  # Sleep for a bit to avoid a race condition on some systems
keyboard = Keyboard(usb_hid.devices)
keyboard_layout = KeyboardLayoutUS(keyboard)  # We're in the US :)

# Make all pin objects inputs with pullups
key_pin_array = []
for pin in keypress_pins:
    key_pin = digitalio.DigitalInOut(pin)
    key_pin.direction = digitalio.Direction.INPUT
    key_pin.pull = digitalio.Pull.UP
    key_pin_array.append(key_pin)

counter = 0
hue = 0


def wheel(pos):
    # Input a value 0 to 255 to get a color value.
    # The colours are a transition r - g - b - back to r.
    if pos < 0 or pos > 255:
        r = g = b = 0
    elif pos < 85:
        r = int(pos * 3)
        g = int(255 - pos * 3)
        b = 0
    elif pos < 170:
        pos -= 85
        r = int(255 - pos * 3)
        g = 0
        b = int(pos * 3)
    else:
        pos -= 170
        r = 0
        g = int(pos * 3)
        b = int(255 - pos * 3)
    return (r, g, b)


print("Waiting for key pin...")

while True:
    counter += 1
    # Check each pin
    for key_pin in key_pin_array:
        if not key_pin.value:  # Is it grounded?
            i = key_pin_array.index(key_pin)
            print("Pin #%d is grounded." % i)

            while not key_pin.value:
                pass  # Hold here until released - crude debounce.

            key = keys_pressed[i]  # Get the corresponding Keycode or string
            if isinstance(key, str):  # If it's a string...
                keyboard_layout.write(key)  # ...Print the string
            else:  # If it's not a string...
                keyboard.press(control_key, key)  # "Press"...
                keyboard.release_all()  # ..."Release"!

    time.sleep(0.01)

    if counter > 10:
        hue += 1
        if hue > 255:
            hue = 0
        pixel.fill(wheel(hue))
        pixel.show()
        counter = 0
