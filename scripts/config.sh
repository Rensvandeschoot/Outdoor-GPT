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

# Hardware settings for the voice agent.
PLATFORM=rpi5
AUDIO_IN=1
AUDIO_OUT=0
SPEAKING_RATE=1.

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
