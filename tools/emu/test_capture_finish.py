"""Force a capture launched from the Capture Select menu to WIN and follow it.

1. title: SELECT, A -> capture of menu entry 0 (scripted Pichu event)
2. once the capture runs, map CCaptureScene state numbers (1..12) to classes by
   reading each state singleton's vptr
3. request the CCaptureWinState number, then log every state request and
   scene change for a while, taking screenshots (env SHOT_DIR, DISP)
The result and browser screens wait for a touch, so the script then steps
Result -> AddBrowser -> CheckRelease -> exit (7), running each state's code.
Success = the game reaches the title scene (0x2C) again without hanging.
"""
import gdb, os, subprocess, time
DISP = os.environ.get("DISP", ":99"); SHOT = os.environ.get("SHOT_DIR", "work/emu/finish")
os.makedirs(SHOT, exist_ok=True)
def shot(n): subprocess.run(["import", "-display", DISP, "-window", "root", f"{SHOT}/{n}.png"], check=False)
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
CTX = 0x0211DDE0; HOOK = 0x020EEA20; STATE_SWITCH = 0x020D05C4
SINGLETONS = {1: 0x212250C, 2: 0x2122518, 3: 0x2122524, 4: 0x2122538, 5: 0x2122544, 6: 0x21227EC,
              8: 0x2122498, 9: 0x2122560, 10: 0x2122680, 11: 0x21227AC, 12: 0x2122810}
VT = {0x0211C304: "Normal", 0x0211C344: "Win", 0x0211C384: "Lose", 0x0211C3C8: "Runaway",
      0x0211C40C: "Reward", 0x0211C464: "Result", 0x0211C4D0: "AddBrowser", 0x0211C540: "CheckRelease",
      0x0211C5A8: "Intrusion", 0x0211C5F0: "DataChange"}
plan = {120: 0x004, 170: 0x001}     # SELECT, A
gdb.execute("break *0x0203DEE0")
t0 = time.time(); hook = None; f = 0; st = None; names = {}; forced = False; n_after = 0; last = None
while time.time() - t0 < 240:
    try: gdb.execute("continue", to_string=True)
    except gdb.error as e: print("err", e); break
    pc = reg("pc")
    if pc == 0x0203DEE0:
        sid = reg("r0") & 0xff; print("[scene_create] 0x%02x (t=%.0fs)" % (sid, time.time() - t0), flush=True)
        if sid == 0x25 and hook is None and not forced: hook = gdb.Breakpoint("*0x%x" % HOOK)
        if sid == 0x02: st = gdb.Breakpoint("*0x%x" % STATE_SWITCH)
        if sid == 0x2C and forced:
            print("RETURNED TO TITLE after forced win", flush=True)
            gdb.execute("delete"); hook = gdb.Breakpoint("*0x%x" % HOOK); k = 0
            while k < 200: gdb.execute("continue", to_string=True); k += 1
            shot("title_after"); print("title screenshot", flush=True); break
    elif hook is not None and pc == HOOK:
        f += 1
        if f in plan:
            gdb.execute("set $r5 = 0x%x" % ((~plan[f]) & 0xffff)); print("== key 0x%x" % plan[f], flush=True)
        if f > max(plan): hook.delete(); hook = None
    elif st is not None and pc == STATE_SWITCH:
        req = r32(r32(CTX) + 0x14)
        if req and req != last:
            print("[state request] %d %s" % (req, names.get(req, "")), flush=True); last = req
        if not names and req == 0 and last == 1:
            for k, a in SINGLETONS.items():
                for off in range(0, 0x20, 4):
                    v = r32(a + off)
                    if v in VT: names[k] = VT[v]; break
            print("state map:", names, flush=True)
            n_after = 0
        if names and not forced:
            n_after += 1
            if n_after == 120:
                win = [k for k, v in names.items() if v == "Win"]
                if not win: print("no Win state found"); break
                gdb.execute("set {unsigned int}0x%x = %d" % (r32(CTX) + 0x14, win[0]))
                print("== forced state %d (Win)" % win[0], flush=True); forced = True; shot("forced"); n_after = 0
        elif forced:
            n_after += 1
            # The result/browser screens wait for a touch we can't inject, so step
            # the state machine: Result -> AddBrowser -> CheckRelease -> exit (7).
            for at, nxt in ((300, "AddBrowser"), (600, "CheckRelease"), (900, None)):
                if n_after == at:
                    shot("before_%s" % (nxt or "exit"))
                    num = [k for k, v in names.items() if v == nxt][0] if nxt else 7
                    gdb.execute("set {unsigned int}0x%x = %d" % (r32(CTX) + 0x14, num))
                    print("== forced state %d (%s)" % (num, nxt or "exit"), flush=True)
print("done")
