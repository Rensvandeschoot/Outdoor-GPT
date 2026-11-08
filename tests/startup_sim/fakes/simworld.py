"""Simulated world for the OutdoorGPT start-up simulation.

One instance per process (W). Holds the scaled clock, the physical state
(dial and button pins, the room: who is talking), both llama servers, and
everything observed (played audio, LED frames, LLM requests, resets).

Time: every sim second lasts SCALE real seconds. time.time and time.sleep are
replaced globally, so the real agent code runs unchanged on the sim clock.
"""

import os
import queue as _queue
import random
import threading
import time as _time

_real_sleep = _time.sleep
_real_mono = _time.monotonic
SCALE = float(os.environ.get('SIM_SCALE', '0.05'))
EPOCH = 1_760_000_000.0
_t0 = _real_mono()


def now():
    return (_real_mono() - _t0) / SCALE


def sim_time():
    return EPOCH + now()


def sleep(s):
    _real_sleep(max(0.0, float(s or 0.0)) * SCALE)


def real_sleep(s):
    _real_sleep(s)


def install_clock():
    _time.time = sim_time
    _time.sleep = sleep


PIN_BUTTON = 22
DIAL_PINS = {'pos1': 23, 'pos2': 24, 'pos3': 17}
CHAT_PID = 90001        # what the boot script hands the agent in OUTDOORGPT_*_PID
EMBED_PID = 90002

W = None


class World:
    def __init__(self, cfg):
        self.cfg = cfg
        self.rng = random.Random(cfg.get('seed', 0))
        self.lock = threading.RLock()
        self.events = []
        self.pins = {}
        self.broken_pins = set(cfg.get('broken_pins', []))
        self.buttons = {}
        self.dial_pos = None
        self.played = []
        self._playing = []
        self.input_streams = []
        self.led_frames = []
        self.led_state = 'dark'
        self.llm_requests = []
        self.utterances = []
        self.va = None
        self.resets = []
        self.out_interrupts = []
        self.eink = []
        self.convlog = []
        self.presses = []
        self.boot_acks = []     # 'starting' shown at full brightness: a press acknowledged
        self.dial_moves = []
        self.stdout = []
        self.thread_exc = []
        self.gpio_cb_log = []
        self.agent_exit = None
        self.chat_start = 0.05
        self.embed_start = 0.05
        self.chat_killed_at = cfg.get('chat_kill_at')
        self.jitters = {}
        self._dispatch_q = _queue.Queue()
        threading.Thread(target=self._dispatch_loop, name='gpio-callbacks', daemon=True).start()

    # -- helpers ----------------------------------------------------------
    def ev(self, _kind, **data):
        with self.lock:
            self.events.append((round(now(), 3), _kind, data))

    def jit(self, value, key, spread=None):
        """value with seeded jitter (default +-10%, scenario may override)."""
        spread = self.cfg.get('jitter', 0.10) if spread is None else spread
        v = value * (1.0 + self.rng.uniform(-spread, spread))
        self.jitters[key] = round(v, 3)
        return v

    # -- GPIO -------------------------------------------------------------
    def register_button(self, b):
        with self.lock:
            self.buttons.setdefault(b.pin, []).append(b)

    def unregister_button(self, b):
        with self.lock:
            if b in self.buttons.get(b.pin, []):
                self.buttons[b.pin].remove(b)

    def pin_low(self, pin):
        return self.pins.get(pin, False)

    def set_pin(self, pin, low):
        with self.lock:
            if pin in self.broken_pins:
                low = False
            if self.pins.get(pin, False) == low:
                return
            self.pins[pin] = low
            edge = 'press' if low else 'release'
            delivered = False
            for b in self.buttons.get(pin, []):
                cb = b._when_pressed if low else b._when_released
                if cb is not None:
                    delivered = True
                    self._dispatch_q.put((cb, f'pin{pin}_{edge}', now()))
            if not delivered:
                self.ev('gpio_edge_lost', pin=pin, edge=edge)

    def _dispatch_loop(self):
        # lgpio runs every pin callback on one thread, in order: a slow
        # callback holds up all later ones.
        while True:
            cb, label, t_edge = self._dispatch_q.get()
            t0 = now()
            try:
                cb()
            except Exception as e:  # gpiozero would print and carry on
                self.thread_exc.append((round(now(), 2), 'gpio-callbacks', f'{type(e).__name__}: {e}'))
            self.gpio_cb_log.append((round(t_edge, 2), round(t0, 2), round(now(), 2), label))

    def init_dial(self, pos):
        self.dial_pos = pos
        for p, pin in DIAL_PINS.items():
            self.pins[pin] = (p == pos) and pin not in self.broken_pins
        # button_stuck: the button pin reads pressed from power-up (a wiring
        # fault, a normally-closed switch, a stuck button).
        self.pins[PIN_BUTTON] = bool(self.cfg.get('button_stuck'))

    def turn_dial(self, pos, gap=0.04, bounce=0):
        """Break-before-make: old contact opens, then the new one closes."""
        old = self.dial_pos
        self.dial_moves.append((round(now(), 2), old, pos))
        self.ev('dial', frm=old, to=pos)
        if old in DIAL_PINS:
            self.set_pin(DIAL_PINS[old], False)
        sleep(gap)
        self.dial_pos = pos
        if pos in DIAL_PINS:
            pin = DIAL_PINS[pos]
            for _ in range(bounce):
                self.set_pin(pin, True)
                sleep(0.004)
                self.set_pin(pin, False)
                sleep(0.004)
            self.set_pin(pin, True)

    def press(self, dur):
        # Recorded when pressed, completed when let go: a 20 s hold ends the
        # run (pipeline restart) before it is let go.
        rec = {'down': round(now(), 2), 'up': None, 'dur': dur, 'state_at_up': {}}
        self.presses.append(rec)
        self.ev('press', dur=dur)
        self.set_pin(PIN_BUTTON, True)
        sleep(dur)
        self.set_pin(PIN_BUTTON, False)
        rec.update(up=round(now(), 2), state_at_up=self.snapshot_state())

    # -- servers ----------------------------------------------------------
    def chat_ready(self):
        c = self.cfg
        if c.get('chat_dead') or c.get('chat_stuck'):
            return False
        if self.chat_killed_at is not None and now() >= self.chat_killed_at:
            return False
        return now() >= self.chat_start + c['_chat_load']

    def embed_ready(self):
        if self.cfg.get('embed_dead'):
            return False
        return now() >= self.embed_start + self.cfg['_embed_load']

    def server_alive(self, pid):
        """Stands in for voice_agent_utils.pid_alive. chat_dead / embed_dead:
        the process exited at once (a model file missing); chat_stuck: it runs
        but never answers; kill_chat: it dies at that moment."""
        c = self.cfg
        if pid == CHAT_PID:
            killed = self.chat_killed_at is not None and now() >= self.chat_killed_at
            return not c.get('chat_dead') and not killed
        if pid == EMBED_PID:
            return not c.get('embed_dead')
        return True

    # -- audio ------------------------------------------------------------
    @property
    def playing(self):
        with self.lock:
            return self._playing[-1] if self._playing else None

    def play(self, stream, audio):
        t0 = now()
        with self.lock:
            rec = {'start': round(t0, 2), 'text': audio.text, 'dur': round(audio.dur, 2),
                   'aborted': False, 'thread': threading.current_thread().name,
                   'overlap': bool(self._playing),
                   'mode_at_start': self.va_mode()}
            self.played.append(rec)
            self._playing.append(rec)
        end = t0 + audio.dur
        try:
            while now() < end:
                if stream._aborted or not stream._active:
                    rec['aborted'] = True
                    break
                _real_sleep(0.0005)
        finally:
            rec['end'] = round(now(), 2)
            with self.lock:
                self._playing.remove(rec)

    def mic_active(self):
        return any(s._active for s in list(self.input_streams))

    def say(self, text, dur=None):
        words = text.split()
        dur = dur or max(1.0, 0.38 * len(words))
        t0 = now()
        u = {'t0': t0, 't1': t0 + dur, 'text': text, 'words': words}
        with self.lock:
            self.utterances.append(u)
        self.ev('say', text=text[:60])
        sleep(dur)
        return u

    def frame(self, t_from, t_to):
        """What the microphone picks up between t_from and t_to."""
        words, speech = [], False
        with self.lock:
            for u in self.utterances:
                if u['t0'] < t_to and u['t1'] > t_from:
                    speech = True
                    n = len(u['words'])
                    for i, w in enumerate(u['words']):
                        tw = u['t0'] + (i + 0.5) * (u['t1'] - u['t0']) / n
                        if t_from <= tw < t_to:
                            words.append(w)
            for p in self._playing:
                # The speaker sits a few cm from the HAT's microphones: an open
                # mic hears the agent. Tagged so it can be recognised later.
                speech = True
                pw = p['text'].split()
                n = max(1, len(pw))
                for i, w in enumerate(pw):
                    tw = p['start'] + (i + 0.5) * p['dur'] / n
                    if t_from <= tw < t_to:
                        words.append('«' + w + '»')
        return ('speech' if speech else 'silence', words)

    # -- LEDs -------------------------------------------------------------
    def led_frame(self, data):
        bri = data[4] & 0x1F
        b, g, r = data[5], data[6], data[7]
        state = '?'
        import device_settings
        for name, rgb in device_settings.LED_COLOURS.items():
            if tuple(rgb) == (r, g, b):
                state = name
        if bri == 0 or (r, g, b) == (0, 0, 0):
            state = 'off'
        with self.lock:
            if state != self.led_state:
                self.led_frames.append((round(now(), 2), state))
            self.led_state = state
            if state == 'starting' and bri >= device_settings.LED_MAX_BRIGHTNESS:
                self.boot_acks.append(round(now(), 2))

    # -- agent state ------------------------------------------------------
    def va_mode(self):
        va = self.va
        try:
            return mode_of(va.output_handler.system_prompt)
        except Exception:
            return None

    def snapshot_state(self):
        va = self.va
        s = {'led': self.led_state, 'mic': self.mic_active(),
             'playing': (self.playing or {}).get('text', '')[:40] if self.playing else None,
             'dial': self.dial_pos}
        try:
            oh = va.output_handler
            s.update(gen=oh.is_generating, spk=oh.is_speaking, proc=oh.is_processing,
                     recipe_mode=oh.recipe_mode, delivered=oh.recipe_delivered,
                     mode=mode_of(oh.system_prompt))
        except Exception:
            pass
        return s

    def new_convlog(self):
        return _ConvLog(self)


class _ConvLog:
    def __init__(self, w):
        self.w = w

    def write(self, s):
        self.w.convlog.append((round(now(), 2), s.rstrip('\n')))

    def flush(self):
        pass

    def close(self):
        pass


def mode_of(system_prompt):
    sp = (system_prompt or '').lower()
    if 'outdoor guide' in sp:
        return 'TIPS'
    if 'campfire cook' in sp:
        return 'RECIPE'
    if 'survival expert' in sp:
        return 'SURVIVE'
    return 'OTHER'
