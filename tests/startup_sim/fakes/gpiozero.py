"""Fake gpiozero: Button on the simulated pins, callbacks on one thread (like lgpio)."""
import simworld as S


class Button:
    def __init__(self, pin, pull_up=True, bounce_time=None, **kw):
        self.pin = pin
        self._when_pressed = None
        self._when_released = None
        S.W.register_button(self)

    @property
    def is_pressed(self):
        return S.W.pin_low(self.pin)

    @property
    def when_pressed(self):
        return self._when_pressed

    @when_pressed.setter
    def when_pressed(self, fn):
        self._when_pressed = fn
        S.W.ev('gpio_cb_set', pin=self.pin, edge='press')

    @property
    def when_released(self):
        return self._when_released

    @when_released.setter
    def when_released(self, fn):
        self._when_released = fn
        S.W.ev('gpio_cb_set', pin=self.pin, edge='release')

    def close(self):
        S.W.unregister_button(self)


class LED:
    def __init__(self, pin, **kw):
        self.pin = pin

    def on(self):
        pass

    def off(self):
        pass

    def close(self):
        pass
