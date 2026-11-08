"""Fake Piper: load and synthesis cost on the sim clock; audio is (text, duration)."""
import simworld as S


class FakeAudio:
    def __init__(self, text, dur):
        self.text = text
        self.dur = dur


class TTS_Piper:
    def __init__(self, model_path=None, warmup=False):
        S.sleep(S.W.jit(2.7, 'piper_load'))
        self.model_path = model_path or 'models/piper/en_US-lessac-low.onnx'

    def get_sample_rate(self):
        return 16000

    def synthesize(self, text, target_sr=None, speaking_rate=1.0, return_as_int16=True, **kw):
        n = len(text.split())
        S.sleep(0.08 + 0.025 * n)
        return FakeAudio(text, max(0.5, 0.32 * n) / (speaking_rate or 1.0)), 16000

    def warmup(self, target_sr=None):
        S.sleep(1.5)


class TTS_Kokoro(TTS_Piper):
    pass
