#!/usr/bin/env python3
"""Do the three LEDs on the ReSpeaker 2-Mic HAT respond?

They are APA102s on the SPI bus -- the same bus as the e-ink panel, which is
why this is a separate test rather than something wired into the agent
straight away. Stop the agent first so nothing else is using the bus:

    systemctl stop dietpi-autostart_custom.service
    ./venv/bin/python test_leds.py

Try another chip select if nothing happens (the HAT does not really use one,
so the number mostly decides which CE line wiggles):

    ./venv/bin/python test_leds.py --bus 0 --device 0
"""

import argparse
import time

N_LEDS = 3


def frame(colours, brightness):
    """One full APA102 update: start frame, one frame per LED, end frame."""
    data = [0x00, 0x00, 0x00, 0x00]                  # start
    for (r, g, b) in colours:
        data += [0xE0 | (brightness & 0x1F), b, g, r]  # APA102 order is B,G,R
    data += [0xFF] * ((N_LEDS + 15) // 16 + 1)       # end frame
    return data


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
    print("done - LEDs back off. Saw nothing? Try --device 0, or the LEDs are")
    print("not on this bus and we need the HAT's own driver instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
