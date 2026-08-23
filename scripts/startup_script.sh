#!/bin/bash
# DietPi-AutoStart custom script
# create with dietpi-autostart
# or copy to: /var/lib/dietpi/dietpi-autostart/custom.sh
#
# This is the CrankGPT DIY startup script
# (https://github.com/squeezlabs/crankgpt_diy/blob/main/dietpi/startup_script.sh)
# with a third mode added: OutdoorGPT, i.e. the voice agent plus RAG over the
# document collection. Set MODE below and reboot.

echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null

cd /root/dev/edge_voice_agent || exit 1
source venv_rpi/bin/activate || exit 1

# Mode: 1 = Voice Agent, 2 = Translation, 3 = OutdoorGPT (agent + RAG)
MODE=3

# Platform: rpi5 or opi5
PLATFORM=rpi5

# Mode 3 only: chat model and context size. The context must fit the retrieved
# chunks on top of the conversation, so it is set explicitly here.
OUTDOOR_MODEL=models/llms/LFM2.5-1.2B-Instruct-Q4_K_M.gguf
OUTDOOR_CONTEXT=4096

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
        sh start_llamacpp_server.sh $OUTDOOR_MODEL $OUTDOOR_CONTEXT > /var/log/llama-server.log 2>&1 &

        echo "Starting embedding server (RAG)..."
        sh start_embedding_server.sh > /var/log/embedding-server.log 2>&1 &

        echo "Starting OutdoorGPT..."
        # The agent waits for both servers itself (~30s retry each), so the
        # background starts above do not need a sleep here.
        python voice_agent_cli.py --platform $PLATFORM --log-conversation --audio-device-input 1 --audio-device-output 0 --speaking_rate 1. --prompt_file prompts.json --rag_index rag_index
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

exit 0
