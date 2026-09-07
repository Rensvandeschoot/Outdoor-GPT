#!/bin/bash
#
# Downloads the embedding model used for retrieval (all-MiniLM-L6-v2 as GGUF,
# about 46 MB) to the path config.sh names in EMBED_MODEL.
#
# The URL is specific to this model. Switching to another embedding model means
# changing both this URL and EMBED_MODEL, and rebuilding the index with it.

CONFIG="$(dirname "$0")/config.sh"
[ -f "$CONFIG" ] && . "$CONFIG"

TARGET=${EMBED_MODEL:-models/embeddings/all-MiniLM-L6-v2-ggml-model-f16.gguf}
URL="https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF/resolve/main/all-MiniLM-L6-v2-ggml-model-f16.gguf"

mkdir -p "$(dirname "$TARGET")"
curl -L -o "$TARGET" "$URL" || exit 1

echo "Done: $TARGET"
