#!/bin/bash
#
# Starts llama.cpp server with the provided model file.
#
# Download gguf model first (eg with download_llm.sh).
# Then start server:
# ./start_llama_server.sh models/llms/LFM2-350M-Q4_K_M.gguf
# Optional second arg: context size in tokens (default 1024; use 2048+ with --rag_index)
# ./start_llama_server.sh models/llms/LFM2-350M-Q4_K_M.gguf 2048


# Device settings (llama-server path, model, context, port) come from
# config.sh next to this script. Arguments still override them.
CONFIG="$(dirname "$0")/config.sh"
[ -f "$CONFIG" ] && . "$CONFIG"

MODEL=${1:-$CHAT_MODEL}
CONTEXT=${2:-${CHAT_CONTEXT:-1024}}
PORT=${CHAT_PORT:-8080}

if [ -z "$MODEL" ]; then
  echo "No model file specified. Pass one as argument, or set CHAT_MODEL in config.sh."
  exit 1
fi
if [ ! -f "$MODEL" ]; then
  echo "Model file not found: $MODEL"
  exit 1
fi
if [ -z "$LLAMA_SERVER" ]; then
  echo "LLAMA_SERVER is not set. Add the absolute path to llama-server in config.sh."
  exit 1
fi
if [ ! -x "$LLAMA_SERVER" ]; then
  echo "llama-server not executable at: $LLAMA_SERVER (check LLAMA_SERVER in config.sh)"
  exit 1
fi

# start server
# note: settings mostly optimized for Raspberry Pi 5
nice -n 10 \
  "$LLAMA_SERVER" -m "$MODEL" \
  --cache-type-k f16 --cache-type-v f16 \
  -c $CONTEXT \
  --threads 2 \
  --batch-size 16 \
  --ubatch-size 8 \
  --port $PORT

