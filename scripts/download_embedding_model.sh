#!/bin/bash
#
# Downloads the embedding model (all-MiniLM-L6-v2, GGUF, ~46MB) used for RAG.
# Used by start_embedding_server.sh and (indirectly) rag_ingest.py / rag.py.

mkdir -p models/embeddings

curl -L -o models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf \
  "https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF/resolve/main/all-MiniLM-L6-v2-ggml-model-f16.gguf"

echo "Done: models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf"
