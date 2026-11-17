# Scene system and the ordinary capture route (static analysis, 2026-11-17)

This document records the static reverse-engineering that resolved the
"ordinary overworld encounter → normal capture launcher → `CCaptureScene`"
question left open in the 2026-10-04 handoff.

Everything here is from static analysis of the decompressed ARM9 and decoded
overlays. Items marked **(dynamic: TODO)** still need one clean GDB trace using
`tools/gdb/ordinary_capture_trace.gdb`.

## 0. Prerequisite discovery: `arm9.bin` is BLZ-compressed

The resident ARM9 image is itself Nitro code-compressed. Its module params
(file `+0xBA0`, magic `0xDEC00621 0x2106C0DE`) say:

```text
autoload list          0x020AA880-0x020AA898
autoload_start         0x020AA0A0
static BSS             0x020AA0A0-0x020D00C0
compressed_static_end  0x02066C94
```

That's why "live ARM9 did not match `arm9.bin`" (README section 7). Decompress
with:

```bash
bash tools/analyze_game_code.sh        # overlays (if not done yet)
python3 tools/decompress_arm9.py       # -> work/code_analysis/runtime/arm9_decompressed.bin
```

The result maps 1:1 onto RAM `0x02000000-0x020AA898`. The script VM interpreter
prologue at `0x02065A80` checks out. All the capture-transition globals below
(`0x020B7xxx`, `0x020BDxxx`) are in **static BSS**, so they're resident and
survive overlay swaps.

## 1. RTTI: 460 classes recovered

`tools/rtti_hierarchy.py [regex]` scans ARM9 and every overlay (each at its own
base, never merged) for CodeWarrior type_info objects
`{tinfo_vptr, "NNName", base_tinfo*}` and their vtables
`{0, type_info*, fn0, fn1, ...}`. The object vptr points to `fn0`.

A full dump is in `research/code/rtti_classes.txt`. The capture-relevant
hierarchy:

```text
CScene (ARM9 0x020A2728)
 ├─ CFieldScene             ov2   (scene 1)
 ├─ CCaptureScene           ov3   (scene 2)   vptr 0x0211A7A8
 ├─ CBossProduceScene       ov22  (scene 0x29) transition into capture
 ├─ CSkyScene / CSkyGameScene ov3 (scenes 0x17 / 0x18)
 ├─ CCaptureToFieldScene(P) ARM9  (scene 0x1B) return to field
 └─ CSkyToFieldScene        ARM9  (scene 0x1A)

CFieldState (ov2)
 ├─ CFieldToCaptureState    ov2  vptr 0x02121014   <- field state 3
 │   └─ CFieldToCaptureStateP    vptr 0x02121034   (CFieldContextP variant)
 ├─ CFieldToFreeSkyState / CFieldToEventSkyState
 └─ ...

CCaptureContext (ov3, vptr 0x0211AA30)
 ├─ CSkyCaptureContext      ov3
 └─ CCommuCaptureContext    ov3 (multiplayer)
CCaptureState (ov3): Normal, Win, Lose, Runaway, Reward, Result,
                     AddBrowser, CheckRelease, Intrusion, DataChange
CFieldWildPokemon : CFieldPokemon (ov2), CFieldWildPokemonManage
```

## 2. Scene table (scene ID → overlay → class)

The resident scene manager is initialized with two callbacks (`0x02000D0C`):

| function | role |
|---|---|
| `0x0203D9BC` | `scene_overlay(sceneId)`: switch → `0x0203E714(overlayId)` which calls `FS_UnloadOverlay 0x0207DFD0` and `FS_LoadOverlay 0x0207DF7C` |
| `0x0203DEE0` | `scene_create(sceneId)`: switch → `operator new(size)` `0x02001164` + constructor at a fixed address inside the freshly loaded overlay |

Every `CScene` subclass returns its own ID from **vtable slot 13**
(`mov r0,#id; bx lr`). **Slot 2** is `Update()`, which returns the next scene ID
(`-2` = stay). `tools/scene_map.py` joins all three sources. Output is in
`research/capture/scene_table.csv`.

Capture-relevant rows:

| ID | overlay | ctor | class |
|---|---|---|---|
| `0x01` | 2 | `0x020D1BB0` | `CFieldScene` |
| `0x02` | 3 | `0x020D013C` | `CCaptureScene` |
| `0x04` | 3 | `0x020FE4A4` | `CCommuCaptureScene` |
| `0x17` | 3 | `0x020FFDB4` | `CSkyScene` |
| `0x18` | 3 | `0x021179F0` | `CSkyGameScene` |
| `0x1A` | — | (ARM9) | `CSkyToFieldScene` |
| `0x1B` | — | (ARM9) | `CCaptureToFieldScene` |
| `0x29` | 22 | `0x020D00C0` | `CBossProduceScene` |

So `0x020D012C`, tried in October as the `CCaptureScene` ctor, is actually the
*base-class* ctor that derived scenes call (e.g. `CCommuCaptureScene`
`0x020FE4A4`). The real `CCaptureScene` ctor is `0x020D013C`, called from
ARM9 `0x0203E024`.

**Overlay 2 (field, `0x020D1B80-0x0212CFC0`) and overlay 3 (capture/sky,
`0x020D00C0-0x02126AC0`) overlap**, as does ov22. A field→capture transition
unloads ov2 and loads ov22, then ov3. Any software breakpoint in that RAM gets
overwritten, which explains the inconclusive 2026-10-04 sweep.

## 3. The ordinary capture chain

```text
CFieldScene (scene 1, ov2)
  field context +0x1F18 = pending field state, +0x1F14 = current
  state resolver  vfunc +0x38 = ov2 0x020D8404 (P variant 0x020DA770)
     state 3 -> CFieldToCaptureState singleton 0x02128AE0 (P: 0x02128AE8)
        |
        v
CFieldToCaptureState::Enter  ov2 0x020DF760
  - fills resident transition block 0x020B7A7C (+0x3C = 0x020B7AB8 "capture request")
      req+0x08 (u32) = 0x1B   return scene = CCaptureToFieldScene
      req+0x02 (u16) = arena/BG id (if 0xFFFF: field ctx vfunc +0x50)
      req+0x0C, +0x10 = area-kind flags (field ctx +0x22B8: 1/7/10)
  - copies player/styler stats from save (0x020BD32C) to 0x020B79E8
CFieldToCaptureState::Update ov2 0x020DFA70
  - field ctx +0x1F2C (next scene) = 0x29 if not already set
        |
        v
scene 0x29 CBossProduceScene (ov22) - transition animation
  Update 0x020D068C ... returns 2 (0x020D096C)
        |
        v
scene 2 CCaptureScene (ov3)
  CCaptureContext::Init ov3 0x020D1D38
    - registers script VM command groups 8, 7 (0x0211C9C8 capture cmds), 15, 13
    - req+0x00 (u16) selects capture BGM via 0x020D351C (0..10)
  CCaptureScene state machine ov3 0x020D05C4, capture ctx 0x0211DDE0:
    states 1..12 -> CCaptureState singletons 0x0212250C..0x02122810
    state 7 = exit: next scene = req+0x08 (0x1B)
        |
        v
scene 0x1B CCaptureToFieldScene (ARM9) -> scene 1
```

The sky route uses the same request block: `CSkyCaptureBeforeState` at
`0x02106A08` resets `req+0/+4/+6/+0x14 = 0`, `+0xC = 1`, `+0x18 = 1`,
`+2 = 0xFFFF`, and ORs `req+6 |= 1`.

`0x020B7C78` and `0x020B7CA4` are resident wrappers around loaded data tables
(resource IDs `0x1ABE` …), accessed through `0x02041F5C` → `0x02022754`
(array getter). `0x020B7C78` is indexed by species. These tables will matter
for the capture *definition* database.

`LoadCapturePokemon 0x02117258` is a **resource preloader**: it takes a list of
`{resId, -1, 0x4C}` entries, where `resId = 0x6B7 + speciesRecord.field_C`, and
loads them into actor-data manager `0x0211E4DC`. It doesn't choose the target.

## 4. Still open

1. **Which resident structure carries the target Pokémon list** from the
   field (ov2 `CFieldWildPokemon`) into `CCapturePokemonManage` (ov3).
   Candidates: the transition block `0x020B7A7C` (field writes
   `+0x3C/+0x3E/+0x40/+0x42/+0x54/+0x56`, ov3 reads `+0x3C/+0x42`),
   `0x020B797C`, and `0x020B7954` (an ARM9 manager the field calls through its
   vtable at ov2 `0x020D8388`). **(dynamic: TODO)**
2. Who sets field pending state 3 (no direct `str` to `+0x1F18` outside init).
   Break at ov2 `0x020D34C8`, where pending state is applied, with
   `r5 == 3` and look at the field state that ran just before. **(dynamic: TODO)**
3. Label states 1..12 of `CCaptureScene` (only Result/AddBrowser/
   CheckRelease are confirmed through static initializers so far).

## 5. Breakpoints that are now safe

These are in resident ARM9 and can never be overwritten by an overlay load:

| address | meaning | notes |
|---|---|---|
| `0x0203D9BC` | scene_overlay(sceneId) | `r0` = scene |
| `0x0207DF7C` | FS_LoadOverlay(0, id) | `r1` = overlay |
| `0x0203DEE0` | scene_create(sceneId) | the scene's overlay **is resident** here, so it's the right moment to arm overlay breakpoints |

`tools/gdb/ordinary_capture_trace.gdb` sets these, logs the scene/overlay
sequence, and dumps `0x020B7A7C`/`0x020B79E8` at every scene creation.

## 6. Consequence for Capture Select

A main-menu "Capture Select" can work at the **scene level**:

1. fill the resident request block `0x020B7AB8` (BGM, arena, return scene
   = the menu's scene) plus whatever target list item 4.1 identifies;
2. return scene `0x29` (with transition) or `2` (direct) from the menu scene's
   `Update()`.

The resident scene manager then loads ov3 and builds `CCaptureScene`
normally. Nothing has to jump into the middle of the capture minigame.
