# OutdoorGPT device configuration.
#
# Every value here is specific to one device. The shell scripts source this
# file instead of guessing, so moving to another Pi means editing this file
# and nothing else.
#
# This file is sourced, not executed: no shebang, no exec bit.
#
# Note: the agent directory itself is NOT configured here (this file lives
# inside it). It is set at the top of startup_script.sh.

# Absolute path to the llama.cpp server binary.
# Must be absolute: at boot the DietPi autostart service runs with a minimal
# PATH that does not include custom build directories.
LLAMA_SERVER=/root/llama.cpp/build/bin/llama-server

# Python virtualenv, relative to the agent directory.
VENV=venv

# Chat model and context size, relative to the agent directory.
# The context has to hold the retrieved chunks on top of the conversation.
CHAT_MODEL=models/llms/LFM2.5-1.2B-Instruct-Q4_K_M.gguf
CHAT_CONTEXT=4096

# Embedding model for RAG, relative to the agent directory.
EMBED_MODEL=models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf

# Built RAG index, relative to the agent directory.
RAG_INDEX=rag_index

# Server ports.
CHAT_PORT=8080
EMBED_PORT=8081

# Interface the embedding server listens on. 127.0.0.1 keeps it private to
# the Pi, which is all the agent needs. Set 0.0.0.0 to build the index from
# a PC on the same network (rag_ingest.py --embedding_server_url).
EMBED_HOST=127.0.0.1

# Hardware settings for the voice agent.
PLATFORM=rpi5
AUDIO_IN=1
AUDIO_OUT=0
SPEAKING_RATE=1.

# CPU governor for mode 3, applied by the boot script. "ondemand" clocks down
# when idle, which matters on crank power: a Pi 5 held at maximum clock burns
# the headroom the audio stage needs when the agent starts speaking. Use
# "performance" for the fastest replies on mains power.
GOVERNOR=ondemand

# Clock ceiling in kHz for mode 3, also applied by the boot script. Measured
# on this phone: the greeting pulls 5 A on the core rail at 2.4 GHz and 2.9 A
# at 1.5 GHz, and the 5 V input dips 310 mV versus 125 mV. On crank power that
# dip is what shuts the Pi down. Costs about two seconds at startup. Steps of
# 100000 between 1500000 and 2400000; leave empty for the kernel's maximum.
CPU_MAX_KHZ=1500000

# Piper (text to speech) runs on onnxruntime, which by default takes one
# thread per core, so every sentence lights up all four cores at once.
# TTS_THREADS=2 roughly halves that spike; 0 keeps the default.
# TTS_WARMUP=1 synthesises a few throwaway lines at startup, after both
# servers are up, so the first real sentence is not also the heaviest one.
TTS_THREADS=2
TTS_WARMUP=1

# Moonshine (speech recognition) has the same default, so every utterance
# you speak is a four-core spike as well. ASR_THREADS=2 halves it; 0 keeps
# the default. The voice activity detector already runs on one thread.
ASR_THREADS=2

# Seconds of silence before the phone decides you have finished talking.
# This is the default; a prompt in prompts.json can set its own with
# "silence_seconds" (Campfire Recipes uses 1.5, since an ingredient list is
# spoken with longer pauses than a question). Every reply is delayed by
# this amount, so keep it as low as the pauses allow.
SILENCE_SECONDS=0.7

# Set to 1 to run the agent with --verbose at boot. Every question then logs
# the retrieved chunks ("RAG context injected") to the journal, which is how
# you check that retrieval is really feeding the model. Read it with:
#   journalctl -u dietpi-autostart_custom.service -b -f
# Set back to 0 afterwards; it is noisy.
VERBOSE=0

# Conversation logs (logs/conversation_*.txt) are written for every session
# and would otherwise accumulate on the SD card for years. The boot script
# keeps the newest LOG_KEEP and deletes the rest.
LOG_KEEP=50
