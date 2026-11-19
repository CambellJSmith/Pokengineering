#!/usr/bin/env bash
# Build the profiling driver: a private copy of the melonDS core with a per-instruction
# ARM9 cycle hook (g_prof_hook), so tools/emu/melonds/prof.cpp can report busy cycles
# per frame by PC range. Needs the source from build.sh; the shared core is untouched.
#   tools/emu/melonds/build_prof.sh   -> work/emu/melonds_prof/prof
#   CAVE=020EEA00:020EFA38 work/emu/melonds_prof/prof ROM "900:4:2,1000:80:120" 880 1200
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; ROOT="$HERE/../../.."
SRC="$ROOT/work/emu/melonds/src"; W="$ROOT/work/emu/melonds_prof"
[[ -d "$SRC" ]] || { echo "run tools/emu/melonds/build.sh first" >&2; exit 1; }
if [[ ! -d "$W/src" ]]; then
    mkdir -p "$W"; cp -r "$SRC" "$W/src"
    python3 - "$W/src/src/ARM.cpp" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
head = "template <CPUExecuteMode mode>\nvoid ARMv5::Execute()\n{"
step = "        NDS.ARM9Timestamp += Cycles;\n        Cycles = 0;"
assert s.count(head) == 1 and step in s, "melonDS ARM.cpp layout changed"
s = s.replace(head, "void (*g_prof_hook)(u32 pc, s32 cycles) = nullptr;\n" + head)
i = s.index(step, s.index(head))          # first step after ARMv5::Execute = the ARM9 interpreter loop
s = s[:i] + "        if (g_prof_hook) g_prof_hook(R[15], Cycles);\n" + s[i:]
open(p, "w").write(s)
PY
fi
cmake -S "$W/src" -B "$W/build" -G Ninja -DBUILD_QT_SDL=OFF -DENABLE_JIT=OFF -DENABLE_OGLRENDERER=OFF \
    -DENABLE_GDBSTUB=OFF -DCMAKE_BUILD_TYPE=Release >/dev/null
ninja -C "$W/build" core >/dev/null
g++ -O2 -std=c++20 -I"$W/src/src" -I"$W/build/src" -I"$W/src/src/teakra/include" "$HERE/prof.cpp" "$HERE/platform.cpp" \
    -o "$W/prof" "$W/build/src/libcore.a" "$W/build/src/teakra/src/libteakra.a" -lpthread -lz
echo "$W/prof"
