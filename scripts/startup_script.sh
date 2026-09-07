#!/bin/bash
# DietPi-AutoStart custom script
# create with dietpi-autostart
# or copy to: /var/lib/dietpi/dietpi-autostart/custom.sh
#
# This is the CrankGPT DIY startup script
# (https://github.com/squeezlabs/crankgpt_diy/blob/main/dietpi/startup_script.sh)
# with a third mode added: OutdoorGPT, i.e. the voice agent plus RAG over the
# document collection. Set MODE below and reboot.
#
# IMPORTANT: the "#!" above must stay on the very first line. A blank line in
# front of it makes systemd fail with "Exec format error" and nothing starts.
#
# Modes 1 and 2 are left exactly as CrankGPT shipped them. Mode 3 reads its
# paths from config.sh in the agent directory, so a missing or broken config
# can never break the stock modes.

echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

# The one path this script has to know by itself; everything else is in config.sh.
AGENT_DIR=/root/edge_voice_agent

cd "$AGENT_DIR" || exit 1
[ -f ./config.sh ] && . ./config.sh
source "${VENV:-venv}/bin/activate" || exit 1

# Mode: 1 = Voice Agent, 2 = Translation, 3 = OutdoorGPT (agent + RAG)
MODE=3

# Platform: rpi5 or opi5
PLATFORM=${PLATFORM:-rpi5}

case $MODE in
    1)
        echo "Starting llama-server (agent)..."
        sh start_llama_server_agent.sh

        echo "Starting Voice Agent..."
        python voice_agent_cli.py --platform $PLATFORM --log-conversation --audio-device-input 1 --audio-device-output 0 --speaking_rate 1. --prompt_file prompts.json
        ;;
    2)
        echo "Starting llama-server (translation)..."
        sh start_llama_server_translation.sh

        echo "Starting Voice Translate..."
        python voice_translate_cli.py --preload-tts --platform $PLATFORM --audio-device-input 1 --audio-device-output 0
        ;;
    3)
        echo "Starting llama-server (outdoor agent)..."
        sh start_llamacpp_server.sh > /var/log/llama-server.log 2>&1 &

        echo "Starting embedding server (RAG)..."
        sh start_embedding_server.sh > /var/log/embedding-server.log 2>&1 &

        echo "Starting OutdoorGPT..."
        # VERBOSE=1 in config.sh logs the retrieved chunks for every question.
        VERBOSE_FLAG=""
        [ "${VERBOSE:-0}" = "1" ] && VERBOSE_FLAG="--verbose"
        # The agent waits for both servers itself (~30s retry each), so the
        # background starts above do not need a sleep here.
        python voice_agent_cli.py --platform $PLATFORM --log-conversation --audio-device-input ${AUDIO_IN:-1} --audio-device-output ${AUDIO_OUT:-0} --speaking_rate ${SPEAKING_RATE:-1.} --end_of_utterance_duration ${SILENCE_SECONDS:-0.7} --prompt_file prompts.json --rag_index ${RAG_INDEX:-rag_index} $VERBOSE_FLAG
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

exit 0
