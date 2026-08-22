# Downloads the embedding model (all-MiniLM-L6-v2, GGUF, ~46MB) used for RAG.
# Windows counterpart of download_embedding_model.sh.

# model lives in the repo root's models/ folder, one level above scripts/
$dir = Join-Path (Split-Path $PSScriptRoot -Parent) "models\embeddings"
New-Item -ItemType Directory -Force $dir | Out-Null

$target = Join-Path $dir "all-MiniLM-L6-v2-ggml-model-f16.gguf"
Invoke-WebRequest -Uri "https://huggingface.co/second-state/All-MiniLM-L6-v2-Embedding-GGUF/resolve/main/all-MiniLM-L6-v2-ggml-model-f16.gguf" -OutFile $target

Write-Output "Done: $target"
