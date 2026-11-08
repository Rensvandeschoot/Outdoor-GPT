"""The yellow button: a press, a 2 s hold and a 20 s hold.

    press           stop the phone talking or thinking; in recipes, a new recipe
    hold 2 s        start this mode over: its opening line, a cleared conversation
    hold 20 s       restart the whole pipeline: both servers and the agent

upstream's gpio_inputs reports a press only when it is released, and sends a
hold of 2 s or more to a long-press callback that OutdoorGPT never set, so a
long press did nothing at all. A 20 s hold must act at 20 s, while the button
is still down, so the user knows when to let go. So the button is read here
directly, 20 times a second, by its own thread, which also drives the LED
feedback while it is held. Its actions run on a second thread: stopping
speech waits for the sentence being played, and that must never hold up
reading the button. The 20 s restart runs on the reading thread itself, so it
still works when everything else is stuck.

Time comes from time.time and time.sleep only, so the start-up simulation
(tests/startup_sim) can run this on its scaled clock.
"""

import queue
import threading
import time

HOLD_RESET = 2.0        # seconds held: start this mode over
HOLD_RESTART = 20.0     # seconds held: restart the whole pipeline
POLL = 0.05             # how often the button is read


class ButtonGestures:
    def __init__(self, is_pressed, on_press, on_hold, on_restart, leds=None, verbose=False):
        """is_pressed: callable, True while the button is down.
        on_press / on_hold: run on the actions thread, in order.
        on_restart: run on the reading thread when HOLD_RESTART is reached.
        leds: a StatusLeds, shown how long the button has been held."""
        self._is_pressed = is_pressed
        self._on_press = on_press
        self._on_hold = on_hold
        self._on_restart = on_restart
        self._leds = leds
        self._verbose = verbose
        self._actions = queue.Queue()
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._watch, name='button-watch', daemon=True).start()
        threading.Thread(target=self._act, name='button-actions', daemon=True).start()

    def stop(self):
        self._stop.set()

    def _hold_display(self, seconds):
        if self._leds is not None:
            self._leds.set_hold(seconds, HOLD_RESET, HOLD_RESTART)

    def _watch(self):
        down_since = None
        restarted = False
        # Only a press that starts after the button has been seen released
        # counts. A button that reads pressed from the start (a wiring fault,
        # a normally-closed switch, a stuck button) would otherwise look like
        # a 20 s hold on every start and restart the pipeline in a loop.
        armed, warned = False, False
        while not self._stop.is_set():
            try:
                down = bool(self._is_pressed())
            except Exception:
                down = False
            if not armed:
                if down:
                    if not warned:
                        print(">> WARNING: the yellow button reads pressed at start-up; it is ignored "
                              "until it reads released. Check its wiring with ./check_gpio.sh")
                        warned = True
                    time.sleep(POLL)
                    continue
                armed = True
                if warned:
                    print(">> The yellow button reads released now; it works from here on")
            now = time.time()
            if down:
                if down_since is None:
                    down_since, restarted = now, False
                held = now - down_since
                self._hold_display(held)
                if held >= HOLD_RESTART and not restarted:
                    restarted = True
                    self._on_restart()
            elif down_since is not None:
                held, down_since = now - down_since, None
                self._hold_display(None)
                if not restarted:
                    # Always logged: one line per press, so the boot log shows
                    # what the button did.
                    print(f">> Button {'held' if held >= HOLD_RESET else 'pressed'} {held:.1f} s")
                    self._actions.put(self._on_hold if held >= HOLD_RESET else self._on_press)
            time.sleep(POLL)

    def _act(self):
        while not self._stop.is_set():
            try:
                action = self._actions.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                action()
            except Exception as e:
                print(f"[button] action failed: {type(e).__name__}: {e}")
