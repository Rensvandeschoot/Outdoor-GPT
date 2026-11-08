"""Status light on the three APA102 LEDs of the ReSpeaker 2-Mic HAT.

The thinking pause on a small model is long enough that silence reads as a
fault; the LEDs show what is actually happening. Colours (device_settings.py):

    starting   turquoise, slow breath  (the phone is starting up)
    listening  green                   (your turn: the mic is open)
    thinking   blue, pulsing           (the model is generating)
    speaking   orange                  (the phone is talking, so wait)
    done       purple                  (recipe delivered; press the button for a new one)

They come on as soon as the agent's process starts, before the models load:
without an output handler StatusLeds shows 'starting'. attach() hands it the
agent once that is ready, and from then on it mirrors the agent's state.

Everything here is fail-safe. No spidev, no HAT, wrong bus: the class turns
into a no-op and the agent runs exactly as it would without it.

The LEDs share SPI0 with the e-ink panel, so every write takes spi_bus.LOCK.
While a picture is being drawn the animation simply pauses; at start-up that
is the instruction card, a few seconds of a breath held still.
"""

import math
import threading
import time

import device_settings
import spi_bus

# Bus, colours and brightness are per device and live in device_settings.py.
N_LEDS = device_settings.LED_COUNT
SPI_BUS = device_settings.LED_SPI_BUS
SPI_DEVICE = device_settings.LED_SPI_DEVICE
MAX_BRIGHTNESS = device_settings.LED_MAX_BRIGHTNESS
COLOURS = device_settings.LED_COLOURS

POLL_INTERVAL = 0.05    # how often we look at the agent's state
PULSE_PERIOD = 1.6      # seconds for one full breath while thinking
BOOT_PERIOD = 4.0       # seconds for one breath while starting: slower, calmer


def apa102_frame(colours, brightness):
    """One complete APA102 update for a list of (r, g, b) tuples, one per LED.

    Start frame, one 4-byte frame per LED (brightness, then B, G, R in that
    order), and an end frame long enough to clock the data through.
    """
    data = [0x00, 0x00, 0x00, 0x00]
    for (r, g, b) in colours:
        data += [0xE0 | (brightness & 0x1F), b, g, r]
    data += [0xFF] * ((len(colours) + 15) // 16 + 1)
    return data


def breath(t, period):
    """0 -> 1 -> 0 over one period: a sine breath rather than a blink. Less
    alarming, and it reads as "working" instead of "error"."""
    phase = (t % period) / period
    return 0.5 - 0.5 * math.cos(2 * math.pi * phase)


def level(wave):
    """Brightness for a breath value 0..1, never fully dark."""
    return 1 + int(wave * (MAX_BRIGHTNESS - 1))


class StatusLeds:
    """Mirrors the agent's state onto the HAT LEDs from a background thread."""

    def __init__(self, output_handler=None, verbose=False):
        self._handler = output_handler
        self._verbose = verbose
        self._spi = None
        self._thread = None
        self._stop = threading.Event()
        self._last_written = None
        self._hold = None           # (seconds held, reset after, restart after)
        self._ack_until = 0.0       # brighter breath until then: a press was seen
        self._override = None       # a frame that stays, whatever the state

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
        data = apa102_frame([rgb] * N_LEDS, brightness)
        try:
            with spi_bus.LOCK:
                self._spi.writebytes(data)
            self._last_written = (rgb, brightness)
        except Exception as e:
            self._log(f"write failed, disabling LEDs ({e})")
            self._spi = None

    # -- state ------------------------------------------------------------
    def attach(self, output_handler):
        """The agent is ready: from now on mirror its state, not 'starting'."""
        self._handler = output_handler

    def set_hold(self, seconds, reset_after=2.0, restart_after=20.0):
        """The yellow button has been held this long (None: let go).

        From reset_after the LEDs turn white: let go now and this mode starts
        over. Two seconds later red takes over and grows brighter until
        restart_after, when the whole pipeline restarts.
        """
        self._hold = None if seconds is None else (seconds, reset_after, restart_after)

    def acknowledge(self):
        """A press that has nothing to act on yet (the phone is starting):
        one brighter breath, so it is seen to have arrived."""
        self._ack_until = time.time() + 0.6

    def show_restart(self):
        """Full red, now and for good: the pipeline restarts (the process is
        about to end, and APA102s keep their last colour)."""
        self._override = (COLOURS['error'], MAX_BRIGHTNESS)
        self._write(*self._override)

    def _state(self):
        h = self._handler
        if h is None:
            return 'starting'
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

    def _frame(self, now):
        """(rgb, brightness) to show at time now."""
        if self._override is not None:
            return self._override
        if self._hold is not None:
            held, reset_after, restart_after = self._hold
            if held >= reset_after + 2.0:
                frac = min(1.0, (held - reset_after - 2.0) / (restart_after - reset_after - 2.0))
                return COLOURS['error'], 1 + int(frac * (MAX_BRIGHTNESS - 1))
            if held >= reset_after:
                return COLOURS['hold'], MAX_BRIGHTNESS
        state = self._state()
        if state == 'starting':
            if now < self._ack_until:
                return COLOURS['starting'], MAX_BRIGHTNESS
            return COLOURS['starting'], level(breath(now, BOOT_PERIOD))
        if state == 'thinking':
            return COLOURS['thinking'], level(breath(now, PULSE_PERIOD))
        return COLOURS[state], MAX_BRIGHTNESS

    def _run(self):
        while not self._stop.is_set():
            rgb, brightness = self._frame(time.time())
            self._write(rgb, brightness)
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
