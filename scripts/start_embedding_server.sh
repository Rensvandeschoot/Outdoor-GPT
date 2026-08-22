#!/bin/bash
#
# Starts llama.cpp server in embedding mode (for RAG).
#
# Download the embedding model first with download_embedding_model.sh.
# Runs on port 8081, next to the chat LLM server on port 8080.
#
# ./start_embedding_server.sh [model.gguf]

MODEL=${1:-models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf}

if [ ! -f "$MODEL" ]; then
  echo "Embedding model not found: $MODEL"
  echo "Download it first with: ./download_embedding_model.sh"
  exit 1
fi

# find llama-server binary path
LLAMA_SERVER=$(which llama-server 2>/dev/null)
if [ -z "$LLAMA_SERVER" ]; then
  echo "llama-server not found in PATH. Please install llama.cpp or add it to PATH."
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
  --port 8081
