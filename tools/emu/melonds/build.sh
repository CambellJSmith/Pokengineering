#!/usr/bin/env bash
# Build a headless melonDS-core driver (soft renderer, FreeBIOS, no JIT) for testing.
# melonDS emulates the ARM9 MPU, so it catches null-pointer reads DeSmuME hides.
#   tools/emu/melonds/build.sh            -> work/emu/melonds/drv
#   work/emu/melonds/drv ROM OUTDIR "frame:keyhex:hold,...;shotframe,..."
#   env: WATCH=1 (print display regs at shots), TRAP=1 (stop + dump regs on an
#        exception), EXITCAP=frame (force the capture's exit state)
# Keys: A 1, B 2, SELECT 4, START 8, RIGHT 10, LEFT 20, UP 40, DOWN 80, R 100, L 200.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$HERE/../../.."
W="$ROOT/work/emu/melonds"; mkdir -p "$W"
[[ -d "$W/src" ]] || git clone -q --depth 1 https://github.com/melonDS-emu/melonDS.git "$W/src"
cmake -S "$W/src" -B "$W/build" -G Ninja -DBUILD_QT_SDL=OFF -DENABLE_JIT=OFF -DENABLE_OGLRENDERER=OFF \
    -DENABLE_GDBSTUB=OFF -DCMAKE_BUILD_TYPE=Release >/dev/null
ninja -C "$W/build" core >/dev/null
g++ -O2 -std=c++20 -I"$W/src/src" -I"$W/build/src" -I"$W/src/src/teakra/include" "$HERE/drv.cpp" "$HERE/platform.cpp" \
    -o "$W/drv" "$W/build/src/libcore.a" "$W/build/src/teakra/src/libteakra.a" -lpthread -lz
echo "$W/drv"
