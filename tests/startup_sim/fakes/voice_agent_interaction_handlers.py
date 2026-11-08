import simworld as S


class ColoredHandler:
    def __init__(self, title='', color='', *a, **k):
        self.title = title

    def start(self):
        pass

    def print(self, transcript, duration=None, partial=False, **kw):
        if not partial and str(transcript).strip():
            S.W.ev('print', who=self.title, text=str(transcript)[:100])

    def show_idle(self, text=None):
        if text:
            S.W.ev('idle', who=self.title, text=str(text)[:80])

    def show_interrupted(self):
        S.W.ev('interrupted_ui')

    def cleanup(self):
        pass

    def setup_keyboard_controls(self, cbs):
        pass


def get_handler(handler_type, title, title_color='blue', is_agent=False):
    return ColoredHandler(title, title_color)


class LoggingHandlerWrapper:
    def __init__(self, handler, log_file, role):
        self._handler = handler
        self._log_file = log_file
        self._role = role

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def print(self, transcript, duration=None, partial=False, **kwargs):
        if not partial and transcript.strip():
            self._log_file.write(f"{self._role}: {transcript}\n")
        return self._handler.print(transcript, duration=duration, partial=partial, **kwargs)


def create_conversation_log_file(log_dir="logs"):
    return S.W.new_convlog()
