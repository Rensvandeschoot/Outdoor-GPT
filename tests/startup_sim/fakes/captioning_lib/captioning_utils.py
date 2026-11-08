"""Fake captioning_lib.captioning_utils: mic stream, VAD/ASR and the transcription worker.

The import itself takes the measured 7.8 s of Python imports (numpy,
onnxruntime and friends) on the sim clock, since this is the first heavy
import of voice_agent.py.
"""
import queue
import simworld as S

S.sleep(S.W.jit(7.8, 'imports'))

SAMPLING_RATE = 16000
FRAME = 0.1  # sim seconds of audio per queued chunk


def find_default_input_device():
    return {'index': 1, 'name': 'fake-mic'}


class _Vad:
    def reset_states(self):
        pass


def get_vad(eos_min_silence=200, **kw):
    S.sleep(0.3)
    return _Vad()


class _Asr:
    pass


def load_asr_model(model_name=None, language=None, sampling_rate=16000,
                   show_word_confidence_scores=False, model_path=None, **kw):
    S.sleep(S.W.jit(6.6, 'asr_load'))
    return _Asr()


class FakeInputStream:
    def __init__(self, audio_queue):
        self.q = audio_queue
        self._active = False
        self._closed = False
        S.W.input_streams.append(self)

    @property
    def active(self):
        return self._active

    def start(self):
        if self._closed:
            raise RuntimeError('input stream closed')
        if not self._active:
            S.W.ev('mic', on=True)
        self._active = True

    def stop(self):
        if self._active:
            S.W.ev('mic', on=False)
        self._active = False

    def close(self):
        self._active = False
        self._closed = True


def get_audio_stream_callback(audio_queue, input_device_index=None, target_latency=2.0):
    s = FakeInputStream(audio_queue)
    s.start()          # the real one returns a started stream
    return s


class TranscriptionWorker:
    """Same public state as the real worker; 'transcribes' the words in each frame."""

    def __init__(self, sampling_rate=SAMPLING_RATE):
        self.sampling_rate = sampling_rate
        self.reset()

    def reset(self):
        self.is_speech_recording = False
        self.had_speech = False
        self.frames_since_last_speech = 0
        self.transcribed_segments = []
        self.last_partial_transcribed_length = 0
        self.accumulated_partial_text = ""
        self._buf = []
        self._silence = 0.0

    def time_since_last_speech(self):
        return float(self.frames_since_last_speech) / self.sampling_rate

    def transcription_worker(self, vad=None, asr=None, audio_queue=None, caption_printer=None,
                             stop_threads=None, min_partial_duration=0.2, max_segment_duration=15,
                             disable_partials=True, **kw):
        while not stop_threads.is_set():
            try:
                kind, words = audio_queue.get(timeout=0.05)   # queue is the sim-scaled one
            except queue.Empty:
                continue
            if kind == 'speech':
                if not self.is_speech_recording:
                    self.is_speech_recording = True
                    self.had_speech = True
                    self.frames_since_last_speech = 0
                    self._buf = []
                self._buf.extend(words)
                self._silence = 0.0
            else:
                if self.is_speech_recording:
                    self._silence += FRAME
                    if self._silence >= 0.2:          # Silero eos_min_silence=200 ms
                        self.is_speech_recording = False
                        self.frames_since_last_speech += int(FRAME * self.sampling_rate)
                        text = ' '.join(self._buf).strip()
                        if text:
                            caption_printer.print(text, duration=1.0, partial=False)
                            self.transcribed_segments.append(text)
                        self._buf = []
                elif self.had_speech:
                    self.frames_since_last_speech += int(FRAME * self.sampling_rate)
