#!/usr/bin/env bash
# Example IPC session for pattern-engine.
#
# Prerequisites:
#   1. Start krach-engine in another terminal: cargo run
#   2. Ensure socat is installed (brew install socat / apt install socat)
#
# Usage: ./examples/ipc_session.sh [socket_path]
#
# Default socket path: /tmp/krach.sock

set -euo pipefail

SOCK="${1:-/tmp/krach.sock}"

if ! command -v socat &>/dev/null; then
    echo "Error: socat is required. Install with: brew install socat (macOS) or apt install socat (Linux)"
    exit 1
fi

send() {
    local msg="$1"
    local label="${2:-}"
    [ -n "$label" ] && echo ">>> $label"
    echo "$msg"
    response=$(echo "$msg" | socat - UNIX-CONNECT:"$SOCK")
    echo "<<< $response"
    echo
}

echo "=== pattern-engine IPC session ==="
echo "Socket: $SOCK"
echo

# Ping
send '{"cmd":"Ping"}' "Ping"

# Set a simple pattern on d1: two notes in a cat
send '{"cmd":"SetPattern","slot":"d1","pattern":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Note","channel":0,"note":60,"velocity":100,"dur":0.5}},{"op":"Atom","value":{"type":"Note","channel":0,"note":64,"velocity":100,"dur":0.5}}]}}' \
    "SetPattern d1: cat [c4, e4]"

# Set a euclidean rhythm on d2
send '{"cmd":"SetPattern","slot":"d2","pattern":{"op":"Euclid","pulses":3,"steps":8,"rotation":0,"child":{"op":"Atom","value":{"type":"Note","channel":9,"note":36,"velocity":100,"dur":0.25}}}}' \
    "SetPattern d2: euclid(3,8) kick"

# Change BPM
send '{"cmd":"SetBpm","bpm":140.0}' "SetBpm 140"

# Hush d1
send '{"cmd":"Hush","slot":"d1"}' "Hush d1"

# Hush all
send '{"cmd":"HushAll"}' "HushAll"

echo "Done."
