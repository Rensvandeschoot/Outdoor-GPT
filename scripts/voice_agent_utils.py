import argparse
import contextlib
import json
import os
import random
import re
import time


# Exit codes the boot script (startup_script.sh, mode 3) acts on. Anything
# else that is not 0 counts as a crash.
EXIT_RESTART_PIPELINE = 3   # asked for: restart both servers and the agent
EXIT_SERVER_STUCK = 4       # a server process runs but never became ready

# How long the agent waits for a server that is still loading. Loading the
# chat model takes ~21 s on mains and longer on the crank at 1.5 GHz; this
# is a ceiling, not a delay: the agent goes on the moment the server answers,
# and stops waiting at once if the server's process has died.
SERVER_WAIT_CEILING = 90.0


class ServerNotReady(ConnectionError):
    """A server did not become ready. stuck: its process still runs."""

    def __init__(self, message, stuck=False):
        super().__init__(message)
        self.stuck = stuck


def pid_alive(pid):
    """Does process pid still run? Read from /proc on Linux; where there is
    no /proc (a PC) the answer is unknown and taken as yes, which leaves only
    the time ceiling."""
    if not os.path.isdir('/proc'):
        return True
    try:
        with open(f'/proc/{pid}/stat') as f:
            stat = f.read()
    except OSError:
        return False
    # The state follows the command name in brackets; a zombie has exited.
    return stat.rsplit(')', 1)[-1].split()[0] not in ('Z', 'X')


def open_conversation_log(log_dir="logs"):
    """Open a new conversation log; never overwrite an old one.

    Upstream names the file after the clock alone and opens it for writing.
    Off-grid the clock cannot be trusted: after a power cut it can start again
    from the same saved time, so a later boot could take the same name and
    overwrite the earlier conversation. The name now leads with the boot
    number the boot script hands over (OUTDOORGPT_BOOT_NR), zero-padded, so
    sorting the names sorts by boot, which is how the boot script keeps the
    newest LOG_KEEP. A name that exists anyway gets a suffix. Run by hand,
    without a boot number, the name is upstream's.
    """
    from datetime import datetime
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    boot = os.environ.get('OUTDOORGPT_BOOT_NR', '')
    base = f"conversation_b{int(boot):05d}_{stamp}" if boot.isdigit() else f"conversation_{stamp}"
    for n in range(1000):
        path = os.path.join(log_dir, base + (f"_{n}" if n else "") + ".txt")
        try:
            log_file = open(path, "x", encoding="utf-8")
        except FileExistsError:
            continue
        log_file.write(f"Conversation started at {datetime.now():%Y-%m-%d %H:%M:%S}"
                       f"{f' (boot {int(boot)}; the clock is not reliable off-grid)' if boot.isdigit() else ''}\n")
        log_file.write("-" * 50 + "\n")
        log_file.flush()
        print(f">> Logging conversation to: {path}")
        return log_file
    raise RuntimeError(f"no free conversation log name for {base} in {log_dir}")


def env_pid(name):
    """A PID handed over by the boot script in environment variable name."""
    try:
        return int(os.environ.get(name, ''))
    except ValueError:
        return None


def wait_for_server(is_ready, name, pid=None, ceiling=SERVER_WAIT_CEILING, retry_delay=1.0):
    """Wait until is_ready() returns true.

    With pid (the server's process, from the boot script) the wait ends at
    once when that process has died: the boot script starts it again, and a
    dead server is not worth 90 s of waiting. Without pid, or while the
    process lives, it waits up to ceiling seconds. Raises ServerNotReady.
    """
    t0 = time.time()
    attempt = 0
    while True:
        try:
            ready = is_ready()
        except Exception:
            ready = False
        if ready:
            return
        if pid is not None and not pid_alive(pid):
            raise ServerNotReady(f"{name}: its process ({pid}) has exited")
        waited = time.time() - t0
        if waited >= ceiling:
            raise ServerNotReady(
                f"{name} not ready after {waited:.0f} s"
                + (f" although its process ({pid}) still runs" if pid is not None else ""),
                stuck=pid is not None)
        attempt += 1
        if attempt == 1 or attempt % 10 == 0:
            print(f">> Waiting for {name}... ({waited:.0f} s)")
        time.sleep(retry_delay)


@contextlib.contextmanager
def onnx_thread_cap(n):
    """Cap the intra-op threads of every onnxruntime session created inside.

    onnxruntime defaults to one thread per core, so a model that is handed no
    SessionOptions lights up all four cores of a Pi 5 for every inference:
    measured on the phone, a 5 A step on the core rail at 2.4 GHz. Piper
    (PiperVoice.load) and Moonshine (MoonshineOnnxModel) both create their
    sessions that way and offer no way to pass options in, so for the
    duration of the block onnxruntime.InferenceSession is wrapped to apply
    the cap to whatever options it is handed. Both libraries call it through
    the module attribute, which is what makes the wrap take effect. Each
    model is still loaded exactly once, where it always was. n = 0 means no
    cap and no wrap.
    """
    if not n:
        yield
        return
    try:
        import onnxruntime as ort
    except ImportError:
        yield
        return
    original = ort.InferenceSession

    def capped(path_or_bytes, sess_options=None, providers=None, **kwargs):
        opts = sess_options if sess_options is not None else ort.SessionOptions()
        opts.intra_op_num_threads = n
        return original(path_or_bytes, sess_options=opts, providers=providers, **kwargs)

    ort.InferenceSession = capped
    try:
        yield
    finally:
        ort.InferenceSession = original


DEFAULT_LLM_SERVER_URL = "http://localhost:8080/v1"
DEFAULT_LLM_SERVER_MODEL = "dummy"
DEFAULT_LLM_SERVER_API_KEY = "dummy"

DEFAULT_LANGUAGE = "en"

DEFAULT_SYSTEM_PROMPT = "Start each response with a brief, varied acknowledgment (e.g., 'Sure!', 'Hmm...', 'Ah!', 'Right!', 'Not really', 'OK so...', 'Let's see...'). Be skeptical and push back if you disagree. Never repeat the same opener twice in a row. Then give your concise answer of maximum one sentence."

DEFAULT_START_MESSAGE = "Ask me anything!"

# Conversation history kept for the model: the system prompt plus at most
# this many of the latest turns (question + answer), and at most this many
# characters of them. Without a limit the history grows with every turn
# until llama-server refuses the request (context 4096, CHAT_CONTEXT in
# config.sh), which ended the conversation after some 35 questions. 6000
# characters is ~1500-1700 tokens: with the longest system prompt and a
# full RAG block on top, that still leaves the model room to answer.
DEFAULT_MAX_HISTORY_TURNS = 8
DEFAULT_MAX_HISTORY_CHARS = 6000
DEFAULT_GOODBYE_MESSAGE = "Goodbye!"

# Spoken when a turn fails (the model server refused or dropped the
# request). With the server still there the phone carries on; without it the
# agent exits and the boot script restarts the servers and the agent.
TURN_FAILED_MESSAGE = "Sorry, something went wrong there. Please ask again."
TURN_FAILED_RESTART_MESSAGE = "Sorry, I have to restart. Give me half a minute."
DEFAULT_EXIT_COMMAND = "please quit"


def said_exit_phrase(text, phrase):
    """True if phrase occurs in text as whole words, case aside.

    A plain substring test let "can you please quite simply explain..."
    stop the agent.
    """
    if not phrase or not phrase.strip():
        return False
    pattern = r'\b' + r'\s+'.join(re.escape(w) for w in phrase.lower().split()) + r'\b'
    return re.search(pattern, text.lower()) is not None


# Recipe mode. The model prefixes a finished recipe with this marker, which
# lets the agent send it to the e-ink screen instead of reading it out loud:
# a recipe is for looking at while you cook, not for listening to. The marker
# is stripped before anything is displayed or stored.
RECIPE_MARKER = "<<RECIPE>>"
# Spoken instead of the recipe, so the phone does not just fall silent.
RECIPE_ON_SCREEN_MESSAGE = "Check the screen for your recipe. Enjoy your outdoor-meal."

# Recipe intake. Speech recognition mis-hears an accent, and a recipe built on
# a mis-heard list is a random recipe. So the list is read back from the
# recogniser's own transcript and confirmed before the model ever sees it.
# {} is the transcript.
RECIPE_READBACK = "I heard: {}. Is that right?"
RECIPE_RETRY = "Alright, tell me your ingredients again."
# What the model receives once the list is confirmed; {} is the list.
# Spoken after the list is confirmed, before the model starts: the thinking
# pause otherwise begins in silence.
RECIPE_COOKING = "Thanks. Give me a moment to put a recipe together."
RECIPE_REQUEST = "My ingredients: {}. Write the recipe."
RECIPE_YES_WORDS = {'yes', 'yeah', 'yep', 'yup', 'correct', 'right', 'exactly', 'ok',
                    'okay', 'sure', 'fine', 'go', 'cook', 'proceed', 'perfect', 'good'}
RECIPE_NO_WORDS = {'no', 'nope', 'nah', 'wrong', 'incorrect', 'not'}
# Words that may precede a correction ("no, that is not right, pasta and cheese")
# and are dropped to find the list that follows.
_NO_PREAMBLE = RECIPE_NO_WORDS | {"that's", "thats", "that", "is", "it's", "its", "the",
                                   "those", "are", "right", "wrong", "correct", "quite"}


def classify_confirmation(text):
    """Was that a yes, a no, or something else (probably a new list)?

    A no wins over a yes, so "no, that is not right" is a no. Anything with
    neither is treated as a fresh ingredient list by the caller.
    """
    words = set(re.findall("[a-z']+", text.lower()))
    if words & RECIPE_NO_WORDS:
        return 'no'
    if words & RECIPE_YES_WORDS:
        return 'yes'
    return 'other'


def strip_leading_no(text):
    """Drop a leading "no, that is not right" preamble; return what follows."""
    tokens = text.split()
    i = 0
    while i < len(tokens) and i < 6 and tokens[i].strip(",.!?;:").lower() in _NO_PREAMBLE:
        i += 1
    return ' '.join(tokens[i:]).strip(',.;: ')


class RecipeIntake:
    """Collects the ingredient list and has it confirmed before cooking.

    receive(transcript) returns one of:
        ('readback', text)  read text back and ask whether it is right
        ('retry', '')       the caller said no: ask for the list again
        ('cook', text)      confirmed: text is the list to cook from
    A transcript that is neither yes nor no while a list is pending replaces
    that list and is read back in turn.
    """

    def __init__(self):
        self.pending = None

    def reset(self):
        self.pending = None

    def receive(self, transcript):
        text = transcript.strip()
        if self.pending is None:
            self.pending = text
            return 'readback', text
        verdict = classify_confirmation(text)
        if verdict == 'yes':
            confirmed, self.pending = self.pending, None
            return 'cook', confirmed
        if verdict == 'no':
            # The correction often comes in the same breath: "no, pasta and
            # cheese". Use what follows the no as the new list when there is
            # enough of it; otherwise ask again.
            rest = strip_leading_no(text)
            if len(rest.split()) >= 3:
                self.pending = rest
                return 'readback', rest
            self.pending = None
            return 'retry', ''
        self.pending = text
        return 'readback', text


class RecipeRouter:
    """Decides, chunk by chunk, whether a streamed reply may be spoken.

    In recipe mode the model opens the recipe with RECIPE_MARKER, and everything
    after the marker goes to the screen instead of the speaker. That is only
    known once the first characters arrive, so text is held back until the
    marker is matched or ruled out. feed() returns the text that may be spoken
    now; flush() returns whatever is still held when the reply ends. Outside
    recipe mode a stray marker is stripped and the text is spoken anyway.
    """

    def __init__(self, marker, recipe_mode, expect_recipe=False):
        self.marker = marker
        self.recipe_mode = recipe_mode
        self.marker_seen = False
        self._decided = False
        self._held = ''
        if expect_recipe:
            # The caller already knows this reply is the recipe (the list was
            # confirmed and requested), so withhold it from the first character
            # whether or not the model remembers the marker.
            self.marker_seen = True
            self._decided = True

    def feed(self, text):
        if self._decided:
            return '' if (self.marker_seen and self.recipe_mode) else text
        self._held += text
        probe = self._held.lstrip()
        if probe.startswith(self.marker):
            self.marker_seen = True
            self._decided = True
            rest = probe[len(self.marker):]
            self._held = ''
            return rest if (not self.recipe_mode and rest.strip()) else ''
        if len(probe) < len(self.marker) and self.marker.startswith(probe):
            return ''                      # could still become the marker
        self._decided = True
        held, self._held = self._held, ''
        return held

    def flush(self):
        held, self._held = self._held, ''
        return held if (not self._decided and held.strip()) else ''


def get_cli_argument_parser():
    parser = argparse.ArgumentParser(description="On Device Voice Agen")
    parser.add_argument("--llm_server_url", default=DEFAULT_LLM_SERVER_URL, help="Url where LLM is served using OpenAI-compatible API format.")
    parser.add_argument("--tts_engine", choices=['piper', 'kokoro'], default="piper", help="which tts engine to use; piper is much faster than kokoro.")
    parser.add_argument("--asr_model_name", default="moonshine_v1_tiny", help="which asr model to run.")
    parser.add_argument("--asr_model_path", default="models/moonshine_v1_tiny", help="Path to the ASR model directory (use empty string to unset for models that don't need it)")
    parser.add_argument("--disable_partials", action="store_true", default=True, help="Disable partial transcription results (default: True)")
    parser.add_argument("--enable_partials", dest="disable_partials", action="store_false", help="Enable partial transcription results")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE, help="language to use")
    parser.add_argument("--tts_model_path", required=False, help="Path to the tts model (.onnx file)")
    parser.add_argument("--speaking_rate", type=float, default=1.0, help="how fast should generated speech be, 1.0 is default, higher numbers mean faster speech")
    parser.add_argument("--max_words_to_speak_start", type=int, default=10, help="maximum number of words to speech onset after a prompt; reduce if latency too high.")
    parser.add_argument("--max_words_to_speak", type=int, default=25, help="always produce speech after this many words were produced ignoring sentence boundaries.")        
    parser.add_argument("--server_wait", type=float, default=SERVER_WAIT_CEILING, help="Seconds to wait at most for each server to finish loading. A ceiling, not a delay; with the PIDs from the boot script the wait also ends at once when a server's process has died.")
    parser.add_argument("--exit_phrase", default=None, help=f"Saying this phrase (as whole words) stops the agent, e.g. '{DEFAULT_EXIT_COMMAND}'. Off by default: on the phone nobody needs to stop it by voice, and a phrase in a question would silence it.")
    parser.add_argument("--max_history_turns", type=int, default=DEFAULT_MAX_HISTORY_TURNS, help="Keep at most this many of the latest turns (question + answer) in the conversation sent to the model; older ones are dropped so the context window never overflows. 0 = no turn limit (the character limit still applies).")
    parser.add_argument("--system_prompt", default=DEFAULT_SYSTEM_PROMPT, help="Instructions for the model.")
    parser.add_argument("--start_message", default=DEFAULT_START_MESSAGE, help="Opening sentence.")
    parser.add_argument("--prompt_file", type=str, default=None, help="JSON file with prompt pairs. Format: [{\"system_prompt\": \"...\", \"start_message\": \"...\"}]. Overrides --system_prompt and --start_message.")
    parser.add_argument("--rag_index", type=str, default=None, help="Path to RAG index directory built by rag_ingest.py (chunks.json + embeddings.npy). Enables retrieval-augmented answers; requires the embedding server (start_embedding_server.sh).")
    parser.add_argument("--embedding_server_url", default="http://localhost:8081/v1", help="OpenAI-compatible embedding server url (llama.cpp with --embedding). Only used with --rag_index.")
    parser.add_argument("--rag_top_k", type=int, default=2, help="Max number of retrieved chunks to inject per question.")
    parser.add_argument("--rag_min_score", type=float, default=0.35, help="Minimum cosine similarity for a retrieved chunk to be used.")
    parser.add_argument("--tts_warmup", action="store_true", default=False, help="Synthesise a few throwaway lines at startup, after the servers are up, so the first real sentence is not also the heaviest one. Matters on crank power.")
    parser.add_argument("--tts_threads", type=int, default=0, help="Cap the onnxruntime threads Piper uses (0 = default, one per core). 2 roughly halves the current spike per sentence on a Pi 5.")
    parser.add_argument("--asr_threads", type=int, default=0, help="Same cap for Moonshine, the speech recogniser (0 = default, one per core). Every utterance is otherwise a four-core spike.")
    parser.add_argument("--min_partial_duration", type=float, default=0.25, help="Minimum duration in seconds for partial transcriptions to be displayed.",)
    parser.add_argument("--end_of_utterance_duration", type=float, default=0.7, help="Silence seconds until end of turn of user identified")
    parser.add_argument("--enable_keyboard_control", action="store_true", default=False, help="Enable keyboard control (space to mute/unmute, ESC to exit)")
    parser.add_argument("--verbose", action="store_true", help="Verbose status info")
    parser.add_argument("--show_ttfb", action="store_true", default=False, help="Measure & print per-turn TTFB (end-of-utterance to first audio spoken). Prints a summary on exit.")
    parser.add_argument("--interaction_handler", choices=['colored', 'minimal', 'whisplay', 'display_leds_interrupt'], default="colored", help="Interaction handler: 'colored' (default) for rich console output, 'minimal' for emoji status, 'whisplay' for Whisplay HAT, 'display_leds_interrupt' for Waveshare display + external LEDs + ReSpeaker button. Use --platform for GPIO interrupt button.")
    parser.add_argument("--audio-device-input", type=str, default=None,
                        help="Input audio device (mic): index (e.g. '3') or ALSA name (e.g. 'plughw:3,0')")
    parser.add_argument("--audio-device-output", type=str, default=None,
                        help="Output audio device (speaker): index (e.g. '3') or ALSA name (e.g. 'plughw:3,0')")
    parser.add_argument("--platform", choices=['rpi5', 'opi5'], default=None,
                        help="Hardware platform for GPIO: rpi5 (Raspberry Pi 5) or opi5 (Orange Pi 5 Pro)")
    parser.add_argument("--log-conversation", action="store_true", default=False,
                        help="Log conversation to a timestamped file in logs/ directory")

    return parser


def apply_audio_device_settings(args):
    """Apply audio device settings from CLI args to sounddevice defaults."""
    if args.audio_device_input is not None or args.audio_device_output is not None:
        import sounddevice as sd

        def parse_device(device_str):
            try:
                return int(device_str)
            except ValueError:
                return device_str

        if args.audio_device_input is not None:
            input_dev = parse_device(args.audio_device_input)
            sd.default.device[0] = input_dev
            name = sd.query_devices(input_dev)['name'] if isinstance(input_dev, int) else input_dev
            print(f">> Using input device: {name}")

        if args.audio_device_output is not None:
            output_dev = parse_device(args.audio_device_output)
            sd.default.device[1] = output_dev
            name = sd.query_devices(output_dev)['name'] if isinstance(output_dev, int) else output_dev
            print(f">> Using output device: {name}")

class PromptSelector:
    """Manages random selection of system_prompt/start_message pairs from a file."""

    def __init__(self, prompt_file=None, default_system_prompt=None, default_start_message=None):
        self.prompts = []
        self.last_index = -1

        if prompt_file:
            with open(prompt_file, 'r') as f:
                self.prompts = json.load(f)
            if not self.prompts:
                raise ValueError(f"Prompt file {prompt_file} is empty")
            print(f">> Loaded {len(self.prompts)} prompt pairs from {prompt_file}")
        else:
            # Use single default prompt
            self.prompts = [{
                'system_prompt': default_system_prompt or DEFAULT_SYSTEM_PROMPT,
                'start_message': default_start_message or DEFAULT_START_MESSAGE
            }]

    def get_random_prompt(self):
        """Get a random prompt pair, avoiding the last one if possible."""
        if len(self.prompts) == 1:
            return self.prompts[0]

        # Pick a different index than last time
        available = [i for i in range(len(self.prompts)) if i != self.last_index]
        self.last_index = random.choice(available)
        return self.prompts[self.last_index]


def get_ui_argument_parser():
    
    # get basic arguments
    parser = get_cli_argument_parser()

    # UI configuration arguments
    parser.add_argument("--window_size", default="470x250", help="Window size in format WIDTHxHEIGHT")
    parser.add_argument("--fullscreen", action="store_true", default=False, help="Run in fullscreen mode")
    parser.add_argument("--label_font_size", type=int, default=14, help="Font size for labels")
    parser.add_argument("--textbox_font_size", type=int, default=14, help="Font size for textboxes")
    parser.add_argument("--button_font_size", type=int, default=20, help="Font size for buttons")
    parser.add_argument("--appearance_mode", default="dark", choices=["dark", "light", "system"], help="UI appearance mode")
    parser.add_argument("--color_theme", default="blue", help="UI color theme")
    
    return parser
