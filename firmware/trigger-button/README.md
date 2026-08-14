# Trigger button

CircuitPython firmware for the physical shutter button, running on an
[Adafruit KB2040](https://learn.adafruit.com/adafruit-kb2040). Connected to
the NUC via USB, it enumerates as a plain keyboard - photobooth itself does
not know this board exists, it just reacts to the keypress (see
[`_handleKeypressEvent`](../../photobooth/gui/Qt5Gui/Controller.py) in the
Controller).

## Wiring

Each pin uses the board's internal pull-up, so a press pulls it to ground.

| Pin | Function |
| --- | --- |
| D2  | Message button - types a fixed string |
| D3  | Shutter button - sends Shift+Space, which photobooth's Controller treats the same as plain Space |
| D4  | NeoPixel status LED - slow rainbow cycle while idle |

## Installing

1. Connect the KB2040 via USB; it mounts as a drive named `CIRCUITPY`.
2. Copy the [Adafruit CircuitPython
   Bundle](https://circuitpython.org/libraries)'s `adafruit_hid` and
   `neopixel` folders/files into `CIRCUITPY/lib/`, matching the
   CircuitPython version shown by `boot_out.txt` on the drive.
3. Copy `code.py` to the root of `CIRCUITPY`. The board runs it
   automatically - no separate build or flash step.
