#!/bin/bash
#
# One-shot OutdoorGPT installer for a Pi that already runs the stock
# CrankGPT / edge_voice_agent setup.
#
# Run as root, from the cloned repo:
#     cd /root/Outdoor-GPT && ./scripts/install_on_pi.sh
#
# It is safe to re-run: every step checks the current state first, backups are
# timestamped, and nothing is deleted. Steps it cannot safely automate are
# reported at the end instead of guessed at.

set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="${AGENT_DIR:-/root/edge_voice_agent}"
CUSTOM=/var/lib/dietpi/dietpi-autostart/custom.sh
STAMP=$(date +%Y%m%d_%H%M%S)
TODO=""

note() { echo "  $*"; }
ok()   { echo "  OK    $*"; }
warn() { echo "  WARN  $*"; TODO="$TODO
  - $*"; }
die()  { echo "FAILED: $*" >&2; exit 1; }

echo "=== OutdoorGPT install ==="
echo "repo:  $REPO"
echo "agent: $AGENT_DIR"

# ---------------------------------------------------------------- preflight
echo
echo "[1/6] Checking prerequisites"
[ "$(id -u)" = "0" ] || die "run as root (sudo -i)"
[ -f "$REPO/scripts/config.sh" ] || die "run this from the cloned repo: cd /root/Outdoor-GPT && ./scripts/install_on_pi.sh"
[ -d "$AGENT_DIR" ] || die "$AGENT_DIR not found. Install edge_voice_agent first (see README Step 4.1)."
[ -x "$AGENT_DIR/venv/bin/python" ] || die "no virtualenv at $AGENT_DIR/venv. Install edge_voice_agent first."
ok "agent directory and virtualenv"

# llama-server, as named in the config we are about to install
LLAMA=$(grep -E "^LLAMA_SERVER=" "$REPO/scripts/config.sh" | cut -d= -f2-)
if [ -x "$LLAMA" ]; then
  ok "llama-server at $LLAMA"
else
  FOUND=$(command -v llama-server 2>/dev/null || true)
  if [ -n "$FOUND" ]; then
    warn "llama-server is at '$FOUND', but config.sh says '$LLAMA'. Fix LLAMA_SERVER in scripts/config.sh and re-run."
  else
    die "llama-server not found at '$LLAMA' and not in PATH. Build llama.cpp first."
  fi
fi

CHAT=$(grep -E "^CHAT_MODEL=" "$REPO/scripts/config.sh" | cut -d= -f2-)
[ -f "$AGENT_DIR/$CHAT" ] && ok "chat model $CHAT" \
  || warn "chat model missing: $AGENT_DIR/$CHAT (download it, or point CHAT_MODEL at one you have)"

for d in moonshine_v1_tiny piper silero_vad; do
  [ -e "$AGENT_DIR/models/$d" ] && ok "speech model $d" \
    || warn "speech model missing: models/$d (run the upstream download scripts)"
done

# Optional e-ink recipe screen. Non-fatal on purpose: most builds do not have
# the panel fitted. See README "Recipe screen (optional e-ink)".
"$AGENT_DIR/venv/bin/python" -c "import PIL" >/dev/null 2>&1 \
  && ok "Pillow present (e-ink rendering)" \
  || note "Pillow not installed - only for the optional e-ink recipe screen (pip install pillow)"
"$AGENT_DIR/venv/bin/python" -c "import waveshare_epd" >/dev/null 2>&1 \
  && ok "waveshare_epd present (e-ink driver)" \
  || note "waveshare_epd not found - only for the optional e-ink recipe screen (see README)"

# ------------------------------------------------------------------ overlay
echo
echo "[2/6] Copying our files over the agent"
cp "$REPO"/scripts/*.py "$REPO"/scripts/*.sh "$REPO"/prompts.json "$AGENT_DIR/" \
  || die "copy failed"
cp "$REPO/scripts/config.sh" "$AGENT_DIR/" || die "copy of config.sh failed"
chmod +x "$AGENT_DIR"/start_*.sh "$AGENT_DIR"/download_embedding_model.sh "$AGENT_DIR"/startup_script.sh
ok "scripts, prompts.json and config.sh"

if [ -d "$REPO/rag_index" ]; then
  cp -r "$REPO/rag_index" "$AGENT_DIR/" || die "copy of rag_index failed"
  CHUNKS=$("$AGENT_DIR/venv/bin/python" -c "import json;print(len(json.load(open('$AGENT_DIR/rag_index/chunks.json',encoding='utf-8'))))" 2>/dev/null || echo "?")
  ok "rag_index ($CHUNKS chunks)"
else
  warn "no rag_index/ in the repo - build it on the PC first (README Step 3)"
fi

# ---------------------------------------------------------- embedding model
echo
echo "[3/6] Embedding model"
EMBED=$(grep -E "^EMBED_MODEL=" "$REPO/scripts/config.sh" | cut -d= -f2-)
if [ -f "$AGENT_DIR/$EMBED" ]; then
  ok "already present ($(stat -c%s "$AGENT_DIR/$EMBED") bytes)"
else
  note "downloading (~46 MB)..."
  (cd "$AGENT_DIR" && ./download_embedding_model.sh) || die "download failed"
  ok "downloaded"
fi

# -------------------------------------------------------------- boot script
echo
echo "[4/6] Installing the boot script"
if [ -f "$CUSTOM" ]; then
  cp "$CUSTOM" "$CUSTOM.$STAMP.bak"
  ok "backed up existing custom.sh to custom.sh.$STAMP.bak"
fi
install -m 755 "$AGENT_DIR/startup_script.sh" "$CUSTOM" || die "could not install $CUSTOM"
head -c 11 "$CUSTOM" | grep -q '^#!/bin/bash' \
  && ok "shebang is on the first line" \
  || die "shebang check failed on $CUSTOM - systemd would refuse to run it"

IDX=$(cat /boot/dietpi/.dietpi-autostart_index 2>/dev/null || echo "")
if [ "$IDX" = "14" ]; then
  ok "DietPi autostart is set to custom script (14)"
else
  warn "DietPi autostart index is '$IDX', not 14: the boot script will never run. Fix with: dietpi-autostart"
fi

# ------------------------------------------------------------ network wait
echo
echo "[5/6] Removing the boot wait for the network"
DROPIN=/etc/systemd/system/dietpi-postboot.service.d/dietpi.conf
if [ -f "$DROPIN" ]; then
  mv "$DROPIN" "$DROPIN.disabled"
  systemctl daemon-reload
  ok "disabled (saves ~42s per boot; reverse by moving dietpi.conf.disabled back)"
elif [ -f "$DROPIN.disabled" ]; then
  ok "already disabled"
else
  ok "no network-wait drop-in present"
fi
sed -i 's/^AUTO_SETUP_BOOT_WAIT_FOR_NETWORK=1/AUTO_SETUP_BOOT_WAIT_FOR_NETWORK=0/' /boot/dietpi.txt 2>/dev/null

# ------------------------------------------------------------- audio check
echo
echo "[6/6] Audio devices"
note "config.sh uses AUDIO_IN=$(grep -E '^AUDIO_IN=' "$AGENT_DIR/config.sh" | cut -d= -f2) and AUDIO_OUT=$(grep -E '^AUDIO_OUT=' "$AGENT_DIR/config.sh" | cut -d= -f2)"
note "these are sounddevice indices, and the numbering can differ per device:"
"$AGENT_DIR/venv/bin/python" -c "import sounddevice; print(sounddevice.query_devices())" 2>&1 | sed 's/^/    /'
warn "verify the two indices above match the phone's microphone and speaker, then correct config.sh if needed"

# ----------------------------------------------------------------- summary
echo
echo "=== Done ==="
if [ -n "$TODO" ]; then
  echo "Still needs attention:$TODO"
else
  echo "No outstanding items."
fi
echo
echo "Next: reboot, then check with"
echo "  journalctl -u dietpi-autostart_custom.service -b --no-pager | tail -20"
echo "  systemd-analyze critical-chain dietpi-autostart_custom.service"
