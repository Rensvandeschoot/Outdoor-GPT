# OutdoorGPT

A fully off-grid outdoor assistant living inside an old hand-cranked field telephone. Crank the handle for power, pick one of three assistants with the rotary dial, and talk to an AI through the handset — running fully offline on a Raspberry Pi, with knowledge drawn from real survival manuals.

| Dial position | Assistant | What it does |
| ------------- | --------- | ------------ |
| 1 | **Outdoor Tips** | Questions about hiking, camping, gear, navigation |
| 2 | **Campfire Recipes** | Turns your ingredients into a campfire recipe |
| 3 | **Survive the Night** | Step-by-step help how to survive the night |

If you came here from the website www.outdoorGPT.ai: this is the part that was never fiction. What follows is the actual build — the pipeline end to end, the experiments and tests, and the many small adjustments our failures argued us into.

![Inside the OutdoorGPT box: a Raspberry Pi, a hand-crank generator, an analog voltmeter, a speaker and hand-wired electronics in an olive-green wooden case.](assets/ai%20in%20a%20box.jpeg)

**Small models can also be capable** — here is the real thing, running fully offline:

<video src="assets/small%20models%20can%20also%20be%20capable.mp4" controls muted loop playsinline width="100%"></video>

> If the video does not play inline on GitHub, watch it directly: [small models can also be capable.mp4](assets/small%20models%20can%20also%20be%20capable.mp4)

## Origin & credits

This project builds on the work of others:

- **Hardware & concept**: [handcrank / CrankGPT](https://squeezlabs.github.io/handcrank/) by Squeez Labs — the idea for the crank and rotary dial.
- **Voice agent**: the code in this repo is a fork of [ktomanek/edge_voice_agent](https://github.com/ktomanek/edge_voice_agent) (Apache 2.0) — an offline voice assistant (speech recognition via Moonshine, speech synthesis via Piper, LLM via llama.cpp). This repo contains **only our additions and modified files**; everything else comes straight from that upstream repo (see [Step 4](#step-4--getting-everything-onto-the-pi)).
- **Knowledge base**: The current selection of documents used to train the model was inspired by [bdkoeh/survivalRAG](https://github.com/bdkoeh/survivalRAG).

## What this repo adds

The stock edge_voice_agent answers purely from the language model itself. We add two things:

1. **Three outdoor prompts** behind the rotary dial (`prompts.json` in the repo root — edit this file to change what the assistants do). Besides `system_prompt` and `start_message`, a prompt can carry `"mode": "recipe"` (draws on the e-ink panel, one recipe per session), `"rag": false` (no retrieval for that mode) and `"silence_seconds"` (how long to wait after you stop talking before answering; Campfire Recipes uses 1.5 because an ingredient list is spoken with longer pauses than a question). Each applies from the moment the dial selects that mode.
2. **RAG** (Retrieval-Augmented Generation): the documents in `docs/` are cut into chunks and converted into embeddings stored on the SD card. For every spoken question, the system looks up the best-matching pieces and hands them to the language model as context. This lets a small offline model give answers grounded in the actual manuals.

### Repository layout

Everything in `scripts/`, plus `prompts.json` in the repo root, gets copied over the upstream code on the Pi:

| File | New/modified | Purpose |
| ---- | ------------ | ------- |
| `prompts.json` | modified | The three prompts behind the rotary dial (Campfire Recipes carries `"mode": "recipe"`, which prints the recipe on the e-ink screen) |
| `scripts/rag_ingest.py` | new | Turns documents into the search index (chunks + embeddings) |
| `scripts/rag.py` | new | Looks up the relevant chunks during a conversation |
| `scripts/rag_test.py` | new | Sanity-checks a built index with test questions |
| `scripts/voice_agent.py`, `voice_agent_cli.py`, `voice_agent_utils.py` | modified | RAG integration with the `--rag_index` options |
| `scripts/download_embedding_model.sh` / `.ps1` | new | Fetches the embedding model (Pi / Windows) |
| `scripts/start_embedding_server.sh` / `.ps1` | new | Starts the embedding server (Pi / Windows) |
| `scripts/start_llamacpp_server.sh` | modified | Now accepts a context size as second argument |
| `scripts/startup_script.sh` | new | Boot script for off-grid use: starts both servers + agent (DietPi autostart) |
| `scripts/config.sh` | new | Per-device paths and settings, sourced by the shell scripts |
| `scripts/device_settings.py` | new | Per-device settings for the Python side: panel orientation and pins, LED bus, brightness and colours |
| `scripts/install_on_pi.sh` | new | One-shot installer/updater for the Pi; also the update path |
| `scripts/check_gpio.sh` | new | Verifies the rotary dial and interrupt button wiring |
| `scripts/eink_display.py` | new | Renders a recipe on the optional e-ink screen (recipe mode only) |
| `scripts/waveshare_epd/` | vendored | Waveshare 7.5" V2 e-ink driver (MIT), with the Pi control pins pre-remapped for this build |

The source documents (`docs/`) and the built index (`rag_index/`, ~20 MB) are committed as well, so a single clone brings everything the Pi needs except the model files.


## Step 1 — Collect documents

The file `test_document.md` directly in `docs/` is a minimal test: build an index with just that file present and ask the agent *"How do I put out a campfire safely?"* to verify the whole pipeline before indexing a big collection. The documents in the subfolders `docs/` are public-domain and freely-redistributable survival, first-aid and outdoor-cooking manuals. See [`docs/README.md`](docs/README.md) for the full list of documents, their original sources and licenses. 

To create your own pipeline, simply put the documents (PDF, `.txt` or `.md`) in **subfolders** of `docs/`. Two things to keep in mind:

- **English documents work best** — the embedding model and the speech pipeline are tuned for English.
- **Scanned PDFs** (photos of pages, no selectable text) need OCR first, for example with [ocrmypdf](https://ocrmypdf.readthedocs.io/). The ingest script reports any file it cannot extract text from.

## Step 2 — One-time PC setup

You only need to do this once.

1. **Python packages** (Python 3.10+):

   ```
   pip install numpy httpx pypdf
   ```

2. **llama.cpp** (runs the models). From the [llama.cpp releases page](https://github.com/ggml-org/llama.cpp/releases), download `llama-bXXXXX-bin-win-cpu-x64.zip` and unzip it to `C:\Users\<you>\tools\llama.cpp`.

3. **Download the embedding model** (~46 MB, goes into `models/embeddings/`):

   ```
   powershell -File scripts\download_embedding_model.ps1
   ```

## Step 3 — From documents to index (on the PC)

Repeat this whenever you add or remove documents (the index is rebuilt from scratch each time).

**What happens:** `rag_ingest.py` reads every document, cuts the text into overlapping pieces of ~150 words (chunks), and has the embedding model turn each piece into a vector of 384 numbers that captures its meaning (an embedding). Similar texts get similar vectors — which is how the Pi can later find the best-matching pieces for a question in milliseconds. The result is a `rag_index/` folder with two files: `chunks.json` (the texts) and `embeddings.npy` (the vectors).

1. **Open a first terminal** in the repo root and start the embedding server. Leave this window open:

   ```
   powershell -File scripts\start_embedding_server.ps1
   ```

   Wait until it prints `listening on http://xxx.x.x.x:xxxx`.

2. **Open a second terminal** in the repo root and build the index:

   ```
   python scripts\rag_ingest.py --docs_dir docs
   ```

   You'll see the number of chunks per document, then the embedding progress. Large collections (tens of thousands of chunks) can take tens of minutes — just let it run.

3. Done? The `rag_index/` folder is the end result.

### Sanity-check the index

Before shipping the index to the Pi, check that retrieval actually finds the right manuals. With the embedding server still running (terminal 1):

```
python scripts\rag_test.py
```

This runs a built-in set of test questions (you can also pass your own: `python scripts\rag_test.py "How do I treat a burn?"`). For each question it prints the best-matching chunks with their similarity score and source document. With the current document collection (18 documents, 8,082 chunks) it looks like this:

| Question | Best match | Score |
| -------- | ---------- | ----- |
| How do I purify water so it is safe to drink? | FM 21-76 US Army Survival Manual | 0.63 |
| What can I cook over a campfire with just potatoes and bacon? | Boy Scout Handbook + Camping and Camp Cooking | 0.60 |
| How do I build a shelter to stay warm at night? | USMC Summer Survival Handbook + FM 21-76 | 0.69 |
| How do I treat a snake bite? | FM 4-25.11 First Aid | 0.78 |
| What is the capital of France? *(off-topic control)* | — no match above threshold | ✓ |

Two things to look for: each question should land in a **plausible source document**, and the off-topic control should return **no match** — that means the agent will answer general questions on its own knowledge instead of dragging in irrelevant survival chunks. Scores around 0.6+ indicate a solid match; if everything scores near the 0.35 threshold, the collection probably doesn't cover the topics you're asking about.

You can stop the embedding server now (Ctrl+C in terminal 1).

## Step 4 — Getting everything onto the Pi

### What has to be there first

A working stock setup of the voice agent has to exist first; the installer then puts our layer on top of it. The easiest is the [CrankGPT DIY image](https://github.com/squeezlabs/crankgpt_diy), which brings all of it:

| Prerequisite | Checked by the installer |
| ------------ | ------------------------ |
| DietPi on a Raspberry Pi 5, everything running as `root` | — |
| Audio HAT (ReSpeaker 2-Mic, `wm8960` sound card) and its driver | indirectly, via the device listing it prints |
| GPIO wiring for the rotary dial and the interrupt button | no — verify separately with `./check_gpio.sh` (see [Wiring](#wiring)) |
| llama.cpp built, with `llama-server` at the path in `config.sh` | yes, fatal if missing |
| [edge_voice_agent](https://github.com/ktomanek/edge_voice_agent) installed in `/root/edge_voice_agent` with a `venv` | yes, fatal if missing |
| Its models: a chat model plus `moonshine_v1_tiny`, `piper`, `silero_vad` | yes, warns if missing |
| DietPi autostart set to "Custom script" (index 14) | yes, warns if not |


> **Paths**: DietPi runs everything as `root`, the agent lives in `/root/edge_voice_agent` and its virtualenv is `venv`. If your Pi differs, check your existing `/var/lib/dietpi/dietpi-autostart/custom.sh` — it names the real paths — and put them in `scripts/config.sh` (see [Device configuration](#device-configuration)).

### Install the updated pipeline

Install:

```
cd /root
# clone only what the Pi needs, skipping the website (index.html, assets/, CNAME)
git clone --filter=blob:none --sparse https://github.com/Rensvandeschoot/Outdoor-GPT.git
cd Outdoor-GPT
git sparse-checkout set --no-cone /scripts /prompts.json /rag_index
./scripts/install_on_pi.sh
reboot
```

`install_on_pi.sh` does the whole job: it checks the prerequisites above, copies the scripts, `prompts.json`, `config.sh` and the built `rag_index/` into the agent directory, downloads the embedding model if it is not already there, installs the boot script over `custom.sh` (with a timestamped backup and a shebang check), and disables the network wait that costs 42 seconds per boot. 

The `--sparse` clone pulls only `scripts/`, `prompts.json` and `rag_index/` — the website files (`index.html`, `assets/`, `CNAME`) live in the same repo but never land on the Pi. 

It is safe to re-run, so it doubles as the update path:

```
cd /root/Outdoor-GPT && git pull && ./scripts/install_on_pi.sh && reboot
```

### Wiring

The dial and the button are read by upstream's `gpio_inputs.py` (`RaspberryPi5GPIOHandler`), so these pin numbers are fixed in code rather than configurable. BCM numbering; the pins were chosen to avoid clashing with the ReSpeaker 2-Mic HAT:

| Function | GPIO | Physical pin |
| -------- | ---- | ------------ |
| Interrupt button | 22 | 15 |
| Rotary position 1 → Outdoor Tips | 23 | 16 |
| Rotary position 2 → Campfire Recipes | 24 | 18 |
| Rotary position 3 → Survive the Night | 17 | 11 |

To check a freshly wired set-up:

```
cd /root/edge_voice_agent && ./check_gpio.sh
```

It prints the four pins live for 20 seconds while you turn the dial and press the button, then reports any pin that never went low — which is exactly the symptom of a wire on the wrong header pin. It needs `pinctrl` (from `raspi-utils`, the Pi 5 successor to `raspi-gpio`) or `raspi-gpio` itself; it tells you if neither is installed.

### Audio devices

One more thing always needs a human check on a new device: the **audio device numbers**. `AUDIO_IN` and `AUDIO_OUT` in `config.sh` are indices into sounddevice's device list, not ALSA card numbers, and that numbering can differ between installs. The installer prints the list at the end — make sure the two indices point at the phone's microphone and speaker. On this Pi they are `AUDIO_IN=1` and `AUDIO_OUT=0`, with a single `wm8960soundcard` as card 0.

### Device configuration

`config.sh` holds everything that is specific to one device, so the scripts never have to guess:

| Setting | Value on this Pi | Why it matters |
| ------- | ---------------- | -------------- |
| `LLAMA_SERVER` | `/root/llama.cpp/build/bin/llama-server` | **Must be absolute.** At boot the autostart service gets a minimal `PATH` that excludes custom build directories, so looking the binary up by name fails there while it works fine in an interactive shell. |
| `VENV` | `venv` | Virtualenv inside the agent directory |
| `CHAT_MODEL` / `CHAT_CONTEXT` | LFM2.5-1.2B, 4096 | Context must hold the retrieved chunks plus the conversation |
| `EMBED_MODEL` | all-MiniLM-L6-v2 | Must be the same model the index was built with |
| `RAG_INDEX` | `rag_index` | Where the index lives |
| `CHAT_PORT` / `EMBED_PORT` | 8080 / 8081 | |
| `EMBED_HOST` | `127.0.0.1` | Interface the embedding server listens on. Private to the Pi by default; `0.0.0.0` lets a PC on the network build the index against it |
| `LOG_KEEP` | `50` | Conversation logs to keep. The boot script deletes older ones, so `logs/` cannot fill the SD card over the years |
| `PLATFORM`, `AUDIO_IN`, `AUDIO_OUT`, `SPEAKING_RATE` | rpi5, 1, 0, 1. | Phone hardware. The audio device numbers matter: with the wrong ones the agent talks to the wrong sound card |
| `GOVERNOR` | `ondemand` | CPU governor applied by the boot script in mode 3. `ondemand` clocks down while the phone waits, which matters on crank power: a Pi 5 held at maximum clock spends its headroom on idling instead of on the audio stage. Use `performance` for the fastest replies on mains power |
| `CPU_MAX_KHZ` | `1500000` | Clock ceiling for mode 3. The first sentence the phone speaks is the heaviest moment of the whole start-up; at 1.5 GHz its dip on the 5 V input is less than half of what it is at 2.4 GHz. Costs about two seconds at start-up. Steps of 100000 up to 2400000; empty keeps the kernel's maximum. See [Crank power](#crank-power) |
| `TTS_THREADS` | `2` | Threads Piper's onnxruntime session may use. The default, one per core, makes every sentence a four-core spike; two roughly halves it. `0` keeps the default |
| `TTS_WARMUP` | `1` | Synthesise a few throwaway lines during start-up, after both servers are up, so the first real sentence does not also carry onnxruntime's one-off setup cost |
| `ASR_THREADS` | `2` | Same cap for Moonshine, the speech recogniser, which otherwise makes every utterance you speak a four-core spike. `0` keeps the default |
| `SILENCE_SECONDS` | `0.7` | How long the phone waits after you stop talking before it answers. This is the default; a prompt can set its own `silence_seconds` in `prompts.json` (see below). Every reply is delayed by this amount, so keep it as low as the pauses allow |
| `VERBOSE` | `0` | Set to `1` to run the agent with `--verbose` at boot, logging the retrieved chunks to the journal. See [Testing & tuning](#testing--tuning) |

`config.sh` is version-controlled with this Pi's real values, so the copy step in Step 4 intentionally overwrites the Pi's copy. That means a temporary change made directly on the Pi — flipping `VERBOSE` to `1`, say — is reset the next time you copy the scripts over. 

`config.sh` covers the shell scripts. Its Python counterpart is `scripts/device_settings.py`, which holds what the Python modules need: the panel's orientation and control pins, and the LEDs' bus, brightness and colours. Moving to another device means editing these two files and nothing else; like `config.sh`, the Python file is version-controlled with this phone's values and copied over the agent directory on every install.

## Step 5 — Running it on the Pi

For a first hands-on test, three terminals (or three `tmux` windows), all in `/root/edge_voice_agent` with the venv activated (`source venv/bin/activate`):

```bash
# Terminal 1: the language model (model and context come from config.sh)
./start_llamacpp_server.sh

# Terminal 2: the embedding server
./start_embedding_server.sh

# Terminal 3: the voice agent itself
python voice_agent_cli.py --platform rpi5 --prompt_file prompts.json --rag_index rag_index --verbose
```

`--verbose` is worth using here: it prints `>> RAG context injected` with the retrieved text for every question, which is the only way to see whether retrieval is actually contributing. Without `--rag_index` the agent behaves exactly like stock (no retrieval; terminal 2 isn't needed then).

To check retrieval on the Pi without involving speech at all, run the same sanity check as on the PC — the embedding server is enough, no chat model needed:

```bash
./start_embedding_server.sh > /tmp/emb.log 2>&1 &
sleep 5
source venv/bin/activate
python rag_test.py
```

The scores should match the ones from the PC exactly; that confirms the index and the embedding model survived the trip intact.

Once this works, Step 6 makes it start on its own.

## Step 6 — Off-grid: start everything at boot

Inside the phone there are no terminals: everything must start by itself when the Pi powers up. CrankGPT handles this with **DietPi's autostart** — a script at `/var/lib/dietpi/dietpi-autostart/custom.sh` (selected via `dietpi-autostart` → "Custom script"). The [CrankGPT DIY version](https://github.com/squeezlabs/crankgpt_diy/blob/main/dietpi/startup_script.sh) of that script pins the CPU governor to `performance`, enters the project directory, activates the virtualenv, and then runs one of two modes chosen by a `MODE` variable at the top: **1** = voice agent, **2** = translation. Each mode starts its own llama-server (backgrounded, logging to `/var/log/llama-server.log`) and then runs the matching CLI in the foreground with the phone's audio devices wired in.

`scripts/startup_script.sh` in this repo is that same script with a **third mode** added:

| MODE | What it starts |
| ---- | -------------- |
| 1 | Stock voice agent (unchanged) |
| 2 | Translation agent (unchanged) |
| **3** | **OutdoorGPT: chat LLM (context 4096) + embedding server + agent with `--rag_index`** |

Mode 3 keeps everything the other modes do — `--platform rpi5`, `--audio-device-input 1 --audio-device-output 0`, `--speaking_rate 1.`, `--log-conversation` — and adds the embedding server (backgrounded, logging to `/var/log/embedding-server.log`) plus the RAG flags on the agent. What it changes is the CPU: modes 1 and 2 keep CrankGPT's `performance` governor, while mode 3 applies `GOVERNOR` and `CPU_MAX_KHZ` from `config.sh` so the phone neither idles at full clock nor spikes to it, passes the `TTS_*` settings through to the agent, and runs it with `python -u` so journal timestamps are real. The measurements behind those defaults are under [Crank power](#crank-power). Switching modes is editing one line and rebooting, so you can always fall back to the stock phone.

DietPi must be set to run the custom script in the first place. Check with:

```
cat /boot/dietpi/.dietpi-autostart_index
```

`14` means "custom script" and is what a CrankGPT image already has. Anything else (`0` is plain console login) means the script is never run at boot; set it with `dietpi-autostart`. Note that `AUTO_SETUP_AUTOSTART_TARGET_INDEX` in `/boot/dietpi.txt` is only the install-time value and may disagree — the file above is the live one.

`install_on_pi.sh` (Step 4) already installs this script, so normally there is nothing to do here. To do it by hand:

```
cp /var/lib/dietpi/dietpi-autostart/custom.sh /var/lib/dietpi/dietpi-autostart/custom.sh.bak
cp /root/edge_voice_agent/startup_script.sh /var/lib/dietpi/dietpi-autostart/custom.sh
chmod +x /var/lib/dietpi/dietpi-autostart/custom.sh
head -c 12 /var/lib/dietpi/dietpi-autostart/custom.sh | od -c | head -1
reboot
```

That `od` line is the shebang check: it must print `#   !   /   b   i   n   /   b   a   s   h  \n`. See the warning below for why.

Check that it worked after rebooting:

```
journalctl -u dietpi-autostart_custom.service -b --no-pager | tail -20
```

Startup order takes care of itself: both servers start in the background and the agent waits for each of them (the LLM client and the RAG retriever each retry for ~30 seconds), so a slow boot is fine. Nothing else on the Pi needs changing — no extra packages, no systemd units, and the embedding server is just a second llama.cpp process.

One thing to expect off-grid: the Pi has no sleep mode, so a voltage dip means a full cold boot before the phone answers again.

### Boot time

Measured on this Pi, roughly 32 seconds from power to picking up the handset:

| Phase | Time | Notes |
| ----- | ---- | ----- |
| Kernel + systemd until the autostart script runs | ~5 s | |
| Python imports | 7.8 s | numpy, onnxruntime and friends |
| Speech recognition model | 6.9 s | |
| RAG index load | 1.5 s | 8082 chunks; cheap enough to leave alone |
| Piper TTS | 2.7 s | |
| Waiting for the chat server | 3.0 s | |
| LLM warmup | 4.0 s | makes the first answer fast |

The chat model itself takes ~21 s to load from the SD card, but that happens in parallel with the agent's own startup, so it is not on the critical path — faster storage would not currently help.

**Do not let the boot wait for the network.** DietPi ships with `AUTO_SETUP_BOOT_WAIT_FOR_NETWORK=1`, which makes `dietpi-postboot.service` (and therefore the autostart script) wait for `network-online.target`. On this Pi that cost **42 seconds** on every boot — and off-grid, where no network will ever appear, it is guaranteed to time out in full. The agent needs no network at all: both servers run on localhost. To disable it:

```
sed -i 's/^AUTO_SETUP_BOOT_WAIT_FOR_NETWORK=1/AUTO_SETUP_BOOT_WAIT_FOR_NETWORK=0/' /boot/dietpi.txt
mv /etc/systemd/system/dietpi-postboot.service.d/dietpi.conf /etc/systemd/system/dietpi-postboot.service.d/dietpi.conf.disabled
systemctl daemon-reload
```

Reverse it by moving the file back and reloading. Check the result with `systemd-analyze critical-chain dietpi-autostart_custom.service`: the service should start around `@5s`, with no `ifup@` unit in the chain. The network still comes up afterwards in the background, so SSH keeps working — just not in the first few seconds.

## Recipe screen (optional e-ink)

An optional [Waveshare 7.5" e-Paper HAT](https://www.waveshare.com/7.5inch-e-paper-hat.htm) (800×480, black/white) turns the recipe assistant into a hands-free cookbook: ask for a recipe on **dial position 2 (Campfire Recipes)** and, on top of speaking it, the phone prints the whole recipe on the screen so you don't have to keep cranking for a re-read. E-ink is *bistable* — it holds the last image with the power completely off — so the recipe stays up even after the cell runs flat.

It is wired to stay out of the way:

- **Recipe mode only.** Outdoor Tips and Survive the Night never touch the screen.
- **No retrieval while cooking.** `prompts.json` carries a `"rag": false` flag on Campfire Recipes. Retrieval is what the manuals are for when you need to look something up, but inventing a meal from what you happen to be carrying is not a lookup: asking for a recipe with pasta and tuna pulls in 19th-century cookbook prose and even contents pages, which a 1.2B model cannot ignore. The other two modes keep retrieval on.
- **It starts with the instructions.** At power-up the screen shows a four-step instruction card (cut a tree, put the box on the stump, crank, talk) while the models are still loading, and every press of the button puts it back. The card is [`scripts/eink_instructions.png`](scripts/eink_instructions.png), built by [`scripts/make_eink_instructions.py`](scripts/make_eink_instructions.py) from the photo of the concept render (`scripts/eink_instructions_source.jpg`): it finds the four panels in the photo, warps each one flat, divides out the lighting so the card ground is white and the ink black, and snaps the result to the panel's four grey levels, in the screen's own orientation. The panels in the photo are about the size of the cards on the screen, so the artwork comes through at its own resolution. Run it on the PC (Pillow, numpy, scipy) to regenerate, or drop any picture under that name — it is fitted to the screen and shown in the panel's four grey levels (white, light grey, dark grey, black; `EINK_GREYSCALE` in `device_settings.py`, off means dithered black and white). Recipes stay black on white. Entering recipe mode leaves the screen as it is; a recipe only draws once one has actually been generated.
- **The last recipe stays.** Turning the dial away from recipes does not clear the panel — the recipe you cooked from is still there. The button is the exception: it brings the instruction card back.
- **It checks before it cooks.** Speech recognition mis-hears an accent, and a recipe built on a mis-heard list is a random recipe. So the first thing you say in recipe mode is read straight back from the transcript — *"I heard: pasta, tuna and an onion. Is that right?"* — and nothing reaches the model until you confirm. Say yes (or right, correct, okay) to cook; say no to start over; say a new list and it is read back in turn. This is done in code, not by the model, so it always happens. The phrases and the yes/no words are constants at the top of `scripts/voice_agent_utils.py`.
- **The recipe is not read aloud.** A recipe is for looking at while you cook, not for listening to, so it goes straight to the panel and the phone only says the short line in `RECIPE_ON_SCREEN_MESSAGE`. Once the list is confirmed the agent asks the model for the recipe with a fixed request and treats the reply as the recipe by definition, so it is withheld from speech whether or not the model remembers the `<<RECIPE>>` marker (the marker is still requested and stripped). An unplugged panel is not detected, so keep it connected in recipe mode.
- **One recipe, then it stops.** Once a recipe has been handed over, the agent stops listening and stops generating, so nothing talks over you while you cook. Press the **interrupt button** to start a fresh session: same mode, cleared context, and it asks for your ingredients again. Turning the dial does the same. A one-line clarifying reply does not count as a recipe, so being asked what you have does not end the session.
- **Fail-safe.** If the panel is missing, unplugged, or the driver isn't installed, drawing is skipped silently and the voice agent runs exactly as before. It also runs in a background thread, so the ~6 s e-ink refresh never holds up the conversation.

**How it fits in the code.** `prompts.json` carries `"mode": "recipe"` on the Campfire Recipes prompt; the CLI passes that to the agent on the initial prompt and on every dial switch. In that mode `process_prompt` first runs the transcript through `RecipeIntake` (read back, retry or cook); on cook it sends the model `RECIPE_REQUEST` with the confirmed list, streams the reply through `RecipeRouter` with speech withheld, hands the text to `scripts/eink_display.py` to draw, and ends the session — the interrupt button starts the next one. The renderer auto-shrinks the font until the whole recipe fits one screen, which is why the prompt keeps recipes short. The prompt also insists on metric units and on an ingredient list with amounts before the steps.

**The driver is bundled.** The Waveshare 7.5" V2 driver lives in this repo at [`scripts/waveshare_epd/`](scripts/waveshare_epd) (`epd7in5_V2.py` + `epdconfig.py`, MIT-licensed, from [waveshareteam/e-Paper](https://github.com/waveshareteam/e-Paper)), and `install_on_pi.sh` copies it into the agent directory — so there is nothing to fetch. 

Two small changes from upstream, both in the `RaspberryPi` backend of `epdconfig.py`: the control-pin mapping, read from `scripts/device_settings.py` (see the wiring table below), and a guard on the SPI bus — the driver requires `/dev/spidev0.0`, the 40-pin header bus, and raises a readable error instead of quietly opening the wrong controller (override with `OUTDOORGPT_SPI_BUS`). Everything else is verbatim.

**Software dependencies** (on the Pi, inside the agent's `venv`):

- **Pillow** — `pip install pillow` (renders the recipe text to an image).
- **`gpiozero` + `lgpio` + `spidev`** — the GPIO/SPI backend the driver uses. The bundled `epdconfig` drives the panel through `gpiozero`, which on a **Raspberry Pi 5** needs the `lgpio` backend (`spidev` handles SPI). Install whatever is missing, and make sure **SPI is enabled** — DietPi ships with it off, and there is no `raspi-config` on DietPi. Use `dietpi-config` → Advanced Options → SPI state, or add `dtparam=spi=on` to `/boot/config.txt`, then reboot. Verify with `ls /dev/spidev*`: you need **`/dev/spidev0.0`** (plus `0.1`), which is the header bus on every Pi — on a Pi 5 the header GPIOs hang off the RP1 and its SPI0 appears there. A Pi 5 *also* shows `/dev/spidev10.0`, which is an SPI controller on the SoC rather than the header. That node exists even while header SPI is switched off, and opening it succeeds and then writes into the void, so the panel stays blank with no error at all — indistinguishable from a wiring fault until you check `ls /dev/spidev*`.

`install_on_pi.sh` reports (non-fatally) whether Pillow and the backend libs are importable, so a re-run tells you if anything is still missing.

**Wiring — the pins are already remapped.** The panel talks over SPI, but three of its *control* pins default to GPIOs that OutdoorGPT already uses, so the bundled `epdconfig.py` moves them to free pins. **Wire the ribbon to the "Ships as" column** (BCM numbering):

| e-Paper pin | Waveshare default | Clashes with | Ships as → wire here |
| ----------- | ----------------- | ------------ | -------------------- |
| RST | GPIO 17 | rotary position 3 | **GPIO 6** |
| BUSY | GPIO 24 | rotary position 2 | **GPIO 5** |
| PWR *(HAT revisions that have it)* | GPIO 18 | ReSpeaker 2-Mic I2S | **GPIO 26** |
| DC | GPIO 25 | — (free) | GPIO 25 (unchanged) |
| CS / MOSI / SCLK | GPIO 8 / 10 / 11 | — (SPI, free) | unchanged |

To use different pins, edit the `RaspberryPi` class at the top of [`scripts/waveshare_epd/epdconfig.py`](scripts/waveshare_epd/epdconfig.py) — that is the only place the mapping lives; our renderer just sets the 800×480 geometry.

**Test it — hardware first.** `scripts/test_eink.py` draws one page straight to the panel, with no dial, microphone, model or servers involved — so it works even with the rotary dial disconnected:

```bash
cd /root/edge_voice_agent && source venv/bin/activate
python test_eink.py                 # a sample recipe
python test_eink.py --doc           # the campfire-safety text from docs/test_document
python test_eink.py --file <path>   # any text or markdown file
python test_eink.py --instructions  # the start-up instruction card
```

On success the page stays on the panel with the power off; on failure the script prints the full error and a wiring checklist (3.3V, RST/BUSY/PWR on 6/5/26, SPI enabled, deps).

**Then end-to-end.** Once the panel works, test the whole chain. If the position-2 dial is wired, turn to it and ask for a recipe. If that dial is disconnected (or you just want to force recipe mode), start the agent with keyboard control and press `s` — the `g`/`s`/`f` keys mirror dial positions 1/2/3, no dial needed:

```bash
python voice_agent_cli.py --platform rpi5 --prompt_file prompts.json --rag_index rag_index --enable_keyboard_control
```

The recipe should be spoken *and* appear on the screen a few seconds later.

## Status lights

The three APA102 LEDs on the ReSpeaker HAT show what the phone is doing, which matters most during the thinking pause: on a small model that silence is long enough to look like a crash.

| Colour | Meaning |
| ------ | ------- |
| Green | Your turn — the mic is open and it is listening |
| Blue, pulsing | The model is generating |
| Orange | The phone is talking, so wait |
| Purple | Recipe delivered; press the button for a new session |

Green and orange are the pair that matter in use: they tell you whose turn it is, which is otherwise guesswork on a handset with no screen.

The blue window is driven by `is_generating`, a flag added for this. The handler's existing `is_processing` looks like the obvious signal but is not: it only turns on once a sentence is ready to be spoken, so the thinking pause falls entirely outside it and the light would sit on green while the model was already working. `is_processing` is instead read as speaking, because it stays up between sentences while `is_speaking` briefly drops, and reading it as thinking would flick the light blue mid-answer.

Colours and brightness are set in `scripts/device_settings.py`. `scripts/leds.py` reads the agent's own state from a background thread, so there is nothing to keep in sync at the call sites, and it is fail-safe: without the HAT, without `spidev`, or on the wrong bus it disables itself and the agent runs unchanged. Test the LEDs on their own with `./venv/bin/python test_leds.py` (stop the agent first).

**They share SPI0 with the e-ink panel** — same MOSI, same SCLK, and only the panel uses a chip select, so LED bytes arriving mid-refresh would reach the panel as commands. Both sides take the lock in `scripts/spi_bus.py`, held for a whole refresh, so the animation pauses for a few seconds while a recipe is drawn. Note also that upstream's `display_leds_interrupt` handler is unusable here: it drives external LEDs on GPIO 5, 6 and 13, and 5 and 6 are the panel's BUSY and RST.

## Testing & tuning

- **See what's happening**: start the agent with `--verbose` — it shows which chunks are injected for each question. This is the best way to judge retrieval quality. When the phone starts on its own there is no terminal to pass flags to, so set `VERBOSE=1` in `config.sh` instead and reboot; the output then goes to the journal:

  ```bash
  journalctl -u dietpi-autostart_custom.service -b -f
  ```

- **Test without the dial**: with `--enable_keyboard_control`, the keys `g`/`s`/`f` switch to prompt 1/2/3, mirroring the rotary dial.
  
- **Knobs**:

  | Option | Default | Meaning |
  | ------ | ------- | ------- |
  | `--rag_top_k` | 2 | Max chunks injected per question (lower = less pressure on a small model's context) |
  | `--rag_min_score` | 0.35 | Minimum similarity; below this, chunks are ignored and the model answers on its own |
  | `--chunk_words` (ingest) | 150 | Chunk size in words; keep it small while the language model's context is small |

- **Model ignoring the documents?** A very small model (like LFM2-350M) is usually the limiting factor. A 1B+ parameter model (Q4 quantization) gives noticeably better answers on a Pi 5, at the cost of some latency. If you switch models, grow `CHAT_CONTEXT` in `config.sh` along with it.

### Crank power

On mains the phone is fine; on the hand crank it browned out the moment the agent first spoke. The Pi 5 can tell you why: its power chip reports the current on every rail. Run this over SSH, provoke a cold start with `systemctl restart dietpi-autostart_custom.service` in a second window, and read the last lines before the Pi dies. They reach your laptop before the power does.

```bash
while true; do echo "$(date +%T) $(vcgencmd pmic_read_adc | grep -E 'EXT5V_V|VDD_CORE_A|3V3_SYS_A|3V7_WL_SW_A' | sed 's/ *current([0-9]*)//; s/ *volt([0-9]*)//' | tr '\n' ' ') $(vcgencmd get_throttled)"; sleep 0.25; done
```

`VDD_CORE_A` is the CPU, `3V3_SYS_A` the 3.3 V rail (HAT, e-ink, SD card), `3V7_WL_SW_A` the wireless module, `EXT5V_V` the input voltage. The speaker amplifier sits on 5 V and does not show up as a current; watch `EXT5V_V` for it. Single samples can be nonsense (an 8 A reading on a rail that cannot deliver it); trust sustained levels and the voltage.

One trap when timing a cold boot on mains: the Pi 5 has no battery on its clock, so DietPi starts it from the time saved at shutdown, and about a minute after boot, once WiFi is up, `systemd-timesyncd` steps it forward by however long the reboot took (around 40 s here). Anything measured across that instant with the wall clock gets the step added: journal timestamps, the agent's own "in X secs" lines, llama-server's timestamp column. Read the journal with `-o short-monotonic` (seconds since boot, never steps) and trust llama-server's per-request `prompt eval time` / `eval time`, which come from a monotonic clock. Off-grid there is no time server and no step.

What the measurements on this phone showed, and what the defaults in `config.sh` do about it:

| Finding | Setting |
|---|---|
| The heaviest moment of the whole start-up is the first sentence, not model loading: 5 A on the core rail and a 310 mV dip on the input at 2.4 GHz | `CPU_MAX_KHZ=1500000` brings that to 2.9 A and 125 mV, for two seconds of extra start-up |
| llama-server never exceeds 1.3 A (`--threads 2`); the spikes come from onnxruntime, which Piper and the speech recogniser run on with one thread per core | `TTS_THREADS=2` and `ASR_THREADS=2` halve them at the source |
| The first synthesis carries onnxruntime's one-off setup cost on top | `TTS_WARMUP=1` pays it during start-up, with both servers loaded and the amplifier still off |
| The wireless module draws a steady ~95 mA on 3.7 V, about 0.35 W, network or not | `rfkill block wifi` after boot, if you can do without SSH |
| Holding every core at maximum clock while waiting costs headroom for nothing | `GOVERNOR=ondemand` |

To measure any one of these, change the setting in `config.sh`, restart the service, and compare the trace.

**The power board.** CrankGPT's board is a 20 W switchable hand-crank generator set to 6.3 V, a Schottky diode, three 50 F supercapacitors in series (16.7 F, 8.1 V maximum) with balance resistors, and a 5 A linear regulator down to 5.3 V. The usable reservoir is the energy between the charged voltage and the point where the regulator can no longer hold the Pi above its brown-out level, roughly 6 V down to 5 V: about 90 J, which is 30 s of this phone's idle draw and 15 to 20 s of recipe generation. That is why cranking speed matters second by second, and why the software work above moves the limit but cannot remove it. Stored energy scales with the square of the voltage, so the cheap upgrade is voltage, not more capacitance at the same voltage. Never exceed 2.7 V per capacitor: a 9 V generator setting needs a fourth capacitor in series (10.8 V maximum, about three to four times the reservoir), 12 V needs a fifth (13.5 V maximum, about six times). At those voltages the linear regulator burns half the energy as heat, so replace it with a 5 V / 5 A synchronous buck converter rated for the input range. The board's voltmeter is the diagnostic: read it at the moment the phone dies. Around 5 V means the reservoir ran out; well above it means something else cut the power, such as the generator's own over-current protection.

### Troubleshooting the boot

Symptoms we have actually hit, and what they mean:

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| Nothing starts at boot, but running the script's lines by hand works | The shebang is not on line 1 of `custom.sh` (`journalctl` shows `Exec format error`) | Copy `startup_script.sh` over it instead of hand-editing |
| Servers refuse to start only at boot, fine from a shell | `LLAMA_SERVER` not set to an absolute path; the boot service has a minimal `PATH` | Set the absolute path in `config.sh` |
| Phone answers, but never uses the documents | `MODE` is not 3, so the agent runs without `--rag_index` | Set `MODE=3` and reboot |
| Agent exits at startup complaining it cannot reach a server | A model file named in `config.sh` does not exist, so that server died immediately | Check the two `*.log` files in `/var/log/` |
| The autostart script never runs at all | `/boot/dietpi/.dietpi-autostart_index` is not `14` | Set it with `dietpi-autostart` |
| `chunks.json` has a different checksum on the Pi than on the PC | Harmless: git normalises line endings, so the Windows copy has CRLF and the Pi has LF. The difference in bytes equals the number of lines | Compare `embeddings.npy` instead — that one is binary and must match exactly |

Useful commands: `journalctl -u dietpi-autostart_custom.service -b --no-pager` for the boot itself, `journalctl -u dietpi-autostart_custom.service -b -f` to follow it live (this is where `VERBOSE=1` output lands), and `tail -f /var/log/llama-server.log /var/log/embedding-server.log` for the two servers.

## Contact

**[Rens](@Rensvandeschoot) & [Allard](@allardw)** — the wiring, the code, and the questionable decision to make a telephone think.
[rens@fwdfaster.ai](mailto:rens@fwdfaster.ai) · [github.com/Rensvandeschoot](https://github.com/Rensvandeschoot) · the story lives in [`index.html`](index.html)

We built this to start a conversation and to use in our lectures, so: argue with us about where capable AI is really headed, borrow it for your own classroom, or build one yourself. If a step above only worked because of something undocumented on our Pi, tell us — that is exactly the sort of thing this README is trying to save you from. If you are better in hardware or PI installations, send us your GitHub repo and we're happy to inject your improvement!

## License

The code in this repository is licensed under the Apache License 2.0 — see [LICENSE](LICENSE). A few parts carry their own terms:

- **`scripts/waveshare_epd/`** — MIT, vendored from [waveshareteam/e-Paper](https://github.com/waveshareteam/e-Paper) with two documented changes.
- **The voice agent it forks** — Apache 2.0, [ktomanek/edge_voice_agent](https://github.com/ktomanek/edge_voice_agent).
- **The documents in `docs/`** — public domain or freely redistributable, one licence per source; the full list is in [`docs/README.md`](docs/README.md).
- **The models** — not redistributed here; the scripts download them from their original sources, and each has its own licence. Worth knowing: LFM2.5 uses the [LFM Open License](https://www.liquid.ai/lfm-license) (free commercial use only below $10M annual revenue), all-MiniLM-L6-v2 is Apache 2.0, Moonshine and Silero VAD are MIT, and each Piper voice carries the licence of its training data.
