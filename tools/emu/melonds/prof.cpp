// melonDS profiling driver: ARM9 busy (non-halted) cycles per frame, split by PC range.
// Build with tools/emu/melonds/build_prof.sh. usage: prof ROM PLAN [from to]
//   PLAN = "frame:keyhex:hold,..."; env CAVE=lo:hi (hex PC range to count separately), HIST=1 (hot 64-byte blocks)
#include "NDS.h"
#include "NDSCart.h"
#include "GPU_Soft.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <memory>
#include <map>
#include <algorithm>
using namespace melonDS;
namespace melonDS { extern void (*g_prof_hook)(u32 pc, s32 cycles); }
static u64 busy, cave, other_ov28, arm9res; static u32 clo, chi;
static std::map<u32,u64>* hist;  // 64-byte buckets within the cave
static void hook(u32 pc, s32 c) {
    busy += c;
    if (pc >= clo && pc < chi) { cave += c; if (hist) (*hist)[(pc - clo) & ~0x3Fu] += c; }
    else if (pc < 0x020AA898) arm9res += c;
    else other_ov28 += c;
}
int main(int argc, char** argv) {
    std::ifstream f(argv[1], std::ios::binary); std::vector<char> rom((std::istreambuf_iterator<char>(f)), {});
    auto buf = std::make_unique<u8[]>(rom.size()); memcpy(buf.get(), rom.data(), rom.size());
    NDSArgs args; args.JIT = std::nullopt;
    auto nds = std::make_unique<NDS>(std::move(args));
    nds->SetRenderer(std::make_unique<SoftRenderer>(*nds));
    auto cart = NDSCart::ParseROM(std::move(buf), rom.size());
    nds->Reset(); nds->SetNDSCart(std::move(cart)); nds->Reset(); nds->SetupDirectBoot("rom.nds"); nds->Start();
    sscanf(getenv("CAVE"), "%x:%x", &clo, &chi);
    struct K { int f, k, h; }; std::vector<K> keys; int last = 0;
    std::stringstream ks(argv[2]); std::string t;
    while (std::getline(ks, t, ',')) if (!t.empty()) { int a, b, c = 4; sscanf(t.c_str(), "%d:%x:%d", &a, &b, &c); keys.push_back({a, b, c}); if (a + c > last) last = a + c; }
    int from = argc > 3 ? atoi(argv[3]) : 0, to = argc > 4 ? atoi(argv[4]) : last + 60; if (to > last) last = to;
    const double FRAME = 560190.0 * 2;   // ARM9 cycles per 60 Hz frame
    if (getenv("HIST")) hist = new std::map<u32,u64>;
    g_prof_hook = hook;
    for (int fr = 1; fr <= last; fr++) {
        u32 pressed = 0; for (auto& k : keys) if (fr >= k.f && fr < k.f + k.h) pressed |= k.k;
        nds->SetKeyMask(0xFFF & ~pressed);
        busy = cave = other_ov28 = arm9res = 0;
        nds->RunFrame();
        if (nds->ARM9.R[15] >= 0xFFFF0000) { printf("TRAP f%d lr=%08x\n", fr, nds->ARM9.R[14]); return 1; }
        if (fr >= from && fr <= to)
            printf("f%d keys=%03x busy=%5.1f%% cave=%5.1f%% arm9=%5.1f%% ov=%5.1f%% open=%d idx=%d\n", fr, pressed, busy*100/FRAME, cave*100/FRAME,
                   arm9res*100/FRAME, other_ov28*100/FRAME, nds->ARM9Read8(0x020B797C + 0x128 + 6), nds->ARM9Read16(0x020B797C + 0x128));
    }
    if (hist) { std::vector<std::pair<u64,u32>> v; for (auto& [a, c] : *hist) v.push_back({c, a}); std::sort(v.rbegin(), v.rend());
        for (int i = 0; i < 25 && i < (int)v.size(); i++) printf("hot %08x %llu\n", clo + v[i].second, (unsigned long long)v[i].first); }
    return 0;
}
