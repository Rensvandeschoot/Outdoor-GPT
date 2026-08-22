#!/bin/bash
#
# Off-grid autostart for OutdoorGPT: starts the chat LLM server, the
# embedding server and the voice agent at boot, no terminals needed.
#
# The handcrank/CrankGPT setup uses DietPi's autostart (dietpi-autostart ->
# "Custom script"). The Pi likely already has a script at
#   /var/lib/dietpi/dietpi-autostart/custom.sh
# that starts the llama server and the plain voice agent. Replace it with
# this one (keep a backup!), after checking that AGENT_DIR, the model file
# and the venv path below match what the existing script uses:
#
#   sudo cp custom.sh custom.sh.bak
#   sudo cp startup_script.sh /var/lib/dietpi/dietpi-autostart/custom.sh
#   sudo chmod +x /var/lib/dietpi/dietpi-autostart/custom.sh

# --- adjust these to match your installation -------------------------------
AGENT_DIR="$HOME/edge_voice_agent"
CHAT_MODEL="models/llms/LFM2-350M-Q4_K_M.gguf"
CHAT_CONTEXT=2048   # room for the RAG chunks; grow along with a bigger model
# ---------------------------------------------------------------------------

cd "$AGENT_DIR" || exit 1

# 1. Chat LLM server (port 8080), in the background
./start_llamacpp_server.sh "$CHAT_MODEL" "$CHAT_CONTEXT" &

# 2. Embedding server for RAG (port 8081), in the background
./start_embedding_server.sh &

# 3. Voice agent in the foreground; it waits for both servers itself
#    (the LLM client retries ~30s, the RAG retriever retries ~30s)
source venv/bin/activate
python voice_agent_cli.py --platform rpi5 --prompt_file prompts.json --rag_index rag_index
