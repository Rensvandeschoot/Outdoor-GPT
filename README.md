# OutdoorGPT

An outdoor assistant living inside an old hand-cranked field telephone. Crank the handle for power, pick one of three assistants with the rotary dial, and talk to an AI through the handset — running fully offline on a Raspberry Pi, with knowledge drawn from real survival manuals.

| Dial position | Assistant | What it does |
| ------------- | --------- | ------------ |
| 1 | **Outdoor Tips** | Questions about hiking, camping, gear, navigation |
| 2 | **Campfire Recipes** | Turns your ingredients into a campfire recipe |
| 3 | **Survive the Night** | Step-by-step help for an unexpected night outdoors |

## Origin & credits

This project builds on the work of others:

- **Hardware & concept**: [handcrank / CrankGPT](https://squeezlabs.github.io/handcrank/) by Squeez Labs — the telephone with the crank, rotary dial and Raspberry Pi.
- **Voice agent**: the code in this repo is a fork of [ktomanek/edge_voice_agent](https://github.com/ktomanek/edge_voice_agent) (Apache 2.0) — an offline voice assistant (speech recognition via Moonshine, speech synthesis via Piper, LLM via llama.cpp). This repo contains **only our additions and modified files**; everything else comes straight from that upstream repo (see [Step 4](#step-4--getting-everything-onto-the-pi)).
- **Knowledge base**: the documents in `docs/` are public-domain and freely-redistributable survival, first-aid and outdoor-cooking manuals. See [`docs/README.md`](docs/README.md) for the full list of documents, their original sources and licenses. (The selection was inspired by [bdkoeh/survivalRAG](https://github.com/bdkoeh/survivalRAG).)

## What this repo adds

The stock edge_voice_agent answers purely from the language model itself. We add two things:

1. **Three outdoor prompts** behind the rotary dial (`prompts.json` in the repo root — edit this file to change what the assistants do).
2. **RAG** (Retrieval-Augmented Generation): the documents in `docs/` are cut into small pieces of text ("chunks") and converted into vectors ("embeddings") stored on the SD card. For every spoken question, the Pi looks up the best-matching pieces and hands them to the language model as context. This lets a small offline model give answers grounded in the actual manuals.

### Repository layout

Everything in `scripts/`, plus `prompts.json` in the repo root, gets copied over the upstream code on the Pi:

| File | New/modified | Purpose |
| ---- | ------------ | ------- |
| `prompts.json` | modified | The three prompts behind the rotary dial |
| `scripts/rag_ingest.py` | new | Turns documents into the search index (chunks + embeddings) |
| `scripts/rag.py` | new | Looks up the relevant chunks during a conversation |
| `scripts/rag_test.py` | new | Sanity-checks a built index with test questions |
| `scripts/voice_agent.py`, `voice_agent_cli.py`, `voice_agent_utils.py` | modified | RAG integration + the `--rag_index` options |
| `scripts/download_embedding_model.sh` / `.ps1` | new | Fetches the embedding model (Pi / Windows) |
| `scripts/start_embedding_server.sh` / `.ps1` | new | Starts the embedding server (Pi / Windows) |
| `scripts/start_llamacpp_server.sh` | modified | Now accepts a context size as second argument |
| `scripts/startup_script.sh` | new | Boot script for off-grid use: starts both servers + agent (DietPi autostart) |
| `scripts/config.sh` | new | Per-device paths and settings, sourced by the shell scripts |

The source documents (`docs/`) and the built index (`rag_index/`, ~20 MB) are committed as well, so a single clone brings everything the Pi needs except the model files.


## Step 1 — Collect documents

Put the documents (PDF, `.txt` or `.md`) in **subfolders** of `docs/` — one subfolder per source. The documents are committed to this (private) repo, so the Pi gets them with a plain `git clone`; the current collection, with sources and licenses, is listed in [`docs/README.md`](docs/README.md) — only add material that is public domain or freely redistributable. The file `test_document.md` directly in `docs/` is a minimal test: build an index with just that file present and ask the agent *"How do I put out a campfire safely?"* to verify the whole pipeline before indexing a big collection.

Two things to keep in mind:

- **English documents work best** — the embedding model and the speech pipeline are tuned for English.
- **Scanned PDFs** (photos of pages, no selectable text) need OCR first, for example with [ocrmypdf](https://ocrmypdf.readthedocs.io/). The ingest script reports any file it cannot extract text from.

## Step 2 — One-time PC setup

You only need to do this once.

1. **Python packages** (Python 3.10+):

   ```
   pip install numpy httpx pypdf
   ```

2. **llama.cpp** (runs the models). From the [llama.cpp releases page](https://github.com/ggml-org/llama.cpp/releases), download `llama-bXXXXX-bin-win-cpu-x64.zip` and unzip it to `C:\Users\<you>\tools\llama.cpp`.

   > ⚠️ **Antivirus**: Norton (and sometimes Defender) silently quarantines these freshly downloaded executables. If something suddenly stops working and the `.exe` files have vanished, restore them from your antivirus quarantine and add the folder to its exclusions.

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

The Pi runs the full voice agent. Since this repo only contains our changes, you first set up the upstream code and then copy our files on top.

> **Paths**: DietPi runs everything as `root`, the agent lives in `/root/edge_voice_agent` and its virtualenv is `venv`. If your Pi differs, check your existing `/var/lib/dietpi/dietpi-autostart/custom.sh` — it names the real paths — and put them in `scripts/config.sh` (see [Device configuration](#device-configuration)).

1. **On the Pi** (once): if you built the Pi yourself rather than from the [CrankGPT DIY image](https://github.com/squeezlabs/crankgpt_diy), install [edge_voice_agent](https://github.com/ktomanek/edge_voice_agent) following their Readme (llama.cpp, Python environment, `python setup.py`, model downloads). Make sure the stock agent works before continuing.

2. **On the Pi** (once): clone this repo next to it and copy our files over the upstream code. The repo is private, so authenticate first — easiest with the [GitHub CLI](https://cli.github.com/) (`sudo apt install gh`, then `gh auth login`), or use a personal access token as the password on HTTPS:

   ```
   cd /root
   git clone https://github.com/Rensvandeschoot/Outdoor-GPT.git
   cp Outdoor-GPT/scripts/* Outdoor-GPT/prompts.json edge_voice_agent/
   cp -r Outdoor-GPT/rag_index edge_voice_agent/
   ```

   The built index travels inside the repo, so there is nothing to transfer manually.

3. **On the Pi** (once): check `config.sh` and download the embedding model:

   ```
   cd /root/edge_voice_agent
   nano config.sh
   ./download_embedding_model.sh
   ```

4. **Updating later**: after changing prompts, documents or scripts on the PC, rebuild the index if the documents changed (Step 3), commit and push. Then on the Pi:

   ```
   cd /root/Outdoor-GPT && git pull && cd ..
   cp Outdoor-GPT/scripts/* Outdoor-GPT/prompts.json edge_voice_agent/
   cp -r Outdoor-GPT/rag_index edge_voice_agent/
   ```

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
| `PLATFORM`, `AUDIO_IN`, `AUDIO_OUT`, `SPEAKING_RATE` | rpi5, 1, 0, 1. | Phone hardware |

Moving to another device means editing this one file. The server scripts still accept arguments, which override the config.

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

Once this works, Step 6 makes it start on its own.

## Step 6 — Off-grid: start everything at boot

Inside the phone there are no terminals: everything must start by itself when the Pi powers up. CrankGPT handles this with **DietPi's autostart** — a script at `/var/lib/dietpi/dietpi-autostart/custom.sh` (selected via `dietpi-autostart` → "Custom script"). The [CrankGPT DIY version](https://github.com/squeezlabs/crankgpt_diy/blob/main/dietpi/startup_script.sh) of that script pins the CPU governor to `performance`, enters the project directory, activates the virtualenv, and then runs one of two modes chosen by a `MODE` variable at the top: **1** = voice agent, **2** = translation. Each mode starts its own llama-server (backgrounded, logging to `/var/log/llama-server.log`) and then runs the matching CLI in the foreground with the phone's audio devices wired in.

`scripts/startup_script.sh` in this repo is that same script with a **third mode** added:

| MODE | What it starts |
| ---- | -------------- |
| 1 | Stock voice agent (unchanged) |
| 2 | Translation agent (unchanged) |
| **3** | **OutdoorGPT: chat LLM (context 4096) + embedding server + agent with `--rag_index`** |

Mode 3 keeps everything the other modes do — the `performance` governor, `--platform rpi5`, `--audio-device-input 1 --audio-device-output 0`, `--speaking_rate 1.`, `--log-conversation` — and adds the embedding server (backgrounded, logging to `/var/log/embedding-server.log`) plus the RAG flags on the agent. Switching modes is editing one line and rebooting, so you can always fall back to the stock phone.

To install it on the Pi:

```
cp /var/lib/dietpi/dietpi-autostart/custom.sh /var/lib/dietpi/dietpi-autostart/custom.sh.bak
cp /root/edge_voice_agent/startup_script.sh /var/lib/dietpi/dietpi-autostart/custom.sh
chmod +x /var/lib/dietpi/dietpi-autostart/custom.sh
reboot
```

**Copy the file rather than hand-editing your existing one.** The shebang `#!/bin/bash` has to be the very first line: if anything precedes it — even a single blank line — systemd cannot execute the file and fails at boot with `Exec format error`, so *nothing* starts, in any mode. Hand-merging is exactly how such a blank line sneaks in. Everything device-specific already lives in `config.sh`, so the only line in this script you may need to touch is `AGENT_DIR` at the top.

Check that it worked after rebooting:

```
journalctl -u dietpi-autostart_custom.service -b --no-pager | tail -20
```

Startup order takes care of itself: both servers start in the background and the agent waits for each of them (the LLM client and the RAG retriever each retry for ~30 seconds), so a slow boot is fine. Nothing else on the Pi needs changing — no extra packages, no systemd units, and the embedding server is just a second llama.cpp process.

Two things to expect off-grid: the Pi has no sleep mode, so a voltage dip means a full cold boot (roughly 30–45 seconds including model loading) before the phone answers again, and the RAG index adds a few seconds to that startup while `embeddings.npy` is read from the SD card.

## Testing & tuning

- **See what's happening**: start the agent with `--verbose` — it shows which chunks are injected for each question. This is the best way to judge retrieval quality.
- **Test without the dial**: with `--enable_keyboard_control`, the keys `g`/`s`/`f` switch to prompt 1/2/3, mirroring the rotary dial.
- **Knobs**:

  | Option | Default | Meaning |
  | ------ | ------- | ------- |
  | `--rag_top_k` | 2 | Max chunks injected per question (lower = less pressure on a small model's context) |
  | `--rag_min_score` | 0.35 | Minimum similarity; below this, chunks are ignored and the model answers on its own |
  | `--chunk_words` (ingest) | 150 | Chunk size in words; keep it small while the language model's context is small |

- **Model ignoring the documents?** A very small model (like LFM2-350M) is usually the limiting factor. A 1B+ parameter model (Q4 quantization) gives noticeably better answers on a Pi 5, at the cost of some latency. If you switch models, grow `CHAT_CONTEXT` in `config.sh` along with it.

### Troubleshooting the boot

Symptoms we have actually hit, and what they mean:

| Symptom | Cause | Fix |
| ------- | ----- | --- |
| Nothing starts at boot, but running the script's lines by hand works | The shebang is not on line 1 of `custom.sh` (`journalctl` shows `Exec format error`) | Copy `startup_script.sh` over it instead of hand-editing |
| Servers refuse to start only at boot, fine from a shell | `LLAMA_SERVER` not set to an absolute path; the boot service has a minimal `PATH` | Set the absolute path in `config.sh` |
| Phone answers, but never uses the documents | `MODE` is not 3, so the agent runs without `--rag_index` | Set `MODE=3` and reboot |
| Agent exits at startup complaining it cannot reach a server | A model file named in `config.sh` does not exist, so that server died immediately | Check the two `*.log` files in `/var/log/` |

Useful commands: `journalctl -u dietpi-autostart_custom.service -b --no-pager` for the boot itself, and `tail -f /var/log/llama-server.log /var/log/embedding-server.log` for the two servers.
