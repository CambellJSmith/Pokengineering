#!/usr/bin/env bash
# Run DeSmuME headless with the ARM9 GDB stub and drive it with a GDB (Python) script.
# Usage: tools/emu/run_headless.sh ROM GDB_SCRIPT [SECONDS] [LOG] [SHOT_DIR]
#   SHOT_DIR (optional): save a screenshot of the emulator window every SHOT_EVERY s.
# Requires: apt-get install desmume gdb-multiarch xvfb imagemagick
set -euo pipefail
ROM="$1"; SCRIPT="$2"; SECS="${3:-120}"; LOG="${4:-/dev/stdout}"; SHOTS="${5:-}"
PORT="${PORT:-3333}"; DISP="${DISP:-:99}"; SHOT_EVERY="${SHOT_EVERY:-5}"
export SDL_AUDIODRIVER=dummy
Xvfb "$DISP" -screen 0 640x480x24 >/dev/null 2>&1 &
XV=$!
sleep 1
DISPLAY="$DISP" /usr/games/desmume-cli --arm9gdb="$PORT" --disable-sound --disable-limiter \
    "$ROM" >/tmp/desmume_headless.log 2>&1 &
EMU=$!
SHOOT=""
if [[ -n "$SHOTS" ]]; then
    mkdir -p "$SHOTS"
    ( i=0; while sleep "$SHOT_EVERY"; do i=$((i+1));
        import -display "$DISP" -window root "$SHOTS/shot_$(printf %03d $i).png" 2>/dev/null || true; done ) &
    SHOOT=$!
fi
cleanup() { kill $EMU $XV ${SHOOT:-} 2>/dev/null || true; }
trap cleanup EXIT
sleep 3
timeout "$SECS" gdb-multiarch -q -nx -batch \
    -ex "set architecture armv5te" -ex "set pagination off" -ex "set confirm off" \
    -ex "target remote localhost:$PORT" -x "$SCRIPT" >"$LOG" 2>&1 || true
