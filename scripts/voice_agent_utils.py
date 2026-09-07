import argparse
import json
import random
import re

DEFAULT_LLM_SERVER_URL = "http://localhost:8080/v1"
DEFAULT_LLM_SERVER_MODEL = "dummy"
DEFAULT_LLM_SERVER_API_KEY = "dummy"

DEFAULT_LANGUAGE = "en"

DEFAULT_SYSTEM_PROMPT = "Start each response with a brief, varied acknowledgment (e.g., 'Sure!', 'Hmm...', 'Ah!', 'Right!', 'Not really', 'OK so...', 'Let's see...'). Be skeptical and push back if you disagree. Never repeat the same opener twice in a row. Then give your concise answer of maximum one sentence."

DEFAULT_START_MESSAGE = "Ask me anything!"
DEFAULT_GOODBYE_MESSAGE = "Goodbye!"
DEFAULT_EXIT_COMMAND = "please quit"

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
    parser.add_argument("--system_prompt", default=DEFAULT_SYSTEM_PROMPT, help="Instructions for the model.")
    parser.add_argument("--start_message", default=DEFAULT_START_MESSAGE, help="Opening sentence.")
    parser.add_argument("--prompt_file", type=str, default=None, help="JSON file with prompt pairs. Format: [{\"system_prompt\": \"...\", \"start_message\": \"...\"}]. Overrides --system_prompt and --start_message.")
    parser.add_argument("--rag_index", type=str, default=None, help="Path to RAG index directory built by rag_ingest.py (chunks.json + embeddings.npy). Enables retrieval-augmented answers; requires the embedding server (start_embedding_server.sh).")
    parser.add_argument("--embedding_server_url", default="http://localhost:8081/v1", help="OpenAI-compatible embedding server url (llama.cpp with --embedding). Only used with --rag_index.")
    parser.add_argument("--rag_top_k", type=int, default=2, help="Max number of retrieved chunks to inject per question.")
    parser.add_argument("--rag_min_score", type=float, default=0.35, help="Minimum cosine similarity for a retrieved chunk to be used.")
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
