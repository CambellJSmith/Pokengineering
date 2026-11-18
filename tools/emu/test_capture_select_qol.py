"""QOL test for the Capture Select menu (headless DeSmuME + GDB).

SELECT -> START x2 (styler MAX) -> R x2 (jump to the SKY section) -> A, then
check the styler preset in CaptureSetup, force the capture to exit and check
that the menu reopens by itself on the same entry. Screenshots: SHOT_DIR.
"""
import gdb, os, subprocess, time
DISP = os.environ.get("DISP", ":99"); SHOT = os.environ.get("SHOT_DIR", "work/emu/qol")
os.makedirs(SHOT, exist_ok=True)
def shot(n): subprocess.run(["import", "-display", DISP, "-window", "root", f"{SHOT}/{n}.png"], check=False)
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def r16(a): return int(gdb.parse_and_eval("*(unsigned short*)0x%x" % a)) & 0xffff
def regs(tag):
    print("  [%s] DISPCNT_A=%08x DISPCNT_B=%08x POWCNT=%04x VRAMCNT A-I=%s BG3CNT_A=%04x" % (tag, r32(0x04000000), r32(0x04001000),
          r16(0x04000304), " ".join("%02x" % r8(0x04000240 + i) for i in range(10)), r16(0x0400000E)), flush=True)
def r8(a): return int(gdb.parse_and_eval("*(unsigned char*)0x%x" % a)) & 0xff
SETUP = 0x020B797C; STATE = SETUP + 0x128; HOOK = 0x020EEA20; CTX = 0x0211DDE0
KEYS = {"A": 1, "B": 2, "SELECT": 4, "START": 8, "RIGHT": 0x10, "LEFT": 0x20, "UP": 0x40, "DOWN": 0x80, "R": 0x100, "L": 0x200}
plan = {120: "SELECT", 140: "START", 150: "START", 160: "R", 170: "R", 200: "A"}
shots = {130: "menu_open", 190: "menu_sky_max"}
gdb.execute("break *0x0203DEE0")
t0 = time.time(); hook = None; f = 0; phase = "title"; st = None; n = 0
while time.time() - t0 < 200:
    try: gdb.execute("continue", to_string=True)
    except gdb.error as e: print("err", e); break
    pc = reg("pc")
    if pc == 0x0203DEE0:
        sid = reg("r0") & 0xff; print("[scene_create] 0x%02x" % sid, flush=True)
        if sid in (0x25, 0x2C) and hook is None: hook = gdb.Breakpoint("*0x%x" % HOOK)
        if sid == 0x02:
            print("  CaptureSetup: ids=%s level(+0x6C)=%d energy(+0x75/76)=%d/%d ret=0x%x reopen=%d idx=%d" % (
                [r16(SETUP + 0x10 + 12 * k) for k in range(r32(SETUP))], r32(SETUP + 0x6C),
                r8(SETUP + 0x75), r8(SETUP + 0x76), r32(SETUP + 0x144), r8(STATE + 10), r16(STATE)), flush=True)
            st = gdb.Breakpoint("*0x020D05C4"); phase = "capture"; n = 0
        if sid == 0x2C and phase == "exited":
            phase = "after"; f = 0
    elif hook is not None and pc == HOOK:
        f += 1
        if phase == "title":
            if f in plan:
                gdb.execute("set $r5 = 0x%x" % ((~KEYS[plan[f]]) & 0xffff))
                print("== %s (open=%d idx=%d styler=%d)" % (plan[f], r8(STATE + 6), r16(STATE), r8(STATE + 11)), flush=True)
            if f in shots: shot(shots[f]); regs(shots[f])
            if f > max(plan): hook.delete(); hook = None
        elif phase == "after" and f == 60:
            print("after battle: menu open=%d idx=%d styler=%d" % (r8(STATE + 6), r16(STATE), r8(STATE + 11)), flush=True)
            shot("menu_reopened"); regs("reopened"); break
    elif st is not None and pc == 0x020D05C4:
        n += 1
        if n == 150:
            shot("capture")
            gdb.execute("set {unsigned int}0x%x = 7" % (r32(CTX) + 0x14))
            print("== forced exit", flush=True); st.delete(); st = None; phase = "exited"
print("done")
