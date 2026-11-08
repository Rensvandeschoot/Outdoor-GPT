#!/bin/bash
#
# Verify the phone's GPIO wiring: rotary dial and interrupt (yellow) button.
#
#     ./check_gpio.sh [seconds]      (default 20)
#
# Safe to run while the agent is running: the tools below read the GPIO
# registers directly, so it does not matter that gpiozero holds the lines.
#
# Pins come from gpio_inputs.py (RaspberryPi5GPIOHandler), all with pull_up=True,
# so a pin reads HIGH when idle and is pulled LOW when its contact closes. The
# agent's GPIO library switches those pull-ups on; with the agent stopped they
# may be off, and an open contact then reads whatever the pin floats to. So
# this script first sets the four pins to inputs with pull-up itself (what the
# agent does anyway; nothing else is changed), and shows the pull it sees.

SECONDS_TO_WATCH=${1:-20}
PINS=22,23,24,17

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

if pgrep -f voice_agent_cli.py >/dev/null 2>&1; then
  echo "the agent is running"
else
  echo "the agent is not running"
fi
# Inputs with pull-up, as the agent sets them.
for p in 22 23 24 17; do
  $TOOL set $p ip pu >/dev/null 2>&1 || { echo "  (could not set the pull-up on GPIO $p; run as root)"; break; }
done

read_levels() {
  if [ "$TOOL" = "pinctrl" ]; then
    # e.g. "17: ip    pu | hi // GPIO17 = input"
    pinctrl get $PINS 2>/dev/null | awk '{
      lvl="?"; for (i=1;i<=NF;i++) if ($i=="hi"||$i=="lo") lvl=$i;
      gsub(":","",$1); printf "GPIO%s %s   ", $1, lvl }'
  else
    # e.g. "GPIO 17: level=1 fsel=0 func=INPUT pull=UP"
    raspi-gpio get $PINS 2>/dev/null | awk '{
      lvl="?"; for (i=1;i<=NF;i++) if ($i ~ /^level=/) { split($i,a,"="); lvl=(a[2]=="1"?"hi":"lo") }
      gsub(":","",$2); printf "GPIO%s %s   ", $2, lvl }'
  fi
}

echo
echo "Pin configuration as the tool reports it (expect input, pull-up):"
$TOOL get $PINS 2>/dev/null | sed 's/^/  /'
echo
echo "Baseline (leave the dial and button alone):"
echo "  $(read_levels)"
echo "  At rest the button (GPIO 22) must read hi, and exactly one of 23/24/17"
echo "  must read lo: the position the dial is in."
echo
echo "Now turn the dial through all three positions and press the interrupt"
echo "button. Exactly one of GPIO 23/24/17 should read 'lo' at a time, and"
echo "GPIO 22 should flip to 'lo' only while the button is held."
echo
echo "Watching for ${SECONDS_TO_WATCH}s (Ctrl-C to stop early)..."
echo

SEEN_LO=""
SEEN_HI=""
CHANGES=0
END=$(( $(date +%s) + SECONDS_TO_WATCH ))
PREV=""
while [ "$(date +%s)" -lt "$END" ]; do
  NOW=$(read_levels)
  if [ "$NOW" != "$PREV" ]; then
    echo "  $(date +%T)  $NOW"
    CHANGES=$(( CHANGES + 1 ))
    for p in 23 24 17 22; do
      case "$NOW" in
        *"GPIO$p lo"*) SEEN_LO="$SEEN_LO $p " ;;
        *"GPIO$p hi"*) SEEN_HI="$SEEN_HI $p " ;;
      esac
    done
    PREV="$NOW"
  fi
  sleep 0.25
done

echo
echo "Summary of the watch:"
for p in 23 24 17 22; do
  lo=no; hi=no
  case "$SEEN_LO" in *" $p "*) lo=yes ;; esac
  case "$SEEN_HI" in *" $p "*) hi=yes ;; esac
  if [ $lo = yes ] && [ $hi = yes ]; then
    echo "  GPIO $p  went both lo and hi - its contact works"
  elif [ $lo = yes ]; then
    echo "  GPIO $p  ONLY read lo - closed the whole time (for 22: the button reads pressed at rest)"
  else
    echo "  GPIO $p  NEVER went low - check its wiring"
  fi
done
if [ "$CHANGES" -gt $(( SECONDS_TO_WATCH * 2 )) ]; then
  echo "  Many changes in a short time: if nobody touched the dial or button, a pin is"
  echo "  floating or its contact is loose."
fi
