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

# The one path this script has to know by itself; everything else is in config.sh.
# (Taken from the environment only by tests/startup_sim/test_boot_script.sh;
# at boot it is never set, so the default applies.)
AGENT_DIR=${AGENT_DIR:-/root/edge_voice_agent}

cd "$AGENT_DIR" || exit 1
[ -f ./config.sh ] && . ./config.sh
source "${VENV:-venv}/bin/activate" || exit 1

# Mode: 1 = Voice Agent, 2 = Translation, 3 = OutdoorGPT (agent + RAG)
MODE=3

# Platform: rpi5 or opi5
PLATFORM=${PLATFORM:-rpi5}

# CPU governor. CrankGPT pins every core at maximum clock with "performance",
# and modes 1 and 2 keep that unchanged. Mode 3 defaults to "ondemand": on
# crank power a permanently boosted Pi 5 burns headroom while it sits idle,
# and that headroom is what the audio stage needs the moment the agent starts
# speaking. Set GOVERNOR in config.sh to override.
if [ "$MODE" = "3" ]; then
    GOVERNOR=${GOVERNOR:-ondemand}
else
    GOVERNOR=performance
fi
if grep -qw "$GOVERNOR" /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors 2>/dev/null; then
    echo "$GOVERNOR" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor > /dev/null
    echo "CPU governor: $GOVERNOR"
else
    echo "CPU governor '$GOVERNOR' not available on this kernel; left unchanged"
fi

# Clock ceiling, mode 3 only. The first sentence the phone speaks is the
# heaviest moment of the whole start-up: 5 A on the core rail at 2.4 GHz
# against 2.9 A at 1.5 GHz, with the 5 V input dipping 310 mV against 125 mV.
# On crank power that dip is what shuts the Pi down. The kernel rounds to the
# nearest available step, so the value that took effect is printed back.
if [ "$MODE" = "3" ] && [ -n "$CPU_MAX_KHZ" ]; then
    echo "$CPU_MAX_KHZ" | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq > /dev/null 2>&1
    echo "CPU clock ceiling: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null || echo unknown) kHz (requested $CPU_MAX_KHZ)"
fi

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
        # One OutdoorGPT at a time. Started by hand while the service runs, a
        # second copy fought the first for the ports, the GPIO pins and the
        # sound card. The lock (fd 9) is held for as long as this script runs;
        # every child below gets 9>&- so none of them keeps it after we are
        # gone. flock is part of util-linux, always there on DietPi.
        if command -v flock >/dev/null 2>&1; then
            exec 9>"${LOCK_FILE:-/run/outdoorgpt.lock}"
            if ! flock -n 9; then
                echo "OutdoorGPT is already running. To restart it: systemctl restart dietpi-autostart_custom.service"
                exit 1
            fi
        fi
        # With the lock held, any llama-server on our ports is a leftover (a
        # server started by hand, a script that was killed): it would hold the
        # port and the new server would fail to start.
        pkill -f "llama-server.* --port ${CHAT_PORT:-8080}( |\$)" 2>/dev/null
        pkill -f "llama-server.* --port ${EMBED_PORT:-8081}( |\$)" 2>/dev/null

        # Boot logs on the SD card, in logs/boot/ of the agent directory: this
        # script's own output with the agent's (boot_<n>.log, also still in
        # the journal) and each server's (boot_<n>_llama-server.log,
        # boot_<n>_embedding-server.log), appended to on every restart. On
        # DietPi /var/log and the journal usually live in RAM (DietPi-RAMlog),
        # so what went wrong was gone after the very power cycle that
        # recovered the phone. Boots are numbered, not dated: off-grid the
        # clock cannot be trusted. The newest BOOT_LOGS_KEEP (config.sh) are
        # kept.
        BOOT_LOG_DIR=logs/boot
        mkdir -p "$BOOT_LOG_DIR"
        BOOT_NR=$(cat "$BOOT_LOG_DIR/last" 2>/dev/null)
        case "$BOOT_NR" in ''|*[!0-9]*) BOOT_NR=0 ;; esac
        BOOT_NR=$(( BOOT_NR + 1 ))
        echo "$BOOT_NR" > "$BOOT_LOG_DIR/last"
        for f in "$BOOT_LOG_DIR"/boot_*.log; do
            [ -e "$f" ] || continue
            n=${f##*/boot_}
            n=${n%%[_.]*}
            case "$n" in ''|*[!0-9]*) continue ;; esac
            [ "$n" -le $(( BOOT_NR - ${BOOT_LOGS_KEEP:-5} )) ] && rm -f "$f"
        done
        CHAT_LOG="$BOOT_LOG_DIR/boot_${BOOT_NR}_llama-server.log"
        EMBED_LOG="$BOOT_LOG_DIR/boot_${BOOT_NR}_embedding-server.log"
        exec > >(tee -a "$BOOT_LOG_DIR/boot_$BOOT_NR.log" 9>&-) 2>&1
        echo "OutdoorGPT boot $BOOT_NR ($(date '+%Y-%m-%d %H:%M:%S'), clock not reliable off-grid)"

        # Conversation logs would otherwise pile up on the SD card for years;
        # keep the newest LOG_KEEP (config.sh) and drop the rest.
        ls -t logs/conversation_*.txt 2>/dev/null | tail -n +$(( ${LOG_KEEP:-50} + 1 )) | xargs -r rm -f

        # VERBOSE=1 in config.sh logs the retrieved chunks for every question.
        VERBOSE_FLAG=""
        [ "${VERBOSE:-0}" = "1" ] && VERBOSE_FLAG="--verbose"
        # Speech settings from config.sh; see the comments there.
        SPEECH_FLAGS=""
        [ "${TTS_WARMUP:-0}" = "1" ] && SPEECH_FLAGS="--tts_warmup"
        [ -n "${TTS_THREADS:-}" ] && [ "${TTS_THREADS}" != "0" ] && SPEECH_FLAGS="$SPEECH_FLAGS --tts_threads ${TTS_THREADS}"
        [ -n "${ASR_THREADS:-}" ] && [ "${ASR_THREADS}" != "0" ] && SPEECH_FLAGS="$SPEECH_FLAGS --asr_threads ${ASR_THREADS}"

        # Off-grid there is nobody with a terminal, so whatever stops is
        # started again: a server whose process has gone, and the agent
        # whenever it exits (a crash, a server it could not reach in time, a
        # turn that failed beyond repair). Without this, any exit left the
        # phone silent until the power was cycled: DietPi's unit has
        # RemainAfterExit=yes and no Restart=. The wait between attempts
        # doubles from RESTART_DELAY (config.sh) up to a minute, and drops
        # back once the agent has run for two minutes.
        # systemctl stop/restart (SIGTERM) and Ctrl-C end the loop and take
        # both servers down with it.
        CHAT_PID=""
        EMBED_PID=""
        # Stop both servers and wait (up to 5 s, then SIGKILL) until they are
        # gone, so a new one can take the port.
        stop_servers() {
            for p in $CHAT_PID $EMBED_PID; do kill "$p" 2>/dev/null; done
            for i in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 $CHAT_PID 2>/dev/null || kill -0 $EMBED_PID 2>/dev/null || break
                sleep 0.5
            done
            for p in $CHAT_PID $EMBED_PID; do kill -9 "$p" 2>/dev/null; done
            CHAT_PID=""
            EMBED_PID=""
        }
        stop_all() {
            echo "Stopping OutdoorGPT..."
            stop_servers
            exit 0
        }
        trap stop_all INT TERM

        DELAY=${RESTART_DELAY:-3}
        while true; do
            # The start scripts exec llama-server, so $! is the server itself.
            if [ -z "$CHAT_PID" ] || ! kill -0 "$CHAT_PID" 2>/dev/null; then
                echo "Starting llama-server (outdoor agent)..."
                sh start_llamacpp_server.sh >> "$CHAT_LOG" 2>&1 9>&- &
                CHAT_PID=$!
            fi
            if [ -z "$EMBED_PID" ] || ! kill -0 "$EMBED_PID" 2>/dev/null; then
                echo "Starting embedding server (RAG)..."
                sh start_embedding_server.sh >> "$EMBED_LOG" 2>&1 9>&- &
                EMBED_PID=$!
            fi

            echo "Starting OutdoorGPT..."
            # The agent waits for both servers itself, so the background starts
            # above need no sleep here. It gets their PIDs: while a server's
            # process lives it waits up to SERVER_WAIT seconds for the model to
            # load, and it stops waiting at once when that process has died.
            # python -u: unbuffered output, so journal timestamps mark the moment a
            # line was printed rather than the moment a buffer happened to flush.
            STARTED=$SECONDS
            OUTDOORGPT_CHAT_PID=$CHAT_PID OUTDOORGPT_EMBED_PID=$EMBED_PID \
            python -u voice_agent_cli.py --platform $PLATFORM --log-conversation --audio-device-input ${AUDIO_IN:-1} --audio-device-output ${AUDIO_OUT:-0} --speaking_rate ${SPEAKING_RATE:-1.} --end_of_utterance_duration ${SILENCE_SECONDS:-0.7} --prompt_file prompts.json --rag_index ${RAG_INDEX:-rag_index} --max_history_turns ${HISTORY_TURNS:-8} --server_wait ${SERVER_WAIT:-90} $VERBOSE_FLAG $SPEECH_FLAGS 9>&-
            RC=$?
            RAN=$(( SECONDS - STARTED ))
            # 4: a server process runs but never became ready (see
            # voice_agent_utils.EXIT_SERVER_STUCK). Restarting only the agent
            # would find it stuck again, so replace both servers.
            if [ "$RC" = 4 ]; then
                echo "A server never became ready; stopping both servers to start them again"
                stop_servers
            fi
            # 3: the yellow button was held 20 s (EXIT_RESTART_PIPELINE): a
            # restart asked for, so both servers and the agent start again
            # now, without the wait.
            if [ "$RC" = 3 ]; then
                echo "Restarting the whole pipeline (button held 20 s)"
                stop_servers
                DELAY=${RESTART_DELAY:-3}
                continue
            fi
            [ "$RAN" -ge 120 ] && DELAY=${RESTART_DELAY:-3}
            echo "OutdoorGPT stopped (exit code $RC after ${RAN}s); starting it again in ${DELAY}s"
            # sleep in the background and wait for it, so a SIGTERM is acted
            # on at once instead of after the sleep.
            sleep "$DELAY" &
            wait $!
            DELAY=$(( DELAY * 2 > 60 ? 60 : DELAY * 2 ))
        done
        ;;
    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

exit 0
