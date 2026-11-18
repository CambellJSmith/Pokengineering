"""Capture Select proof of concept, driven through DeSmuME's ARM9 GDB stub.

Boots to the title/demo scene (0x25, overlay 28), waits ~180 frames, then does
in RAM exactly what the field scripts do for a capture:
  CaptureSetup_Clear + CaptureSetup_Add(0x020B797C, RANGER_ID) and
  return scene (setup+0x144) = 0x25,
and forces the current scene's Update() (ov28 0x020D20A4, return to caller)
to return scene 2 (CCaptureScene). The resident scene manager then loads
overlay 3 and builds the capture normally.

Run (headless):
  RANGER_ID=13 SHOT_EVERY=4 tools/emu/run_headless.sh work/debug/guardian_signs_debug.nds \
      tools/emu/capture_select_poc.py 150 work/emu/poc.log work/emu/shots
"""
import os
RANGER_ID = int(os.environ.get("RANGER_ID", "13"), 0)
RETURN_SCENE = int(os.environ.get("RETURN_SCENE", "0x25"), 0)
SCRIPT_150 = int(os.environ.get("SCRIPT_150", "0"), 0)
COUNT = int(os.environ.get("COUNT", "1"), 0)
import gdb, time
def reg(r): return int(gdb.parse_and_eval("$"+r)) & 0xffffffff
def w32(a,v): gdb.execute("set {unsigned int}0x%x = 0x%x" % (a, v & 0xffffffff))
def w16(a,v): gdb.execute("set {unsigned short}0x%x = 0x%x" % (a, v & 0xffff))
def w8(a,v):  gdb.execute("set {unsigned char}0x%x = 0x%x" % (a, v & 0xff))
def r32(a): return int(gdb.parse_and_eval("*(unsigned int*)0x%x" % a)) & 0xffffffff
def cont():
    gdb.execute("continue", to_string=True); return reg("pc")
SETUP=0x020B797C
def capture_setup(rid, ret_scene):
    # == CaptureSetup_Clear (ARM9 0x020418D4) ==
    w32(SETUP,0); w32(SETUP+4,1); w8(SETUP+8,0)
    w16(SETUP+0x13C,0); w16(SETUP+0x13E,0xFFFF); w16(SETUP+0x140,0); w16(SETUP+0x142,0)
    w32(SETUP+0x148,1); w32(SETUP+0x150,0); w16(SETUP+0x154,1); w32(SETUP+0x15C,0); w32(SETUP+0x144,1)
    for k in range(4):
        b=SETUP+0x34*k
        w8(b+0x74,1); w32(b+0x6C,1); w16(b+0x70,10); w8(b+0x75,10); w8(b+0x76,10)
        w16(b+0x8A,0); w8(b+0x85,0); w8(b+0x86,0); w8(b+0x87,0xFF); w8(b+0x88,0xFF); w8(b+0x89,0)
        w8(b+0x77,0); w8(b+0x78,15); w16(b+0x72,0x1C0)
        for j in range(7): w8(b+0x7D+j,0)
    # == CaptureSetup_Add(setup, rid, 0, 0, 0) ==
    w32(SETUP,1); e=SETUP+0xC; w32(e,0); w16(e+4,rid); w16(e+6,0); w16(e+8,0)
    # return scene (request+8 = setup+0x144)
    w32(SETUP+0x144, ret_scene)
    w32(SETUP, COUNT)
    w32(SETUP+0x150, SCRIPT_150)

gdb.execute("break *0x0203DEE0")   # scene_create
gdb.execute("break *0x0207DF7C")   # FS_LoadOverlay
t0=time.time(); stage=0; upd_bp=None; ret_bp=None; frames=0; ctx_bp=None; st_bp=None; states=[]
while time.time()-t0 < 150:
    try: pc=cont()
    except gdb.error as e: print("err",e); break
    if pc==0x0203DEE0:
        sid=reg("r0")&0xff; print("[scene_create] 0x%02x"%sid, flush=True)
        if sid==0x25 and stage==0:
            upd_bp=gdb.Breakpoint("*0x020D20A4"); stage=1
        if sid==0x02:
            ctx_bp=gdb.Breakpoint("*0x020D1D38"); st_bp=gdb.Breakpoint("*0x020D05C4")
            print("  setup:",hex(r32(SETUP)),hex(r32(SETUP+0xC+4)&0xffff),"ret",hex(r32(SETUP+0x144)),flush=True)
    elif pc==0x0207DF7C:
        print("[load_overlay] %d"%(reg("r1")&0xff), flush=True)
    elif upd_bp and pc==0x020D20A4 and stage==1:
        lr=reg("lr"); print("Update caller lr=0x%08x"%lr, flush=True)
        upd_bp.delete(); upd_bp=None
        ret_bp=gdb.Breakpoint("*0x%x"%lr); stage=2
    elif ret_bp and stage==2 and pc==int(ret_bp.location[1:],0):
        frames+=1
        if frames==180:
            capture_setup(RANGER_ID, RETURN_SCENE)
            gdb.execute("set $r0 = 2")
            print("== forced Update() -> 2 with CaptureSetup(ranger id=%d) after %d frames"%(RANGER_ID,frames), flush=True)
            ret_bp.delete(); ret_bp=None; stage=3
    elif ctx_bp and pc==0x020D1D38:
        print("[CCaptureContext::Init] this=0x%08x"%reg("r0"), flush=True)
    elif st_bp and pc==0x020D05C4:
        s=r32(r32(0x0211DDE0)+0x14)
        if not states or states[-1]!=s:
            states.append(s); print("[capture state request] %d"%s, flush=True)
        if 1 in states:
            print("capture running; removing breakpoints and running freely", flush=True)
            gdb.execute("delete")
            try: gdb.execute("continue")
            except gdb.error as e: print("err",e)
            break
print("done; capture states:",states)
