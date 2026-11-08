#!/bin/bash
#
# Checks the restart loop of scripts/startup_script.sh (mode 3) by running the
# real script, with the real start_*_server.sh, against a fake `python` (the
# agent) and a fake `llama-server`. Runs anywhere bash runs, a PC included;
# nothing is installed and nothing outside a temp dir is touched.
#
#     bash test_boot_script.sh
#
# Each case gets its own agent dir. The fake agent's behaviour per run comes
# from a plan file (one line per run: "<seconds to live> <exit code>"); a
# server dies after the seconds in die_<port>, once.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
T=$(mktemp -d)
FAILED=0
SCRIPT_PIDS=""
cleanup() {
  for p in $SCRIPT_PIDS; do kill "$p" 2>/dev/null; done
  for f in "$T"/*/agent.pid "$T"/*/server_*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
  rm -rf "$T"
}
trap cleanup EXIT

ok()   { echo "  ok    $*"; }
fail() { echo "  FAIL  $*"; FAILED=1; }
count() { grep -c "$1" "$2" 2>/dev/null || true; }

# A fresh agent directory with the real boot script and server scripts.
setup() {
  A="$T/$1"
  mkdir -p "$A/venv/bin" "$A/logs" "$A/var"
  cp "$REPO/scripts/startup_script.sh" "$REPO/scripts/start_llamacpp_server.sh" \
     "$REPO/scripts/start_embedding_server.sh" "$REPO/scripts/config.sh" "$A/"
  cat >> "$A/config.sh" <<EOF

# --- test overrides
LLAMA_SERVER=$A/fake-llama-server
RESTART_DELAY=1
CPU_MAX_KHZ=
EOF
  ( . "$A/config.sh"; mkdir -p "$(dirname "$A/$CHAT_MODEL")" "$(dirname "$A/$EMBED_MODEL")"
    touch "$A/$CHAT_MODEL" "$A/$EMBED_MODEL" )
  echo "export PATH=\"$A/venv/bin:\$PATH\"" > "$A/venv/bin/activate"

  cat > "$A/venv/bin/python" <<'EOF'
#!/bin/bash
# Fake agent. Runs in the agent dir, like the real one.
n=$(( $(cat runs 2>/dev/null || echo 0) + 1 )); echo "$n" > runs
echo "$$" > agent.pid
echo "$(date +%s) start $n" >> agent.log
line=$(sed -n "${n}p" plan 2>/dev/null); [ -z "$line" ] && line="999 0"
set -- $line
trap 'echo "$(date +%s) term $n" >> agent.log; exit 0' TERM INT
sleep "$1" &
wait $!
echo "$(date +%s) exit $n $2" >> agent.log
exit "$2"
EOF
  cat > "$A/fake-llama-server" <<'EOF'
#!/bin/bash
# Fake llama-server: logs its start, lives until killed or until die_<port>.
port=$(echo "$*" | sed -n 's/.*--port \([0-9]*\).*/\1/p')
echo "$$" > "server_$port.pid"
echo "$(date +%s) up $port" >> servers.log
trap 'echo "$(date +%s) term $port" >> servers.log; exit 0' TERM INT
life=999
if [ -f "die_$port" ]; then life=$(cat "die_$port"); rm -f "die_$port"; fi
sleep "$life" &
wait $!
echo "$(date +%s) died $port" >> servers.log
EOF
  chmod +x "$A/venv/bin/python" "$A/fake-llama-server" "$A"/*.sh
}

start_script() {
  AGENT_DIR="$A" bash "$A/startup_script.sh" > "$A/script.out" 2>&1 &
  SCRIPT_PID=$!
  SCRIPT_PIDS="$SCRIPT_PIDS $SCRIPT_PID"
}

wait_for() {  # wait_for <seconds> '<condition>': re-evaluate until it holds
  local t=$(( $(date +%s) + $1 )); shift
  while [ "$(date +%s)" -le "$t" ]; do eval "$1" && return 0; sleep 0.2; done
  return 1
}

echo "1. The agent crashes twice: it is started again, with a growing delay"
setup crash
printf '1 1\n1 1\n60 0\n' > "$A/plan"
start_script
if wait_for 20 '[ "$(count " start 3" "$A/agent.log")" = 1 ]'; then
  ok "three agent runs after two crashes"
else
  fail "expected a third run; agent.log:"; cat "$A/agent.log" 2>/dev/null
fi
e1=$(awk '$2=="exit" && $3==1 {print $1}' "$A/agent.log"); s2=$(awk '$2=="start" && $3==2 {print $1}' "$A/agent.log")
e2=$(awk '$2=="exit" && $3==2 {print $1}' "$A/agent.log"); s3=$(awk '$2=="start" && $3==3 {print $1}' "$A/agent.log")
if [ -n "$s3" ] && [ $(( s3 - e2 )) -gt $(( s2 - e1 )) ]; then
  ok "second wait ($(( s3 - e2 ))s) longer than the first ($(( s2 - e1 ))s)"
else
  fail "waits did not grow: $(( ${s2:-0} - ${e1:-0} ))s then $(( ${s3:-0} - ${e2:-0} ))s"
fi
[ "$(count ' up 8080' "$A/servers.log")" = 1 ] && [ "$(count ' up 8081' "$A/servers.log")" = 1 ] \
  && ok "servers that kept running were not started twice" \
  || { fail "servers started more than once:"; cat "$A/servers.log"; }
grep -q "OutdoorGPT stopped (exit code 1" "$A/script.out" && ok "each stop is logged with its exit code" \
  || fail "no 'OutdoorGPT stopped' line in the output"

echo "2. The chat server dies: it is started again before the agent"
setup server
echo 1 > "$A/die_8080"
printf '3 1\n60 0\n' > "$A/plan"
start_script
if wait_for 20 '[ "$(count " up 8080" "$A/servers.log")" = 2 ]'; then
  ok "chat server started again"
else
  fail "chat server not restarted; servers.log:"; cat "$A/servers.log" 2>/dev/null
fi
[ "$(count ' up 8081' "$A/servers.log")" = 1 ] && ok "embedding server left alone" \
  || fail "embedding server restarted although it was running"
wait_for 10 '[ "$(count " start 2" "$A/agent.log")" = 1 ]' && ok "agent started again" || fail "agent not restarted"

echo "3. systemctl stop (SIGTERM to every process): the loop ends, servers go down"
setup stop
printf '60 0\n' > "$A/plan"
start_script
wait_for 15 '[ -f "$A/agent.pid" ]' || fail "agent never started"
wait_for 10 '[ -f "$A/server_8080.pid" ]' || fail "chat server never started"
sleep 1
kill -TERM "$SCRIPT_PID" 2>/dev/null
kill -TERM "$(cat "$A/agent.pid")" 2>/dev/null
if wait_for 10 '! kill -0 "$SCRIPT_PID" 2>/dev/null'; then
  ok "boot script exited"
else
  fail "boot script still running after SIGTERM"
fi
sleep 2
[ "$(count ' start ' "$A/agent.log")" = 1 ] && ok "agent not started again" || fail "agent was restarted after SIGTERM"
[ "$(count ' term 8080' "$A/servers.log")" = 1 ] && [ "$(count ' term 8081' "$A/servers.log")" = 1 ] \
  && ok "both servers stopped by the script" || { fail "servers not stopped:"; cat "$A/servers.log"; }

echo "4. Boot logs: one set per boot on disk, the newest BOOT_LOGS_KEEP (5) kept"
setup bootlogs
printf '60 0\n' > "$A/plan"
for i in 1 2 3 4 5 6 7; do
  rm -f "$A/agent.pid" "$A/runs"
  start_script
  wait_for 15 '[ -f "$A/agent.pid" ]' || fail "boot $i: agent never started"
  kill -TERM "$SCRIPT_PID" 2>/dev/null; kill -TERM "$(cat "$A/agent.pid")" 2>/dev/null
  wait_for 10 '! kill -0 "$SCRIPT_PID" 2>/dev/null' || fail "boot $i: script did not stop"
done
kept=$(ls "$A/logs/boot" | grep -c '^boot_[0-9]*\.log$')
[ "$(cat "$A/logs/boot/last")" = 7 ] && ok "boots numbered 1..7" || fail "last boot number is $(cat "$A/logs/boot/last")"
[ "$kept" = 5 ] && [ -f "$A/logs/boot/boot_7.log" ] && [ ! -f "$A/logs/boot/boot_2.log" ] \
  && ok "5 boot logs kept (3..7)" || { fail "kept $kept boot logs:"; ls "$A/logs/boot"; }
grep -q "Starting OutdoorGPT" "$A/logs/boot/boot_7.log" && ok "the script's output is in the boot log" \
  || fail "boot_7.log lacks the script's output"
[ -f "$A/logs/boot/boot_7_llama-server.log" ] && ok "server log of the boot kept next to it" \
  || fail "no boot_7_llama-server.log"

echo
if [ "$FAILED" = 0 ]; then echo "All boot script checks passed."; else echo "Boot script checks FAILED."; fi
exit "$FAILED"
