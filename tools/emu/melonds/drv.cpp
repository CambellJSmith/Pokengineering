// melonDS core driver: boot ROM, apply a key plan, dump both screens as PPM.
// usage: drv ROM OUTDIR PLAN   PLAN = "frame:keyhex:holdframes,...;shot,frames,..."
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
    for (int fr = 1; fr <= last; fr++) {
        u32 pressed = 0; for (auto& k : keys) if (fr >= k.f && fr < k.f + k.h) pressed |= k.k;
        nds->SetKeyMask(0xFFF & ~pressed);
        if (getenv("EXITCAP") && fr == atoi(getenv("EXITCAP"))) { u32 c = nds->ARM9Read32(0x0211DDE0); printf("force exit ctx=%08x\n", c); nds->ARM9Write32(c + 0x14, 7); }
        nds->RunFrame();
        if (getenv("TRAP") && nds->ARM9.R[15] >= 0xFFFF0000) {
            printf("TRAP f%d pc=%08x lr=%08x cpsr=%08x r0-3 %08x %08x %08x %08x r4-7 %08x %08x %08x %08x\n", fr, nds->ARM9.R[15], nds->ARM9.R[14], nds->ARM9.CPSR,
              nds->ARM9.R[0], nds->ARM9.R[1], nds->ARM9.R[2], nds->ARM9.R[3], nds->ARM9.R[4], nds->ARM9.R[5], nds->ARM9.R[6], nds->ARM9.R[7]);
            for (int b = 0; b < 3; b++) printf(" bank%d abt=%08x und=%08x svc=%08x\n", b, nds->ARM9.R_ABT[b], nds->ARM9.R_UND[b], nds->ARM9.R_SVC[b]);
            return 0; }
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
