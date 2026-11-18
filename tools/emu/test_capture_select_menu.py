"""Menu test for the Capture Select ROM patch (headless DeSmuME + GDB).

Injects keys at the wrapper's `mvn r5, r5` (cave+0x20) on chosen title frames:
SELECT (open menu) -> DOWN x3 -> A (launch). Screenshots are taken while the
emulator is paused, via ImageMagick on the Xvfb display (env DISP, SHOT_DIR).
"""
import gdb, os, subprocess, time
DISP = os.environ.get("DISP", ":99"); SHOT = os.environ.get("SHOT_DIR", "work/emu/menu_shots")
os.makedirs(SHOT, exist_ok=True)
def shot(name): subprocess.run(["import", "-display", DISP, "-window", "root", f"{SHOT}/{name}.png"], check=False)
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def r16(a): return int(gdb.parse_and_eval("*(unsigned short*)0x%x" % a)) & 0xffff
CAPTURE_SHOT_FRAMES = [int(x) for x in os.environ.get("CAPTURE_SHOTS", "300").split(",")]
SETUP = 0x020B797C; HOOK = 0x020EEA20; STATE = SETUP + 0x128
KEYS = {"A": 1, "B": 2, "SELECT": 4, "RIGHT": 0x10, "LEFT": 0x20, "UP": 0x40, "DOWN": 0x80}
plan = {120: "SELECT", 160: "DOWN", 170: "DOWN", 180: "DOWN", 230: "A"}
if os.environ.get("PLAN"):   # e.g. PLAN="120:SELECT,160:DOWN,200:A"
    plan = {int(k): v for k, v in (x.split(":") for x in os.environ["PLAN"].split(","))}
shots = {150: "menu_open", 200: "menu_moved"}
gdb.execute("break *0x0203DEE0")
t0 = time.time(); hook = None; f = 0; st = None
while time.time() - t0 < 200:
    try: gdb.execute("continue", to_string=True)
    except gdb.error as e: print("err", e); break
    pc = reg("pc")
    if pc == 0x0203DEE0:
        sid = reg("r0") & 0xff; print("[scene_create] 0x%02x" % sid, flush=True)
        if sid in (0x25, 0x2C) and hook is None and f < max(plan): hook = gdb.Breakpoint("*0x%x" % HOOK)
        if sid == 0x2C and f >= max(plan):
            print("returned to title scene", flush=True)
            after = gdb.Breakpoint("*0x%x" % HOOK); n_after = 0
            while n_after < 240:
                gdb.execute("continue", to_string=True); n_after += 1
            shot("title_after"); print("title_after screenshot (240 frames later)", flush=True); break
        if sid == 0x02:
            ids = [r16(SETUP + 0xC + 12 * k + 4) for k in range(r32(SETUP))]
            print("  CaptureSetup: count=%d ids=%s bgm=%d arena=0x%x ret=0x%x flags=0x%x s150=%d v154=%d" % (
                r32(SETUP), ids, r16(SETUP + 0x13C), r16(SETUP + 0x13E), r32(SETUP + 0x144),
                r16(SETUP + 0x142), r32(SETUP + 0x150), r16(SETUP + 0x154)), flush=True)
            st = gdb.Breakpoint("*0x020D05C4"); f = 0
    elif hook is not None and pc == HOOK:
        f += 1
        if f in plan:
            gdb.execute("set $r5 = 0x%x" % ((~KEYS[plan[f]]) & 0xffff))
            print("== frame %d: %s  (menu open=%d idx=%d top=%d)" % (f, plan[f], r32(STATE+6) & 0xff, r16(STATE), r16(STATE+2)), flush=True)
        if f in shots:
            print("   DISPCNT_A=%08x VRAMCNT_C=%02x" % (r32(0x04000000), r32(0x04000240) >> 16 & 0xff), flush=True)
            shot(shots[f])
        if f > 240: hook.delete(); hook = None
    elif st is not None and pc == 0x020D05C4:
        f += 1
        if f in CAPTURE_SHOT_FRAMES:
            shot("capture_%d" % f if f != CAPTURE_SHOT_FRAMES[0] else "capture"); print("capture screenshot %d" % f, flush=True)
        if f >= CAPTURE_SHOT_FRAMES[-1]:
            print("capture screenshot taken", flush=True); break
print("done")
