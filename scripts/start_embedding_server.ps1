# Starts llama.cpp server in embedding mode (for RAG) on Windows.
# Counterpart of start_embedding_server.sh; same model and flags, so an index
# built on the PC matches the embeddings the Pi computes at question time.
#
# Requires the llama.cpp Windows build (llama-server.exe), either in PATH
# or in the default location below.
#
# Usage: .\start_embedding_server.ps1 [path\to\model.gguf]

param(
    [string]$Model = (Join-Path (Split-Path $PSScriptRoot -Parent) "models\embeddings\all-MiniLM-L6-v2-ggml-model-f16.gguf")
)

if (-not (Test-Path $Model)) {
    Write-Error "Embedding model not found: $Model`nDownload it first with: powershell -File scripts\download_embedding_model.ps1"
    exit 1
}

$server = (Get-Command llama-server -ErrorAction SilentlyContinue).Source
if (-not $server) {
    $fallback = "$env:USERPROFILE\tools\llama.cpp\llama-server.exe"
    if (Test-Path $fallback) { $server = $fallback }
}
if (-not $server) {
    Write-Error "llama-server.exe not found in PATH or $env:USERPROFILE\tools\llama.cpp\. Download a win-cpu-x64 build from https://github.com/ggml-org/llama.cpp/releases"
    exit 1
}

# batch size must cover the full chunk length for embeddings
& $server -m $Model `
    --embedding `
    --pooling mean `
    -c 512 -b 512 -ub 512 `
    --port 8081
