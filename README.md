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
- **Knowledge base**: the documents in `docs/` are a selection from [bdkoeh/survivalRAG](https://github.com/bdkoeh/survivalRAG) — a curated collection of public-domain survival and medical content (US Army field manuals, FEMA guides, CDC material; some CC BY-SA 4.0 Wikipedia articles). We use their source documents only, not their code.

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
| `scripts/voice_agent.py`, `voice_agent_cli.py`, `voice_agent_utils.py` | modified | RAG integration + the `--rag_index` options |
| `scripts/download_embedding_model.sh` / `.ps1` | new | Fetches the embedding model (Pi / Windows) |
| `scripts/start_embedding_server.sh` / `.ps1` | new | Starts the embedding server (Pi / Windows) |
| `scripts/start_llamacpp_server.sh` | modified | Now accepts a context size as second argument |


## Step 1 — Collect documents

Put the documents (PDF, `.txt` or `.md`) in **subfolders** of `docs/`, for example `docs/survival/` and `docs/medical/`. Subfolders are ignored by git, so large collections never end up in the repo. The one file directly in `docs/` — `test_document.md` — is tracked on purpose: build an index with just that file present and ask the agent *"How do I put out a campfire safely?"* to verify the whole pipeline before committing to a big collection.

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

3. Done? You can stop the embedding server in terminal 1 (Ctrl+C). The `rag_index/` folder is the end result.

## Step 4 — Getting everything onto the Pi

The Pi runs the full voice agent. Since this repo only contains our changes, you first set up the upstream code and then copy our files on top.

1. **On the Pi** (once): install [edge_voice_agent](https://github.com/ktomanek/edge_voice_agent) following their Readme (llama.cpp, Python environment, `python setup.py`, model downloads). Make sure the stock agent works before continuing.

2. **On the Pi** (once): clone this repo next to it and copy our files over the upstream code:

   ```
   git clone https://github.com/Rensvandeschoot/Outdoor-GPT.git
   cp Outdoor-GPT/scripts/* Outdoor-GPT/prompts.json edge_voice_agent/
   ```

   (After a `git pull` in Outdoor-GPT, repeat the `cp` command.)

3. **On the Pi** (once): download the embedding model:

   ```
   cd edge_voice_agent
   ./download_embedding_model.sh
   ```

4. **From the PC**: copy the built index to the Pi (replace `<pi-ip>` with the Pi's IP address — run `hostname -I` on the Pi to find it):

   ```
   scp -r rag_index pi@<pi-ip>:~/edge_voice_agent/
   ```

## Step 5 — Running it on the Pi

Three terminals (or three `tmux` windows), all in `~/edge_voice_agent`:

```bash
# Terminal 1: the language model, with extra context for the RAG chunks
./start_llamacpp_server.sh models/llms/LFM2-350M-Q4_K_M.gguf 2048

# Terminal 2: the embedding server
./start_embedding_server.sh

# Terminal 3: the voice agent itself
python voice_agent_cli.py --platform rpi5 --prompt_file prompts.json --rag_index rag_index
```

Without `--rag_index` the agent behaves exactly like stock (no retrieval; terminal 2 isn't needed then).

## Testing & tuning

- **See what's happening**: start the agent with `--verbose` — it shows which chunks are injected for each question. This is the best way to judge retrieval quality.
- **Test without the dial**: with `--enable_keyboard_control`, the keys `g`/`s`/`f` switch to prompt 1/2/3, mirroring the rotary dial.
- **Knobs**:

  | Option | Default | Meaning |
  | ------ | ------- | ------- |
  | `--rag_top_k` | 2 | Max chunks injected per question (lower = less pressure on a small model's context) |
  | `--rag_min_score` | 0.35 | Minimum similarity; below this, chunks are ignored and the model answers on its own |
  | `--chunk_words` (ingest) | 150 | Chunk size in words; keep it small while the language model's context is small |

- **Model ignoring the documents?** The small default model (LFM2-350M) is usually the limiting factor. A 1B+ parameter model (Q4 quantization) gives noticeably better answers on a Pi 5, at the cost of some latency. If you upgrade, remember to grow the context size in the start command (the `2048`) along with it.
