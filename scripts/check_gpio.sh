#!/bin/bash
#
# Verify the phone's GPIO wiring: rotary dial and interrupt button.
#
#     ./check_gpio.sh [seconds]      (default 20)
#
# Read-only. Safe to run while the agent is running: the tools below read the
# GPIO registers directly, so it does not matter that gpiozero holds the lines.
#
# Pins come from gpio_inputs.py (RaspberryPi5GPIOHandler), all with pull_up=True,
# so a pin reads HIGH when idle and is pulled LOW when its contact closes.

SECONDS_TO_WATCH=${1:-20}

echo "Expected wiring (Raspberry Pi 5, BCM numbering):"
echo "  GPIO 22 (physical 15) - interrupt button"
echo "  GPIO 23 (physical 16) - rotary position 1 -> prompt 1"
echo "  GPIO 24 (physical 18) - rotary position 2 -> prompt 2"
echo "  GPIO 17 (physical 11) - rotary position 3 -> prompt 3"
echo

# Pick whichever tool this image has. pinctrl is the Pi 5 successor to raspi-gpio.
if command -v pinctrl >/dev/null 2>&1; then
  TOOL=pinctrl
elif command -v raspi-gpio >/dev/null 2>&1; then
  TOOL=raspi-gpio
else
  echo "Neither pinctrl nor raspi-gpio is installed. Install one with:"
  echo "  apt install raspi-utils   # provides pinctrl"
  echo
  echo "Alternative, if libgpiod is present, showing which lines are claimed:"
  command -v gpioinfo >/dev/null 2>&1 && gpioinfo | grep -E "line +(17|22|23|24):" || echo "  gpioinfo not available either"
  exit 1
fi
echo "using: $TOOL"

read_levels() {
  if [ "$TOOL" = "pinctrl" ]; then
    # e.g. "17: ip    pu | hi // GPIO17 = input"
    pinctrl get 22,23,24,17 2>/dev/null | awk '{
      lvl="?"; for (i=1;i<=NF;i++) if ($i=="hi"||$i=="lo") lvl=$i;
      gsub(":","",$1); printf "GPIO%-3s %-3s  ", $1, lvl }'
  else
    # e.g. "GPIO 17: level=1 fsel=0 func=INPUT pull=UP"
    raspi-gpio get 22,23,24,17 2>/dev/null | awk '{
      lvl="?"; for (i=1;i<=NF;i++) if ($i ~ /^level=/) { split($i,a,"="); lvl=(a[2]=="1"?"hi":"lo") }
      gsub(":","",$2); printf "GPIO%-3s %-3s  ", $2, lvl }'
  fi
}

echo
echo "Baseline (leave the dial and button alone):"
echo -n "  "; read_levels; echo
echo
echo "Now turn the dial through all three positions and press the interrupt"
echo "button. Exactly one of GPIO 23/24/17 should read 'lo' at a time, and"
echo "GPIO 22 should flip to 'lo' only while the button is held."
echo
echo "Watching for ${SECONDS_TO_WATCH}s (Ctrl-C to stop early)..."
echo

SEEN=""
END=$(( $(date +%s) + SECONDS_TO_WATCH ))
PREV=""
while [ "$(date +%s)" -lt "$END" ]; do
  NOW=$(read_levels)
  if [ "$NOW" != "$PREV" ]; then
    echo "  $(date +%T)  $NOW"
    case "$NOW" in
      *"GPIO23 lo"*) SEEN="$SEEN 23";;
    esac
    case "$NOW" in
      *"GPIO24 lo"*) SEEN="$SEEN 24";;
    esac
    case "$NOW" in
      *"GPIO17 lo"*) SEEN="$SEEN 17";;
    esac
    case "$NOW" in
      *"GPIO22 lo"*) SEEN="$SEEN 22";;
    esac
    PREV="$NOW"
  fi
  sleep 0.25
done

echo
echo "Summary of pins seen active (low) during the watch:"
for p in 23 24 17 22; do
  case "$SEEN" in
    *" $p"*) echo "  GPIO $p  seen";;
    *)       echo "  GPIO $p  NEVER went low - check its wiring";;
  esac
done
