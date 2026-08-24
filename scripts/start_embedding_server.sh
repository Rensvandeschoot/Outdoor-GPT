#!/bin/bash
#
# Starts llama.cpp server in embedding mode (for RAG).
#
# Download the embedding model first with download_embedding_model.sh.
# Runs on port 8081, next to the chat LLM server on port 8080.
#
# ./start_embedding_server.sh [model.gguf]

# Device settings (llama-server path, model, port) come from config.sh next
# to this script. An argument still overrides the model.
CONFIG="$(dirname "$0")/config.sh"
[ -f "$CONFIG" ] && . "$CONFIG"

MODEL=${1:-${EMBED_MODEL:-models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf}}
PORT=${EMBED_PORT:-8081}

if [ ! -f "$MODEL" ]; then
  echo "Embedding model not found: $MODEL"
  echo "Download it first with: ./download_embedding_model.sh"
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

# notes:
# - batch size must cover the full chunk length for embeddings
# - listens on all interfaces so a PC on the local network can run
#   rag_ingest.py against this server (see Readme, Outdoor GPT section)
nice -n 10 \
  "$LLAMA_SERVER" -m "$MODEL" \
  --embedding \
  --pooling mean \
  -c 512 -b 512 -ub 512 \
  --threads 2 \
  --host 0.0.0.0 \
  --port $PORT
