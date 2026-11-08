# Start-up simulation

Sometimes the phone has to be restarted because something went wrong: it runs another
mode than the dial shows, it talks over itself, or it goes quiet for good. This folder
reproduces those situations on a PC, without the phone, by running the agent's real code
against simulated hardware, and checks every run for the known ways it can go wrong.

```
cd tests/startup_sim
python run_matrix.py                 # full matrix, ~3 minutes, writes report.md
python run_matrix.py --only C3,D --seeds 1
python inspect_run.py results.jsonl C3:1     # timeline of one run
bash test_boot_script.sh             # the boot script's restart loop (see below)
```

Python 3.10+ and nothing else: no numpy, no audio, no GPIO.

## What is real and what is simulated

| Real (run unchanged from `scripts/`) | Simulated (`fakes/`) |
| --- | --- |
| `voice_agent_cli.py`, `voice_agent.py`, `voice_agent_utils.py` | rotary dial and yellow button (`gpiozero`), with lgpio's single callback thread |
| `leds.py`, `device_settings.py`, `spi_bus.py` | microphone and speaker (`sounddevice`); an open mic hears the speaker |
| upstream `gpio_inputs.py` (vendored in `upstream/`, Apache-2.0) | speech recognition and VAD (`captioning_lib`), Piper (`tts_lib`) |
| the agent's command line, built from `scripts/config.sh` as `startup_script.sh` does | both llama-servers (`llm_client`, `rag`): load time, prefill and token speed, `n_ctx` |
| | the e-ink panel (holds the SPI lock for a whole refresh, like the real one) |

The clock runs 20x faster (`SIM_SCALE=0.05`): `time.time` and `time.sleep` are replaced,
so every wait in the real code keeps its meaning. Load times come from the README's boot
table: imports 7.8 s, speech recognition 6.9 s, RAG 1.5 s, Piper 2.7 s, chat model 21 s,
LLM warm-up 4 s, all with seeded jitter (`seed` in a scenario; the chat model +-15 %).
The model's answers carry their mode as a tag word (`TIPS`, `SURVIVE`, `RECIPE`) and are
written as a short list, one sentence per line, as a small model tends to.

A simulated user waits for the green LED, asks a question (in recipe mode: the
ingredients, then "yes"), and waits for the answer. Scenario events fire at a time or at
a phase: `ready`, `start_msg`, `say`, `gen_start` (blue), `answer` (orange), `readback`,
`cooking`, `delivered` (purple), `reset`.

## Scenarios

- **A** start position: 1, 2, 3, between two positions, a loose wire.
- **B** the dial turned during start-up, at every phase from imports to the start message.
- **C** the dial turned while listening, while you talk, while it thinks, while it answers,
  while a recipe is written; quick double turns; contact bounce.
- **D** the yellow button: a press in every phase (including after a recipe and while one is
  written), 2 s holds, and 20 s holds while listening and during start-up.
- **E** slow, missing, hanging and dying servers, a warm restart, a 40-question
  conversation, a one-off server error, and a question that contains "please quite".
- **G** the start-up LEDs after one and after three failed starts in a row.
- **F** combinations; **Z** 20 random combinations of dial turns and presses.

Each fixed scenario runs with 3 seeds; E7 and the random ones once.

## What is checked

The finding codes and their meaning are listed at the bottom of every report. In short:
does the mode match the dial, is an old answer spoken after a switch, is the history sent to
the model well-formed, does the e-ink panel only ever show a real recipe, does the button do
what it says, does the agent stay alive.

## The boot script

`harness.py` simulates one agent process. What happens when that process ends is up to
`startup_script.sh`; `test_boot_script.sh` runs the real script under bash with a fake
`python` and a fake `llama-server` and checks: restarts with a growing wait, a dead server
started again, a clean stop on SIGTERM, five boot logs kept, exit codes 4 and 3 (servers
replaced; 3 at once), the failed-start count and the red blink between restarts, and,
where `flock` exists, that a second copy is refused.

## Results

`results/` holds a report per stage: the code before the fixes (`baseline_0220b54.md`),
after the first round (`after_4a602c6.md`) and after the button and LED work
(`after_804d92b.md`). `results.jsonl` (every run in full) is not committed.
