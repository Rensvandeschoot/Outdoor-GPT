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
#   Interrupt button  - stops the agent mid-speech; after a recipe has been
#                       delivered, starts a new recipe session instead
#   Keyboard (with --enable_keyboard_control):
#     ENTER           - same as the interrupt button
#     SPACE           - mute / unmute the microphone
#     g / s / f       - prompt 1 / 2 / 3, mirroring the dial
#
# Exit: say "please quit" (DEFAULT_EXIT_COMMAND in voice_agent_utils.py), or Ctrl-C.

import threading
import time
start_time = time.time()
print("Loading Voice Agent...")

from voice_agent import VoiceAgent
import voice_agent_utils
from voice_agent_interaction_handlers import get_handler, LoggingHandlerWrapper, create_conversation_log_file
from opi.gpio_utils import POSITION_KEYS

# Rotary dial: 3 positions mapped to the first 3 prompts in prompts.json.
ROTARY_POSITION_TO_PROMPT_INDEX = {
    'pos1': 0,
    'pos2': 1,
    'pos3': 2,
}
ROTARY_SETTLE_DELAY = 0.5

print(f">> -- All imports done in {time.time() - start_time:.2f} seconds -- <<")


def main():
    """Main function to run the LLM to Audio output streamer."""
    
    parser = voice_agent_utils.get_cli_argument_parser()
    args = parser.parse_args()

    voice_agent_utils.apply_audio_device_settings(args)

    # Setup prompt selector (either from file or CLI args)
    prompt_selector = voice_agent_utils.PromptSelector(
        prompt_file=args.prompt_file,
        default_system_prompt=args.system_prompt,
        default_start_message=args.start_message
    )

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

    # Pick initial prompt: from rotary dial if available, else random
    initial_prompt = None
    if gpio_handler:
        rotary_pos = gpio_handler.get_current_position()
        idx = ROTARY_POSITION_TO_PROMPT_INDEX.get(rotary_pos)
        if idx is not None and idx < len(prompt_selector.prompts):
            initial_prompt = prompt_selector.prompts[idx]
            print(f">> Initial prompt from rotary dial position '{rotary_pos}': {initial_prompt.get('name', 'unnamed')}")
        else:
            print(f">> No valid rotary position detected (got {rotary_pos!r}), using random prompt")
    if initial_prompt is None:
        initial_prompt = prompt_selector.get_random_prompt()

    # A prompt may set its own silence window (silence_seconds in prompts.json);
    # the CLI value is the default for the ones that do not.
    def silence_for(prompt):
        return float(prompt.get('silence_seconds', args.end_of_utterance_duration))

    t1 = time.time()
    print(">> Initializing Voice Agent <<")
    va = VoiceAgent(verbose=args.verbose)

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
        printer=user_interaction_handler
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
    )
    print(f">> Initialized LLmToAudioOutput in {time.time() - start_time:.2f} seconds -- <<")

    # Status LEDs on the audio HAT. Fail-safe: no HAT, no spidev, no LEDs and
    # the agent is unaffected. Reads the handler's own state, so there is
    # nothing to keep in sync at the call sites.
    from leds import StatusLeds
    status_leds = StatusLeds(va.output_handler, verbose=args.verbose)
    if status_leds.start():
        print(">> Status LEDs active (green=your turn, blue=thinking, orange=speaking, purple=done)")

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
        """Interrupt the agent, or start a fresh recipe session."""
        # Recipe mode delivers one recipe and then stops listening, so there is
        # nothing to interrupt. Restart the same mode instead: cleared context
        # and the opening question again, ready for new ingredients.
        if getattr(va.output_handler, 'recipe_delivered', False):
            switch_to_prompt(current_prompt['p'])
            return
        if va.output_handler.is_speaking or va.output_handler.is_processing:
            on_interrupt_agent()

    def switch_to_prompt(new_prompt):
        current_prompt['p'] = new_prompt
        if log_file:
            prompt_name = new_prompt.get('name', 'unnamed')
            log_file.write(f"\n[RESET] [PROMPT] {prompt_name}\n")
            log_file.flush()
        va.full_reset_with_prompt(
            system_prompt=new_prompt['system_prompt'],
            start_message=new_prompt['start_message'],
            recipe_mode=new_prompt.get('mode') == 'recipe',
            rag_enabled=new_prompt.get('rag', True),
            silence_seconds=silence_for(new_prompt)
        )

    # Setup GPIO interrupt button via gpio_handler
    if gpio_handler:
        gpio_handler.set_interrupt_callback(on_button_press)
        print(">> GPIO interrupt button enabled (interrupts speech; restarts recipe mode once a recipe is done)")

    # -- rotary switch -> prompt selection --
    # Debounce so dial sweeps don't queue multiple prompt switches, and
    # suppress repeat events for the position we already applied (mechanical
    # bounce on the rotary can keep firing after the dial has settled).
    initial_pos = gpio_handler.get_current_position() if gpio_handler else None
    rotary_state = {'timer': None, 'last_applied_pos': initial_pos}

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

    if gpio_handler:
        gpio_handler.set_position_change_callback(switch_to_position)
        print(f">> Rotary switch listener active (3 positions -> first 3 prompts)")

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

if __name__ == "__main__":
    main()
