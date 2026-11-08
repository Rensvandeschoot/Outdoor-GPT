"""Fake e-ink panel: newest job wins, each refresh holds the shared SPI lock."""
import threading

import simworld as S
import spi_bus


class EinkRecipeDisplay:
    def __init__(self, verbose=False):
        self._lock = threading.Lock()
        self._pending = None
        self._worker = None

    def render_async(self, text):
        if text:
            self._queue(('recipe', text))

    def render_image_async(self, path=None):
        self._queue(('card', None))

    def _queue(self, job):
        S.W.ev('eink_queued', kind=job[0])
        with self._lock:
            self._pending = job
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._drain, name='eink', daemon=True)
            self._worker.start()

    def _drain(self):
        while True:
            with self._lock:
                job, self._pending = self._pending, None
                if job is None:
                    return
            kind, text = job
            with spi_bus.LOCK:
                t0 = S.now()
                S.sleep(7.0 if kind == 'card' else 4.5)   # 4-grey card is the slow one
                S.W.eink.append({'t0': round(t0, 2), 't1': round(S.now(), 2), 'kind': kind,
                                 'text': (text or '')[:200]})
