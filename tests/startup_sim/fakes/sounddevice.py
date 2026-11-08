"""Fake sounddevice: an output stream that 'plays' FakeAudio on the sim clock."""
import simworld as S


class PortAudioError(Exception):
    pass


class _Default:
    def __init__(self):
        self.device = [None, None]


default = _Default()


def query_devices(dev=None, kind=None):
    return {'name': f'fake-device-{dev}', 'default_samplerate': 16000,
            'max_input_channels': 2, 'max_output_channels': 2}


def check_input_settings(**kw):
    return None


class OutputStream:
    def __init__(self, samplerate=None, blocksize=None, channels=1, dtype='int16', **kw):
        self._active = False
        self._closed = False
        self._aborted = False

    @property
    def active(self):
        return self._active

    def start(self):
        if self._closed:
            raise PortAudioError('stream closed')
        self._active = True
        self._aborted = False

    def stop(self):
        self._active = False

    def abort(self):
        self._aborted = True
        self._active = False

    def close(self):
        self._active = False
        self._closed = True

    def write(self, audio):
        if not self._active:
            raise PortAudioError('Stream is stopped')
        S.W.play(self, audio)
