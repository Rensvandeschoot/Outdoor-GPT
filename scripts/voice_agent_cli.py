# CLI for the conversational voice agent, OutdoorGPT build.
#
# Usage:
#
#   python voice_agent_cli.py                                   # random prompt, no hardware
#   python voice_agent_cli.py --platform rpi5                   # GPIO: interrupt button + rotary dial
#   python voice_agent_cli.py --prompt_file prompts.json --rag_index rag_index
#   python voice_agent_cli.py --enable_keyboard_control
#   python voice_agent_cli.py --verbose
#
# A prompt in prompts.json may carry, besides system_prompt and start_message:
#   "mode": "recipe"          one recipe per session, drawn on the e-ink panel
#   "rag": false              no retrieval in that mode
#   "silence_seconds": 1.5    how long to wait after the caller stops talking
#
# Controls:
#   Rotary dial       - selects one of the first three prompts (full reset)
#   Yellow button     - press: stops the agent talking or thinking; in recipe
#                       mode (a recipe being written or delivered) starts a
#                       new recipe instead
#                     - hold 2 s: starts this mode over (opening line,
#                       cleared conversation)
#                     - hold 20 s: restarts the whole pipeline (exit code 3
#                       for the boot script); see button_gestures.py
#   Keyboard (with --enable_keyboard_control):
#     ENTER           - same as a press of the button
#     SPACE           - mute / unmute the microphone
#     g / s / f       - prompt 1 / 2 / 3, mirroring the dial
#
# Exit: Ctrl-C. Stopping by voice is off by default (on the phone it would only
# silence it until the boot script restarts it); --exit_phrase "please quit"
# turns it on for a session at a desk, matched as whole words.

import os
import sys
import tempfile
import threading
import time
start_time = time.time()
print("Loading Voice Agent...")

# Light imports only up here. The heavy ones (numpy, onnxruntime, the speech
# libraries: ~8 s on the Pi) come inside main(), after the status LEDs and
# the GPIO are up, so the phone shows it is starting from its first second
# instead of staying dark for half a minute.
import voice_agent_utils
from opi.gpio_utils import POSITION_KEYS

# Rotary dial: 3 positions mapped to the first 3 prompts in prompts.json.
ROTARY_POSITION_TO_PROMPT_INDEX = {
    'pos1': 0,
    'pos2': 1,
    'pos3': 2,
}
ROTARY_SETTLE_DELAY = 0.5


def hold_single_instance_lock():
    """Refuse to run next to another agent; return the lock (keep it open).

    A second agent, started by hand while the boot service runs one, fails
    on the GPIO pins, the sound card or the server ports with errors that
    do not say why. This says why. Linux only (fcntl); elsewhere no lock.
    """
    try:
        import fcntl
    except ImportError:
        return None
    lock_dir = '/run' if os.access('/run', os.W_OK) else tempfile.gettempdir()
    lock = open(os.path.join(lock_dir, 'outdoorgpt-agent.lock'), 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(">> Another OutdoorGPT agent is already running, probably the boot service. "
              "Stop it first: systemctl stop dietpi-autostart_custom.service")
        sys.exit(1)
    return lock


def main():
    """Main function to run the LLM to Audio output streamer."""

    parser = voice_agent_utils.get_cli_argument_parser()
    args = parser.parse_args()
    instance_lock = hold_single_instance_lock()  # noqa: F841 - held until exit

    # Status LEDs first: a slow turquoise breath from the first second until
    # the agent is ready (attach() below). Fail-safe: no HAT, no spidev, no
    # LEDs and the agent is unaffected.
    from leds import StatusLeds, boot_mode_from_env
    # After an error the boot script says how many starts failed in a row;
    # the start-up breath then shows it in red (leds.py).
    boot_mode = boot_mode_from_env()
    status_leds = StatusLeds(verbose=args.verbose, boot=boot_mode)
    if status_leds.start():
        print(">> Status LEDs active (turquoise breath=starting, green=your turn, "
              "blue=thinking, amber=speaking, purple=done, red=something went wrong)")
    if boot_mode != 'normal':
        print(f">> Starting after {os.environ.get('OUTDOORGPT_FAILED_STARTS')} failed start(s) in a row: "
              f"LEDs show '{boot_mode}'. The boot logs are in logs/boot/.")

    # Setup GPIO handler early so we can read the rotary dial for the initial prompt
    gpio_handler = None
    if args.platform:
        from gpio_inputs import RaspberryPi5GPIOHandler, OrangePi5ProGPIOHandler
        if args.platform == 'rpi5':
            gpio_handler = RaspberryPi5GPIOHandler()
        elif args.platform == 'opi5':
            gpio_handler = OrangePi5ProGPIOHandler()
        gpio_handler.setup(add_interrupt_button=True, add_rotary_dial=True)
        print(f">> GPIO handler: {gpio_handler.__class__.__name__}")

    # The yellow button, watched from now on, while the models still load
    # (button_gestures.py). Press and 2 s hold need the agent, which does not
    # exist yet: until it does (ctx['va']), they only show on the LEDs that
    # they arrived. The 20 s hold works from the start.
    ctx = {'va': None, 'log_file': None}

    def gesture_press():
        if ctx['va'] is None:
            status_leds.acknowledge()
        else:
            ctx['on_press']()

    def gesture_hold():
        if ctx['va'] is None:
            status_leds.acknowledge()
        else:
            ctx['on_hold']()

    def gesture_restart():
        """Held 20 s: restart both servers and the agent (the boot script does
        that on exit code EXIT_RESTART_PIPELINE). os._exit, not sys.exit: this
        must work even when the rest of the agent hangs."""
        print(">> Button held 20 s: restarting the whole pipeline")
        status_leds.show_restart()
        if ctx['log_file']:
            try:
                ctx['log_file'].write("\n[RESTART] button held 20 s\n")
                ctx['log_file'].flush()
            except Exception:
                pass
        sys.stdout.flush()
        os._exit(voice_agent_utils.EXIT_RESTART_PIPELINE)

    button = None
    if gpio_handler:
        from button_gestures import ButtonGestures
        button = ButtonGestures(gpio_handler.is_interrupt_pressed, gesture_press, gesture_hold,
                                gesture_restart, leds=status_leds, verbose=args.verbose)
        button.start()
        print(">> Yellow button: press = stop (a new recipe in recipes), hold 2 s = start this mode over, "
              "hold 20 s = restart everything")

    # The e-ink panel next, before any model loads: the instruction card goes
    # up while the phone is still starting, so the screen explains what to do
    # from the first seconds of power. After the GPIO setup on purpose, so the
    # two never initialise the pin backend at the same time. Fail-safe: with
    # no panel this does nothing.
    from eink_display import EinkRecipeDisplay
    eink = EinkRecipeDisplay(verbose=args.verbose)
    eink.render_image_async()

    # Now the heavy imports, with the LEDs breathing and the card going up.
    from voice_agent import VoiceAgent
    from voice_agent_interaction_handlers import get_handler, LoggingHandlerWrapper, create_conversation_log_file
    print(f">> -- All imports done in {time.time() - start_time:.2f} seconds -- <<")

    voice_agent_utils.apply_audio_device_settings(args)

    # Setup prompt selector (either from file or CLI args)
    prompt_selector = voice_agent_utils.PromptSelector(
        prompt_file=args.prompt_file,
        default_system_prompt=args.system_prompt,
        default_start_message=args.start_message
    )

    # Pick initial prompt: from the rotary dial; without GPIO (a PC), random
    initial_prompt = None
    if gpio_handler:
        rotary_pos = gpio_handler.get_current_position()
        idx = ROTARY_POSITION_TO_PROMPT_INDEX.get(rotary_pos)
        if idx is not None and idx < len(prompt_selector.prompts):
            initial_prompt = prompt_selector.prompts[idx]
            print(f">> Initial prompt from rotary dial position '{rotary_pos}': {initial_prompt.get('name', 'unnamed')}")
        else:
            # The dial rests between two positions, or a wire is loose. A
            # random pick made the phone start differently on every boot;
            # position 1 at least is the same every time. If the dial settles
            # before the phone is ready, adopt_dial_position() takes it over.
            initial_prompt = prompt_selector.prompts[0]
            print(f">> WARNING: no rotary position detected (got {rotary_pos!r}): between two "
                  f"positions, or a loose wire? Starting in position 1: {initial_prompt.get('name', 'unnamed')}")
    if initial_prompt is None:
        initial_prompt = prompt_selector.get_random_prompt()

    # A prompt may set its own silence window (silence_seconds in prompts.json);
    # the CLI value is the default for the ones that do not.
    def silence_for(prompt):
        return float(prompt.get('silence_seconds', args.end_of_utterance_duration))

    t1 = time.time()
    print(">> Initializing Voice Agent <<")
    va = VoiceAgent(verbose=args.verbose, exit_phrase=args.exit_phrase)

    # Create interaction handlers
    user_interaction_handler = get_handler(args.interaction_handler, "User Input", "blue", is_agent=False)
    agent_interaction_handler = get_handler(args.interaction_handler, "Agent Output", "magenta", is_agent=True)

    # Wrap with logging if requested
    log_file = None
    if args.log_conversation:  # argparse converts --log-conversation to log_conversation
        log_file = create_conversation_log_file()
        user_interaction_handler = LoggingHandlerWrapper(user_interaction_handler, log_file, "USER")
        agent_interaction_handler = LoggingHandlerWrapper(agent_interaction_handler, log_file, "AGENT")
        # Log initial prompt name
        prompt_name = initial_prompt.get('name', 'unnamed')
        log_file.write(f"[PROMPT] {prompt_name}\n")
        log_file.flush()

    va.init_AudioToText(
        asr_model_name=args.asr_model_name,
        asr_model_path=args.asr_model_path if args.asr_model_path else None,
        disable_partials=args.disable_partials,
        language=args.language,
        min_partial_duration=args.min_partial_duration,
        end_of_utterance_duration=silence_for(initial_prompt),
        verbose=args.verbose,
        printer=user_interaction_handler,
        asr_threads=args.asr_threads,
    )
    print(f">> Initialized AudioToTextInput in {time.time() - start_time:.2f} seconds -- <<")

    # Optional RAG retriever (needs the embedding server; see config.sh for the port)
    rag_retriever = None
    if args.rag_index:
        from rag import RagRetriever
        rag_retriever = RagRetriever(
            index_dir=args.rag_index,
            embedding_server_url=args.embedding_server_url,
            top_k=args.rag_top_k,
            min_score=args.rag_min_score,
            server_pid=voice_agent_utils.env_pid('OUTDOORGPT_EMBED_PID'),
            server_wait=args.server_wait,
        )
        print(f">> RAG enabled: {len(rag_retriever.chunks)} chunks from '{args.rag_index}'")

    va.init_LLmToAudioOutput(
        llm_server_url=args.llm_server_url,
        system_prompt=initial_prompt['system_prompt'],
        start_message=initial_prompt['start_message'],
        tts_engine=args.tts_engine,
        speaking_rate=args.speaking_rate,
        tts_model_path=args.tts_model_path,
        max_words_to_speak_start=args.max_words_to_speak_start,
        max_words_to_speak=args.max_words_to_speak,
        max_history_turns=args.max_history_turns,
        split_on_punctuation=False,
        verbose=args.verbose,
        single_turn=False,  # Conversational agent keeps history
        printer=agent_interaction_handler,
        show_ttfb=args.show_ttfb,
        rag_retriever=rag_retriever,
        recipe_mode=initial_prompt.get('mode') == 'recipe',
        rag_enabled=initial_prompt.get('rag', True),
        tts_warmup=args.tts_warmup,
        tts_threads=args.tts_threads,
        eink=eink,
        # Set by the boot script, so a dead server ends the wait at once.
        server_pid=voice_agent_utils.env_pid('OUTDOORGPT_CHAT_PID'),
        server_wait=args.server_wait,
    )
    print(f">> Initialized LLmToAudioOutput in {time.time() - start_time:.2f} seconds -- <<")

    # The LEDs stop breathing 'starting' and mirror the agent from here on.
    # They read the handler's own state, so there is nothing to keep in sync
    # at the call sites.
    status_leds.attach(va.output_handler)

    va.start()
    print(f">> Took {time.time()-t1:.2f} secs to initialize Voice Agent <<")

    # full start time to ready
    print(f">> --  Voice Agent ready in {time.time()-start_time:.2f} seconds -- <<")

    # Define button callbacks (used by both GPIO button and keyboard)
    button_press_count = {'n': 0}
    # Which prompt is active now, so the button can restart the same mode.
    current_prompt = {'p': initial_prompt}

    def on_interrupt_agent():
        """Interrupt agent's speech output and discard pending input."""
        button_press_count['n'] += 1
        if args.verbose:
            print(f"\n[Interrupt agent #{button_press_count['n']}] at {time.time():.2f}")
        va.debug_state("interrupt_start")

        # Acquire stream lock to prevent get_speech_input from starting mic
        # while we're draining audio
        va.input_handler.acquire_stream_lock()
        va.debug_state("interrupt_got_stream_lock")
        try:
            # Interrupt input to discard any partial transcription
            va.input_handler.interrupt()
            va.debug_state("interrupt_after_input_interrupt")

            # Interrupt output to stop speech (includes 0.5s audio drain wait)
            va.output_handler.interrupt()
            va.debug_state("interrupt_after_output_interrupt")

            if hasattr(user_interaction_handler, 'show_interrupted'):
                user_interaction_handler.show_interrupted()

            # Don't clear interrupt_event here - let process_prompt() see it and exit
            # The event will be cleared at the start of next process_prompt() call
            # Don't unmute here either - the main run() loop handles it
        finally:
            va.input_handler.release_stream_lock()
            va.debug_state("interrupt_released_lock")

        user_interaction_handler.start()
        if args.verbose:
            print(f"[Interrupt agent #{button_press_count['n']} done]")

    def on_button_press():
        """Short press: stop the agent talking or thinking; in recipes, start
        a fresh recipe session."""
        # No instruction card here (only at start-up and on the 2 s hold): a
        # redraw holds the SPI bus shared with the LEDs for ~7 s, so the
        # lights froze after every press, just when they should show what
        # the press did. In recipes the last recipe stays up until the next
        # one is drawn.
        oh = va.output_handler
        # Recipe mode delivers one recipe and then stops listening, so there is
        # nothing to interrupt. Restart the same mode instead: cleared context
        # and the opening question again, ready for new ingredients. The same
        # while a recipe is being written: the press means "not this one".
        if getattr(oh, 'recipe_delivered', False) or getattr(oh, 'recipe_requested', False):
            switch_to_prompt(current_prompt['p'])
            return
        if oh.is_speaking or oh.is_processing:
            on_interrupt_agent()
            return
        # The thinking pause (blue): drop this question and listen again; the
        # conversation stays. A press here used to do nothing.
        if getattr(oh, 'is_generating', False):
            va.request_cancel()

    def on_button_hold():
        """Held 2 s: start this mode over, its opening line and a cleared
        conversation; in recipes that is a new recipe. The instruction card
        goes back on the screen: starting over is what a newcomer does."""
        eink.render_image_async()
        switch_to_prompt(current_prompt['p'])

    def switch_to_prompt(new_prompt):
        # Called from the dial's timer and the button's callback thread. The
        # reset itself happens in the agent's run loop between turns;
        # request_reset only cuts the current turn short and returns.
        current_prompt['p'] = new_prompt
        if log_file:
            prompt_name = new_prompt.get('name', 'unnamed')
            log_file.write(f"\n[RESET] [PROMPT] {prompt_name}\n")
            log_file.flush()
        va.request_reset(
            system_prompt=new_prompt['system_prompt'],
            start_message=new_prompt['start_message'],
            recipe_mode=new_prompt.get('mode') == 'recipe',
            rag_enabled=new_prompt.get('rag', True),
            silence_seconds=silence_for(new_prompt)
        )

    # The button now acts on the agent (it was watched since the start). Its
    # upstream callback (gpio_handler.set_interrupt_callback) is not used:
    # that one fires on release only, and swallows holds of 2 s or more.
    ctx.update(on_press=on_button_press, on_hold=on_button_hold, log_file=log_file)
    ctx['va'] = va

    # -- rotary switch -> prompt selection --
    # Debounce so dial sweeps don't queue multiple prompt switches, and
    # suppress repeat events for the position we already applied (mechanical
    # bounce on the rotary can keep firing after the dial has settled).
    # last_applied_pos is set by adopt_dial_position() below, once the
    # callback is listening.
    rotary_state = {'timer': None, 'last_applied_pos': None}

    def switch_to_position(rotary_pos):
        idx = ROTARY_POSITION_TO_PROMPT_INDEX.get(rotary_pos)
        if idx is None or idx >= len(prompt_selector.prompts):
            return
        if rotary_state['timer'] is not None:
            rotary_state['timer'].cancel()

        def fire():
            if rotary_state['last_applied_pos'] == rotary_pos:
                return  # dial already at this position; ignore bounce
            rotary_state['last_applied_pos'] = rotary_pos
            switch_to_prompt(prompt_selector.prompts[idx])

        rotary_state['timer'] = threading.Timer(ROTARY_SETTLE_DELAY, fire)
        rotary_state['timer'].start()

    def adopt_dial_position():
        """Start in whatever mode the dial shows now, with its callback live.

        The prompt was picked from the dial right after the GPIO setup, but
        turns only reach switch_to_position from here on, some 20 seconds
        later on the Pi. A turn in between was lost: the phone started in
        the old mode while the dial pointed at another, and stayed there.
        Reading the dial again after the callback is in place closes that
        gap: this read covers every turn before it, the callback every turn
        after. The agent is not running yet, so nothing is said; run() opens
        with this prompt's start message.
        """
        pos = gpio_handler.get_current_position()
        idx = ROTARY_POSITION_TO_PROMPT_INDEX.get(pos)
        if idx is None or idx >= len(prompt_selector.prompts):
            return  # between two positions: keep the prompt picked at start-up
        rotary_state['last_applied_pos'] = pos
        prompt = prompt_selector.prompts[idx]
        if prompt is current_prompt['p']:
            return
        current_prompt['p'] = prompt
        print(f">> Dial turned during start-up, now at '{pos}': {prompt.get('name', 'unnamed')}")
        if log_file:
            log_file.write(f"[PROMPT] {prompt.get('name', 'unnamed')} (dial turned during start-up)\n")
            log_file.flush()
        va.configure_prompt(
            system_prompt=prompt['system_prompt'],
            start_message=prompt['start_message'],
            recipe_mode=prompt.get('mode') == 'recipe',
            rag_enabled=prompt.get('rag', True),
            silence_seconds=silence_for(prompt),
        )

    if gpio_handler:
        gpio_handler.set_position_change_callback(switch_to_position)
        print(f">> Rotary switch listener active (3 positions -> first 3 prompts)")
        adopt_dial_position()

    # Setup keyboard controls via the interaction handler
    if args.enable_keyboard_control and hasattr(user_interaction_handler, 'setup_keyboard_controls'):
        # Track mute state for toggle
        mute_state = {'is_muted': False}

        def on_mute_toggle():
            if mute_state['is_muted']:
                va.unmute_microphone()
                mute_state['is_muted'] = False
                print("\r\033[K🎤 Microphone ACTIVE")
            else:
                va.mute_microphone()
                mute_state['is_muted'] = True
                print("\r\033[K🔇 Microphone MUTED")

        key_callbacks = {
            'enter': on_button_press,
            'space': on_mute_toggle,
        }
        # Bind g/s/f (or whatever POSITION_KEYS defines) to switch prompts,
        # mirroring the rotary dial.
        for key, pos in POSITION_KEYS.items():
            key_callbacks[key] = lambda p=pos: switch_to_position(p)

        user_interaction_handler.setup_keyboard_controls(key_callbacks)

        keys_str = "/".join(k.upper() for k in POSITION_KEYS)
        print(f"Keyboard controls: ENTER=interrupt | SPACE=mute/unmute | {keys_str}=switch prompt")

    # Run the voice agent
    try:
        va.run()
    except KeyboardInterrupt:
        print("\n>> Interrupted by user (Ctrl-C)")
    finally:
        status_leds.stop()
        # TTFB summary (EOU -> first audio played)
        if args.show_ttfb:
            history = getattr(va.output_handler, 'ttfb_history', [])
            if history:
                import statistics
                mean = statistics.mean(history)
                stdev = statistics.stdev(history) if len(history) > 1 else 0.0
                print("\n========== TTFB summary ==========")
                print(f"  turns measured : {len(history)}")
                print(f"  mean           : {mean:.3f}s")
                print(f"  stdev          : {stdev:.3f}s")
                print(f"  min            : {min(history):.3f}s")
                print(f"  max            : {max(history):.3f}s")
                print(f"  values         : {[f'{x:.3f}' for x in history]}")
                print("==================================")
            else:
                print("\n>> No TTFB samples collected.")
        if button:
            button.stop()
        # Cancel any pending rotary debounce timer
        if rotary_state.get('timer'):
            rotary_state['timer'].cancel()
        # Clean up GPIO handler
        if gpio_handler:
            gpio_handler.cleanup()
        # Clean up interaction handler (handles keyboard listener cleanup too)
        if hasattr(user_interaction_handler, 'cleanup'):
            user_interaction_handler.cleanup()
        # Close log file
        if log_file:
            log_file.close()


def cli():
    """main(), with the exit codes the boot script acts on."""
    try:
        main()
    except voice_agent_utils.ServerNotReady as e:
        print(f">> {e}")
        # A server whose process runs but never got ready will not get
        # better by restarting only the agent: ask for both servers too.
        sys.exit(voice_agent_utils.EXIT_SERVER_STUCK if e.stuck else 1)


if __name__ == "__main__":
    cli()
