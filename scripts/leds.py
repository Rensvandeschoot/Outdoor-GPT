"""Status light on the three APA102 LEDs of the ReSpeaker 2-Mic HAT.

The thinking pause on a small model is long enough that silence reads as a
fault; the LEDs show what is actually happening. Colours:

    listening  green           (your turn: the mic is open)
    thinking   blue, pulsing   (the model is generating)
    speaking   orange          (the phone is talking, so wait)
    done       purple          (recipe delivered; press the button for a new one)

Everything here is fail-safe. No spidev, no HAT, wrong bus: the class turns
into a no-op and the agent runs exactly as it would without it.

The LEDs share SPI0 with the e-ink panel, so every write takes spi_bus.LOCK.
While a recipe is being drawn the animation simply pauses.
"""

import math
import threading
import time

import spi_bus

N_LEDS = 3
SPI_BUS = 0
SPI_DEVICE = 1
MAX_BRIGHTNESS = 8      # 0-31; kept low because the handset is used close up, often in the dark

# (r, g, b) per state. "thinking" pulses; the rest are steady.
COLOURS = {
    'listening': (0, 110, 0),
    'thinking':  (0, 60, 255),
    'speaking':  (255, 80, 0),
    'done':      (180, 0, 255),
    'off':       (0, 0, 0),   # only on shutdown
}

POLL_INTERVAL = 0.05    # how often we look at the agent's state
PULSE_PERIOD = 1.6      # seconds for one full breath while thinking


class StatusLeds:
    """Mirrors the agent's state onto the HAT LEDs from a background thread."""

    def __init__(self, output_handler, verbose=False):
        self._handler = output_handler
        self._verbose = verbose
        self._spi = None
        self._thread = None
        self._stop = threading.Event()
        self._last_written = None

    # -- plumbing ---------------------------------------------------------
    def _log(self, msg):
        if self._verbose:
            print(f"[leds] {msg}")

    def _open(self):
        try:
            import spidev
        except ImportError:
            self._log("spidev not installed - status LEDs disabled")
            return False
        try:
            spi = spidev.SpiDev()
            spi.open(SPI_BUS, SPI_DEVICE)
            spi.max_speed_hz = 8000000
            spi.mode = 0b00
        except Exception as e:
            self._log(f"no LEDs on /dev/spidev{SPI_BUS}.{SPI_DEVICE} ({e}) - disabled")
            return False
        self._spi = spi
        return True

    def _write(self, rgb, brightness):
        """One APA102 update. Skipped when it would change nothing."""
        if self._spi is None:
            return
        if (rgb, brightness) == self._last_written:
            return
        r, g, b = rgb
        data = [0x00, 0x00, 0x00, 0x00]
        for _ in range(N_LEDS):
            data += [0xE0 | (brightness & 0x1F), b, g, r]   # APA102 order: B,G,R
        data += [0xFF] * ((N_LEDS + 15) // 16 + 1)
        try:
            with spi_bus.LOCK:
                self._spi.writebytes(data)
            self._last_written = (rgb, brightness)
        except Exception as e:
            self._log(f"write failed, disabling LEDs ({e})")
            self._spi = None

    # -- state ------------------------------------------------------------
    def _state(self):
        h = self._handler
        # Priority order. Speech first: the closing line after a recipe is still
        # speech, so it stays orange and only turns purple once the phone is
        # quiet. is_processing counts as speech rather than thinking, because it
        # means the speech worker is alive and it stays up between sentences
        # while is_speaking briefly drops; reading it as thinking would flick
        # the light blue mid-answer.
        if getattr(h, 'is_speaking', False) or getattr(h, 'is_processing', False):
            return 'speaking'
        if getattr(h, 'recipe_delivered', False):
            return 'done'
        # What is left is the real pause: prompt sent, nothing to say yet.
        if getattr(h, 'is_generating', False):
            return 'thinking'
        return 'listening'

    def _run(self):
        while not self._stop.is_set():
            state = self._state()
            if state == 'thinking':
                # A sine breath rather than a blink: less alarming, and it
                # reads as "working" instead of "error".
                phase = (time.time() % PULSE_PERIOD) / PULSE_PERIOD
                wave = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
                level = 1 + int(wave * (MAX_BRIGHTNESS - 1))
                self._write(COLOURS['thinking'], level)
            else:
                self._write(COLOURS[state], MAX_BRIGHTNESS if state != 'off' else 0)
            self._stop.wait(POLL_INTERVAL)
        self._write(COLOURS['off'], 0)

    # -- lifecycle --------------------------------------------------------
    def start(self):
        if not self._open():
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._log("status LEDs active")
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._spi is not None:
            try:
                self._spi.close()
            except Exception:
                pass
