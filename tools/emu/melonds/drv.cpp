// melonDS core driver: boot ROM, apply a key plan, dump both screens as PPM.
// usage: drv ROM OUTDIR PLAN   PLAN = "frame:keyhex:holdframes,...;shot,frames,..."
// Keys include X 400, Y 800. env: TOUCH="frame:x:y:hold,..." (stylus on the bottom screen),
// DUMP="frame,..." (main RAM -> OUTDIR/ramNNNNN.bin), POKE="frame:addr:hexval[:size],..."
// (write before that frame), MEM="addr:size,..." (print at every shot frame).
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
using namespace melonDS;
int main(int argc, char** argv) {
    std::ifstream f(argv[1], std::ios::binary); std::vector<char> rom((std::istreambuf_iterator<char>(f)), {});
    auto buf = std::make_unique<u8[]>(rom.size()); memcpy(buf.get(), rom.data(), rom.size());
    NDSArgs args; args.JIT = std::nullopt;
    auto nds = std::make_unique<NDS>(std::move(args));
    nds->SetRenderer(std::make_unique<SoftRenderer>(*nds));
    auto cart = NDSCart::ParseROM(std::move(buf), rom.size());
    if (!cart) { fprintf(stderr, "bad rom\n"); return 1; }
    nds->Reset(); nds->SetNDSCart(std::move(cart)); nds->Reset(); nds->SetupDirectBoot("rom.nds"); nds->Start();
    std::string outdir = argv[2];
    struct K { int f, k, h; }; std::vector<K> keys; std::vector<int> shots; int last = 0;
    std::string plan = argv[3]; auto semi = plan.find(';');
    std::stringstream ks(plan.substr(0, semi)), ss(semi == std::string::npos ? "" : plan.substr(semi + 1)); std::string t;
    while (std::getline(ks, t, ',')) if (!t.empty()) { int a, b, c = 4; sscanf(t.c_str(), "%d:%x:%d", &a, &b, &c); keys.push_back({a, b, c}); if (a + c > last) last = a + c; }
    while (std::getline(ss, t, ',')) if (!t.empty()) { shots.push_back(atoi(t.c_str())); if (shots.back() > last) last = shots.back(); }
    const char* watch = getenv("WATCH");
    struct T { int f, x, y, h; }; std::vector<T> touches;
    if (const char* e = getenv("TOUCH")) { std::stringstream ts(e); while (std::getline(ts, t, ',')) if (!t.empty()) { T v{0, 0, 0, 4}; sscanf(t.c_str(), "%d:%d:%d:%d", &v.f, &v.x, &v.y, &v.h); touches.push_back(v); if (v.f + v.h > last) last = v.f + v.h; } }
    std::vector<int> dumps;
    if (const char* e = getenv("DUMP")) { std::stringstream ds(e); while (std::getline(ds, t, ',')) if (!t.empty()) { dumps.push_back(atoi(t.c_str())); if (dumps.back() > last) last = dumps.back(); } }
    struct P { int f; u32 a, v; int sz; }; std::vector<P> pokes;
    if (const char* e = getenv("POKE")) { std::stringstream ps(e); while (std::getline(ps, t, ',')) if (!t.empty()) { P v{0, 0, 0, 2}; sscanf(t.c_str(), "%d:%x:%x:%d", &v.f, &v.a, &v.v, &v.sz); pokes.push_back(v); } }
    struct M { u32 a; int sz; }; std::vector<M> mems;
    if (const char* e = getenv("MEM")) { std::stringstream ms(e); while (std::getline(ms, t, ',')) if (!t.empty()) { M v{0, 2}; sscanf(t.c_str(), "%x:%d", &v.a, &v.sz); mems.push_back(v); } }
    for (int fr = 1; fr <= last; fr++) {
        u32 pressed = 0; for (auto& k : keys) if (fr >= k.f && fr < k.f + k.h) pressed |= k.k;
        nds->SetKeyMask(0xFFF & ~pressed);
        bool touching = false;
        for (auto& tc : touches) if (fr >= tc.f && fr < tc.f + tc.h) { nds->TouchScreen(tc.x, tc.y); touching = true; }
        if (!touching) nds->ReleaseScreen();
        for (auto& p : pokes) if (p.f == fr) { if (p.sz == 1) nds->ARM9Write8(p.a, p.v); else if (p.sz == 4) nds->ARM9Write32(p.a, p.v); else nds->ARM9Write16(p.a, p.v); }
        if (getenv("EXITCAP") && fr == atoi(getenv("EXITCAP"))) { u32 c = nds->ARM9Read32(0x0211DDE0); printf("force exit ctx=%08x\n", c); nds->ARM9Write32(c + 0x14, 7); }
        nds->RunFrame();
        // Stop on a real exception: the CPU is in abort (0x17) or undefined (0x1B) mode.
        // (Being in BIOS code alone isn't one: IRQ dispatch and SWIs run there too.)
        if (getenv("TRAP") && ((nds->ARM9.CPSR & 0x1F) == 0x17 || (nds->ARM9.CPSR & 0x1F) == 0x1B)) {
            printf("TRAP f%d pc=%08x lr=%08x cpsr=%08x r0-3 %08x %08x %08x %08x r4-7 %08x %08x %08x %08x\n", fr, nds->ARM9.R[15], nds->ARM9.R[14], nds->ARM9.CPSR,
              nds->ARM9.R[0], nds->ARM9.R[1], nds->ARM9.R[2], nds->ARM9.R[3], nds->ARM9.R[4], nds->ARM9.R[5], nds->ARM9.R[6], nds->ARM9.R[7]);
            for (int b = 0; b < 3; b++) printf(" bank%d abt=%08x und=%08x svc=%08x\n", b, nds->ARM9.R_ABT[b], nds->ARM9.R_UND[b], nds->ARM9.R_SVC[b]);
            return 0; }
        for (int d : dumps) if (d == fr) {
            char name[512]; snprintf(name, sizeof name, "%s/ram%05d.bin", outdir.c_str(), fr);
            FILE* o = fopen(name, "wb"); for (u32 a = 0x02000000; a < 0x02400000; a += 4) { u32 w = nds->ARM9Read32(a); fwrite(&w, 4, 1, o); } fclose(o); }
        for (int s : shots) if (s == fr && !mems.empty()) {
            printf("f%d mem", fr); for (auto& m : mems) printf(" %08x=%x", m.a, m.sz == 1 ? nds->ARM9Read8(m.a) : m.sz == 4 ? nds->ARM9Read32(m.a) : nds->ARM9Read16(m.a)); printf("\n"); fflush(stdout); }
        for (int s : shots) if (s == fr) {
            void *top, *bot; nds->GPU.GetFramebuffers(&top, &bot);
            char name[512]; snprintf(name, sizeof name, "%s/f%05d.ppm", outdir.c_str(), fr);
            FILE* o = fopen(name, "wb"); fprintf(o, "P6 256 384 255\n");
            for (u32* p : {(u32*)top, (u32*)bot}) for (int i = 0; i < 256 * 192; i++) { u32 c = p[i]; unsigned char rgb[3] = {(unsigned char)(c >> 16), (unsigned char)(c >> 8), (unsigned char)c}; fwrite(rgb, 1, 3, o); }
            fclose(o);
            if (watch) { printf("f%d pc9=%08x DISPCNT=%08x BG3CNT=%04x VRAMCNT=%08x POWCNT=%04x BRIGHT=%04x state6=%d idx=%d scene_ret=%x\n", fr, nds->ARM9.R[15],
                nds->ARM9Read32(0x04000000), nds->ARM9Read16(0x0400000E), nds->ARM9Read32(0x04000240), nds->ARM9Read16(0x04000304), nds->ARM9Read16(0x0400006C),
                nds->ARM9Read8(0x020B797C + 0x128 + 6), nds->ARM9Read16(0x020B797C + 0x128), nds->ARM9Read32(0x020B797C + 0x144)); fflush(stdout); }
        }
    }
    return 0;
}
