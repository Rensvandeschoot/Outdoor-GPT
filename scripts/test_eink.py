#!/usr/bin/env python3
"""
Standalone hardware test for the OutdoorGPT e-ink recipe screen.

Draws one page on the Waveshare 7.5" panel WITHOUT the rest of the phone - no
rotary dial, no microphone, no language model, no servers. Use it to prove the
wiring, the driver and Pillow are all working before wiring the screen into the
voice agent.

It never reads the rotary dial, so it also works with the dial disconnected.

Run on the Pi, inside the agent's venv, from the folder that holds
eink_display.py and the waveshare_epd/ driver (that is /root/edge_voice_agent
after install_on_pi.sh, or the repo's scripts/ folder):

    source /root/edge_voice_agent/venv/bin/activate
    cd /root/edge_voice_agent            # or: cd .../Outdoor-GPT/scripts
    python test_eink.py                  # draws a sample recipe
    python test_eink.py --doc            # draws the campfire-safety sample (docs/test_document)
    python test_eink.py --file some.md   # draws any text/markdown file
    python test_eink.py --text "line one\nline two"

Wiring (BCM):  VCC->3.3V  GND->GND  DIN->10  CLK->11  CS->8  DC->25
               RST->6  BUSY->5  PWR->26     (RST/BUSY/PWR are remapped in
               waveshare_epd/epdconfig.py; VCC on 3.3V, NOT 5V)
"""

import argparse
import sys
import traceback

# A real, recipe-shaped page - what recipe mode actually produces.
SAMPLE_RECIPE = """Foil-pack trout & potatoes
Time: 25 min
Ingredients:
- 1 trout, cleaned
- 1 potato, thinly sliced
- 1 knob butter
- a few sprigs wild thyme
- salt, pepper
Steps:
1. Lay fish and potato on a double sheet of foil, butter and thyme on top, season.
2. Fold into a sealed packet.
3. Set on hot embers, not open flame, for 10 min.
4. Flip; cook another 8-10 min.
5. Open carefully; done when the fish flakes and the potato is tender."""

# The content of docs/test_document.md, embedded so --doc works on the Pi too
# (docs/ is not copied onto the Pi by install_on_pi.sh).
SAMPLE_DOC = """Campfire safety basics
Build the fire at least three metres from tents, trees and dry brush. Clear the ground to bare soil about a metre around the pit, and keep water or a shovel of sand within reach before lighting.

To cook, let the flames die down to glowing embers first - embers give steady, even heat, while open flames char the outside and leave the inside raw.

To put it out: pour water over it, stir the ashes with a stick, and pour again. The ashes must be cold to the touch before you leave. Never bury a fire - the embers can smoulder underground for hours and reignite."""


def load_text(args):
    if args.text is not None:
        return args.text.replace("\\n", "\n"), "the text you passed"
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read(), args.file
    if args.doc:
        return SAMPLE_DOC, "the campfire-safety sample (docs/test_document)"
    return SAMPLE_RECIPE, "the built-in sample recipe"


def main():
    ap = argparse.ArgumentParser(description="Draw one test page on the e-ink panel.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--file", help="render a text/markdown file")
    g.add_argument("--text", help="render this literal text (use \\n for line breaks)")
    g.add_argument("--doc", action="store_true",
                   help="render the campfire-safety sample from docs/test_document")
    args = ap.parse_args()

    try:
        text, what = load_text(args)
    except OSError as e:
        print(f"Could not read the input file: {e}")
        return 1

    print("OutdoorGPT e-ink panel test")
    print(f"  drawing : {what}")
    print("  wiring  : VCC=3.3V  RST=GPIO6  BUSY=GPIO5  PWR=GPIO26  DC=25  CS=8  DIN=10  CLK=11")
    print("  note    : this test ignores the rotary dial, so a disconnected dial is fine\n")

    try:
        from eink_display import EinkRecipeDisplay
    except Exception:
        print("Could not import eink_display.py. Run this from the folder that holds")
        print("eink_display.py and the waveshare_epd/ driver.\n")
        traceback.print_exc()
        return 1

    disp = EinkRecipeDisplay(verbose=True)
    try:
        disp.render_blocking(text)
    except Exception:
        print("\nFAILED to draw. Full error:\n")
        traceback.print_exc()
        print("\nChecklist:")
        print("  - GPIO busy? Another process already holds the pin. Usually the")
        print("    voice agent: it claims RST/BUSY/DC/PWR the first time it draws")
        print("    a recipe and keeps them until it exits. Stop it and retry:")
        print("      systemctl stop dietpi-autostart_custom.service")
        print("    (a reboot brings the phone back)")
        print("  - Pillow + gpiozero + lgpio + spidev installed in this venv?")
        print("  - No such file /dev/spidev0.0? SPI is off. Enable it with")
        print("    dietpi-config -> Advanced Options -> SPI state, then reboot.")
        print("    /dev/spidev10.0 on its own is not enough: that is the SoC")
        print("    internal bus, not the 40-pin header.")
        print("  - VCC on 3.3V (not 5V), and RST/BUSY/PWR on GPIO 6/5/26?")
        print("  - Ribbon/FPC seated the right way round and fully clicked in?")
        print("  - Pins free? RST/BUSY/PWR must not clash with the dial or the audio HAT.")
        return 1

    print("\nOK - the panel drew the page. It stays on screen with the power off (bistable).")
    print("Re-run with --doc, --file or --text to draw something else.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
