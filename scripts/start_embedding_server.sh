#!/bin/bash
#
# Starts the llama.cpp embedding server used for retrieval.
#
# The llama-server path, model and port come from config.sh next to this
# script; an argument overrides the model. Download the model first with
# download_embedding_model.sh.
#
#   ./start_embedding_server.sh [model.gguf]

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

# Notes:
# - the batch size must cover a whole chunk, since an embedding cannot be split
# - --host 0.0.0.0 lets another machine on the network use this server, for
#   example to build the index with rag_ingest.py --embedding_server_url
nice -n 10 \
  "$LLAMA_SERVER" -m "$MODEL" \
  --embedding \
  --pooling mean \
  -c 512 -b 512 -ub 512 \
  --threads 2 \
  --host 0.0.0.0 \
  --port $PORT
