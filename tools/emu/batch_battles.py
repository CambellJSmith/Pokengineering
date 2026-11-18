"""Launch many Capture Select battles in ONE emulator session (headless DeSmuME + GDB).

Jobs come from a JSON file (env JOBS): [{"idx": menu index, "arena": optional
override, "name": screenshot name}, ...]. For each job:
  1. on a title frame (wrapper hook), make the menu's launch path run for
     entry `idx` (menu state: open=1, index=idx, A pressed);
  2. at scene_create(2), optionally override CaptureSetup+0x13E (arena);
  3. once the capture's normal state is entered (CCaptureNormalState enter,
     ov3 0x020FA7C8), let N frames pass, screenshot, and record success;
  4. force capture state 7 (exit) -> title, next job.
Results: env OUT (JSON lines). Screenshots: env SHOT_DIR/<name>.png (bottom
screen cropped).

  JOBS=jobs.json OUT=res.jsonl SHOT_DIR=shots tools/emu/run_headless.sh \\
      work/capture_select/capture_select.nds tools/emu/batch_battles.py 7200 log.txt
"""
import gdb, json, os, subprocess, time

DISP = os.environ.get("DISP", ":99")
SHOT = os.environ.get("SHOT_DIR", "work/emu/batch")
OUT = os.environ.get("OUT", "work/emu/batch.jsonl")
JOBS = json.load(open(os.environ["JOBS"]))
SETTLE = int(os.environ.get("SETTLE", "90"))       # frames between normal-state enter and screenshot
os.makedirs(SHOT, exist_ok=True)

SETUP = 0x020B797C; STATE = SETUP + 0x128; HOOK = 0x020EEA20
CTX = 0x0211DDE0; NORMAL_ENTER = 0x020FA7C8; STATE_SWITCH = 0x020D05C4; SCENE_CREATE = 0x0203DEE0


def reg(r): return int(gdb.parse_and_eval("$" + r)) & 0xffffffff
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def r16(a): return int(gdb.parse_and_eval("*(unsigned short*)0x%x" % a)) & 0xffff
def w(a, v, t="unsigned int"): gdb.execute("set {%s}0x%x = 0x%x" % (t, a, v))


def shot(name):
    tmp = f"{SHOT}/_full.png"
    subprocess.run(["import", "-display", DISP, "-window", "root", tmp], check=False)
    # bottom screen of the 640x480 window: x 192..448, y 240..432
    subprocess.run(["convert", tmp, "-crop", "256x192+192+240", "+repage", f"{SHOT}/{name}.png"], check=False)


out = open(OUT, "a")
bp_scene = gdb.Breakpoint("*0x%x" % SCENE_CREATE)
hook = None; bp_normal = None; bp_switch = None
job_i = 0; phase = "boot"; t_job = time.time(); frames = 0; result = None
t0 = time.time()
while job_i < len(JOBS):
    try:
        gdb.execute("continue", to_string=True)
    except gdb.error as e:
        print("err", e, flush=True); break
    pc = reg("pc")
    job = JOBS[job_i]
    if pc == SCENE_CREATE:
        sid = reg("r0") & 0xff
        if sid in (0x25, 0x2C) and phase in ("boot", "returning"):
            phase = "title"; frames = 0
            hook = gdb.Breakpoint("*0x%x" % HOOK)
        elif sid == 0x02 and phase == "launched":
            if "arena" in job and job["arena"] is not None:
                w(SETUP + 0x13E, job["arena"], "unsigned short")
            for addr, val, size in job.get("pokes", []):     # experiments: [addr, value, 1|2|4]
                w(addr, val, {1: "unsigned char", 2: "unsigned short", 4: "unsigned int"}[size])
            result = {"idx": job.get("idx"), "name": job["name"], "arena": r16(SETUP + 0x13E),
                      "count": r32(SETUP), "ids": [r16(SETUP + 0x10 + 12 * k) for k in range(min(r32(SETUP), 8))],
                      "ok": False}
            bp_normal = gdb.Breakpoint("*0x%x" % NORMAL_ENTER)
            phase = "capture"; t_job = time.time()
    elif hook is not None and pc == HOOK and phase == "title":
        frames += 1
        if frames == 20:
            # drive the menu's own launch path for entry idx
            w(STATE + 0, job["idx"], "unsigned short"); w(STATE + 2, job["idx"], "unsigned short")
            w(STATE + 4, 0, "unsigned short"); w(STATE + 6, 1, "unsigned char"); w(STATE + 8, 0, "unsigned char")
            gdb.execute("set $r5 = 0x%x" % ((~0x001) & 0xffff))    # A pressed
            hook.delete(); hook = None; phase = "launched"
    elif bp_normal is not None and pc == NORMAL_ENTER and phase == "capture":
        bp_normal.delete(); bp_normal = None
        bp_switch = gdb.Breakpoint("*0x%x" % STATE_SWITCH); frames = 0; phase = "settle"
    elif bp_switch is not None and pc == STATE_SWITCH and phase == "settle":
        frames += 1
        if frames >= SETTLE:
            shot(job["name"]); result["ok"] = True
            result["secs"] = round(time.time() - t_job, 1)
            out.write(json.dumps(result) + "\n"); out.flush()
            print("[%d/%d] %s ok arena=%d ids=%s" % (job_i + 1, len(JOBS), job["name"], result["arena"], result["ids"]), flush=True)
            w(r32(CTX) + 0x14, 7)              # exit -> return scene (title)
            bp_switch.delete(); bp_switch = None
            phase = "returning"; job_i += 1
    # watchdog: a job that never reaches the normal state
    if phase in ("launched", "capture") and time.time() - t_job > 120 and result is not None:
        result["error"] = "timeout before normal state"; out.write(json.dumps(result) + "\n"); out.flush()
        print("[%d/%d] %s TIMEOUT" % (job_i + 1, len(JOBS), job["name"]), flush=True)
        break
print("done %d jobs in %.0fs" % (job_i, time.time() - t0), flush=True)
