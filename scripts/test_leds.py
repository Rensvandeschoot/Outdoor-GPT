#!/usr/bin/env python3
"""Light the three APA102 LEDs on the ReSpeaker 2-Mic HAT, one colour at a time.

Use it to confirm the LEDs respond before relying on the status lights in
leds.py. They share the SPI bus with the e-ink panel, so stop the agent first
so nothing else is driving the bus:

    systemctl stop dietpi-autostart_custom.service
    ./venv/bin/python test_leds.py

The HAT does not use a chip select, so the device number mainly decides which
CE line toggles. If nothing lights up, try the other one:

    ./venv/bin/python test_leds.py --bus 0 --device 0
"""

import argparse
import time

# The frame encoding lives in leds.py; this test only supplies the colours.
from leds import N_LEDS, apa102_frame as frame


def main():
    ap = argparse.ArgumentParser(description="Light the ReSpeaker HAT LEDs.")
    ap.add_argument("--bus", type=int, default=0)
    ap.add_argument("--device", type=int, default=1)
    ap.add_argument("--brightness", type=int, default=8, help="0-31, keep it low")
    args = ap.parse_args()

    try:
        import spidev
    except ImportError:
        print("spidev is missing from this environment. Run with ./venv/bin/python.")
        return 1

    spi = spidev.SpiDev()
    try:
        spi.open(args.bus, args.device)
    except FileNotFoundError:
        print(f"No /dev/spidev{args.bus}.{args.device}. Available nodes:")
        import glob
        for node in sorted(glob.glob("/dev/spidev*")):
            print("   ", node)
        return 1
    spi.max_speed_hz = 8000000
    spi.mode = 0b00

    off = [(0, 0, 0)] * N_LEDS
    steps = [
        ("all red",   [(255, 0, 0)] * N_LEDS),
        ("all green", [(0, 255, 0)] * N_LEDS),
        ("all blue",  [(0, 0, 255)] * N_LEDS),
        ("one at a time", None),
    ]

    print(f"writing to /dev/spidev{args.bus}.{args.device}, brightness {args.brightness}")
    print("watch the three LEDs on the audio HAT...")
    for label, colours in steps:
        if colours is None:
            for i in range(N_LEDS):
                lit = [(0, 0, 0)] * N_LEDS
                lit[i] = (255, 255, 255)
                print(f"  LED {i + 1}")
                spi.writebytes(frame(lit, args.brightness))
                time.sleep(0.6)
        else:
            print(f"  {label}")
            spi.writebytes(frame(colours, args.brightness))
            time.sleep(1.0)

    spi.writebytes(frame(off, 0))
    spi.close()
    print("done - LEDs back off. If nothing lit, try --device 0; if that stays dark too,")
    print("the LEDs are not on this bus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
