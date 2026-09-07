"""Device-specific settings for the Python side of OutdoorGPT.

The shell scripts read config.sh; the Python modules read this file. Between
them they hold everything that is particular to one build of the phone, so a
second build needs only these two files changed.

Like config.sh, this file is version-controlled with this phone's real values
and is copied over the agent directory by install_on_pi.sh.
"""

# --- e-ink recipe screen (Waveshare 7.5" V2, 800x480) ------------------------

# The panel buffer is always landscape; "portrait" renders on a 480x800 canvas
# and rotates it into the buffer. Use "landscape" for the original layout.
EINK_ORIENTATION = "portrait"

# Rotation used for portrait, in degrees. Depends on which way the panel is
# mounted: if the text comes out upside down, use 90.
EINK_ROTATE_DEGREES = 270

# Control pins, BCM numbering. Chosen to stay clear of the rotary dial
# (GPIO 17, 22, 23, 24) and the ReSpeaker I2S audio (GPIO 18-21). Waveshare's
# own defaults are RST 17, BUSY 24, PWR 18, all of which collide.
EINK_PIN_RST = 6      # physical pin 31
EINK_PIN_DC = 25      # physical pin 22
EINK_PIN_CS = 8       # physical pin 24, CE0
EINK_PIN_BUSY = 5     # physical pin 29
EINK_PIN_PWR = 26     # physical pin 37

# --- status LEDs (ReSpeaker 2-Mic HAT, three APA102s on SPI) -----------------

LED_SPI_BUS = 0
LED_SPI_DEVICE = 1
LED_COUNT = 3

# 0-31. Kept low: the handset is used close up, often in the dark.
LED_MAX_BRIGHTNESS = 8

# (r, g, b) per state. "thinking" pulses; the others are steady.
LED_COLOURS = {
    'listening': (0, 110, 0),     # your turn: the mic is open
    'thinking':  (0, 60, 255),    # the model is generating
    'speaking':  (255, 80, 0),    # the phone is talking, so wait
    'done':      (180, 0, 255),   # recipe delivered; press the button for a new one
    'off':       (0, 0, 0),       # only on shutdown
}
