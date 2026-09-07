#!/bin/bash
#
# Starts the llama.cpp chat server for the voice agent.
#
# The llama-server path, model, context size and port come from config.sh
# next to this script. Arguments override the model and the context size:
#
#   ./start_llamacpp_server.sh                          # everything from config.sh
#   ./start_llamacpp_server.sh models/llms/other.gguf   # another model
#   ./start_llamacpp_server.sh models/llms/other.gguf 8192

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

