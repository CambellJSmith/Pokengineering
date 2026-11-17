"""Test the Capture Select ROM patch headlessly.

Boots the PATCHED ROM, waits for the title/demo scene, then for one frame makes
the wrapper (ov28 cave) read KEYINPUT as "SELECT pressed" (optionally with L/R
via env KEYS=select|l|r) by editing r5 just before `mvn r5, r5` at 0x020EEA14.
Logs the scene sequence, the CaptureSetup the patch wrote and capture states.

  SHOT_EVERY=4 tools/emu/run_headless.sh work/capture_select/capture_select.nds \\
      tools/emu/test_capture_select_rom.py 120 work/emu/csel.log work/emu/csel_shots
"""
import gdb, os, time
KEYS = os.environ.get("KEYS", "select")
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def r16(a): return int(gdb.parse_and_eval("*(unsigned short*)0x%x" % a)) & 0xffff
SETUP = 0x020B797C
pressed = 0x004 | (0x200 if "l" in KEYS.split("|") else 0) | (0x100 if "r" in KEYS.split("|") else 0)
gdb.execute("break *0x0203DEE0")
gdb.execute("break *0x0207DF7C")
t0 = time.time(); hook = None; frames = 0; st = None; states = []
while time.time() - t0 < 100:
    try: gdb.execute("continue", to_string=True)
    except gdb.error as e: print("err", e); break
    pc = reg("pc")
    if pc == 0x0203DEE0:
        sid = reg("r0") & 0xff; print("[scene_create] 0x%02x" % sid, flush=True)
        if sid == 0x25 and hook is None:
            hook = gdb.Breakpoint("*0x020EEA14")
        if sid == 0x02:
            print("  CaptureSetup: count=%d id=%d bgm=%d arena=0x%x ret=0x%x idx_next=%d" % (
                r32(SETUP), r16(SETUP+0x10), r16(SETUP+0x13C), r16(SETUP+0x13E), r32(SETUP+0x144), r32(SETUP+0x60)), flush=True)
            st = gdb.Breakpoint("*0x020D05C4")
    elif pc == 0x0207DF7C:
        print("[load_overlay] %d" % (reg("r1") & 0xff), flush=True)
    elif hook is not None and pc == 0x020EEA14:
        frames += 1
        if frames == 180:
            gdb.execute("set $r5 = 0x%x" % ((~pressed) & 0x3ff))
            print("== injected keys %s on frame %d" % (KEYS, frames), flush=True)
            hook.delete(); hook = None
    elif st is not None and pc == 0x020D05C4:
        s = r32(r32(0x0211DDE0) + 0x14)
        if not states or states[-1] != s:
            states.append(s); print("[capture state request] %d" % s, flush=True)
        if 1 in states:
            print("capture running; free-running", flush=True)
            gdb.execute("delete")
            try: gdb.execute("continue")
            except gdb.error as e: print("err", e)
            break
