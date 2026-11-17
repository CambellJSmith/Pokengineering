"""Loop test for the Capture Select ROM patch.

1. title: inject SELECT -> capture of list[0]
2. once the capture runs, force its exit state (7) -> expect return to scene 0x2C
3. title again: inject R+SELECT -> expect list[10] (index persisted, +9 skip)
"""
import gdb, time
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def r16(a): return int(gdb.parse_and_eval("*(unsigned short*)0x%x" % a)) & 0xffff
SETUP = 0x020B797C
plan = [0x004, 0x104]          # SELECT, then R+SELECT
gdb.execute("break *0x0203DEE0"); gdb.execute("break *0x0207DF7C")
t0 = time.time(); hook = None; frames = 0; st = None; step = 0; captures = 0; forced = False
while time.time() - t0 < 160:
    try: gdb.execute("continue", to_string=True)
    except gdb.error as e: print("err", e); break
    pc = reg("pc")
    if pc == 0x0203DEE0:
        sid = reg("r0") & 0xff; print("[scene_create] 0x%02x" % sid, flush=True)
        if sid in (0x25, 0x2C) and step < len(plan) and hook is None:
            hook = gdb.Breakpoint("*0x020EEA14"); frames = 0
        if sid == 0x02:
            captures += 1
            print("  CaptureSetup: id=%d bgm=%d arena=0x%x ret=0x%x idx_next=%d" % (
                r16(SETUP+0x10), r16(SETUP+0x13C), r16(SETUP+0x13E), r32(SETUP+0x144), r32(SETUP+0x60)), flush=True)
            st = gdb.Breakpoint("*0x020D05C4"); forced = False
            if captures == 2: break
    elif pc == 0x0207DF7C:
        print("[load_overlay] %d" % (reg("r1") & 0xff), flush=True)
    elif hook is not None and pc == 0x020EEA14:
        frames += 1
        if frames == 120:
            gdb.execute("set $r5 = 0x%x" % ((~plan[step]) & 0x3ff))
            print("== injected keys 0x%03x" % plan[step], flush=True)
            step += 1; hook.delete(); hook = None
    elif st is not None and pc == 0x020D05C4:
        frames += 1
        if not forced and frames > 200:
            ctx = r32(0x0211DDE0)
            gdb.execute("set {unsigned int}0x%x = 7" % (ctx + 0x14))
            print("== forced capture exit state 7", flush=True)
            forced = True; st.delete(); st = None
print("done")
