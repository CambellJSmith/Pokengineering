# Scene system and the ordinary capture route (static analysis, 2026-11-17)

> Summary: every field capture fills the resident `CaptureSetup` at
> `0x020B797C`, runs script `sToCapture`, which sets field state 3, then
> goes through scene `0x29` → scene `2`. Sections 4–5 have the details.
> Wild placements per map are decoded in section 6.

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

## 4. Capture setup struct `0x020B797C` (resident BSS) — solved

`CCaptureContext::Init` builds the capture Pokémon array with
`__construct_new_array(count = [0x020B797C], 0x3FF8, ctor 0x020EE5D4)`, so this
struct is what carries the targets across the ov2 → ov22 → ov3 swap.

```text
0x020B797C  CaptureSetup
  +0x000 u32   count                         (0 is treated as 1)
  +0x004 u32   = 1
  +0x008 u8
  +0x00C entry[count], stride 0xC:
         +0 u32  a        (wild: CFieldWildPokemon+0x08)
         +4 u16  rangerId   Ranger Pokemon ID (section 6c; NOT a Dex number)
         +6 u16  b        (wild: kind from +0x85F, 2 if a save flag is set)
         +8 u16  c
  +0x06C 4 x 0x34-byte player/styler records (copied from save 0x020BD32C)
  +0x13C u16   BGM kind 0..10                 (= "request block" 0x020B7AB8)
  +0x13E u16   arena/BG (0xFFFF -> field picks one)
  +0x140 u16
  +0x142 u16   flags (bit0, bit1, bit2 set by script commands; ov3 reads)
  +0x144 u32   return scene ID (= request+8, 0x020B7AC0): Clear sets 1,
               CFieldToCaptureState sets 0x1B (CCaptureToFieldScene)
  +0x148 u32 = 1, +0x14C u8, +0x150 u32
  +0x154 u16, +0x156 u16
  +0x15C u32   capture result (read back by script command 0x0CAF)
```

The ARM9 API (all resident):

| address | function |
|---|---|
| `0x020418D4` | `CaptureSetup_Clear(setup)` |
| `0x02041998` | `CaptureSetup_Add(setup, pokemonId, u32 a, u16 b, u16 c)` |
| `0x020419D0` | `CaptureSetup_Add(setup, pokemonId, b)` |

ov3 reads `entry.pokemonId` at `0x020D22CC` and maps it through the species
data table `0x020B7C78` (`record+0xE`, `record+0xC` → actor resource
`0x6B7 + n`).

## 5. What actually triggers a field capture — solved

Field state machine (ov2): context pointer `*0x021260E0`, current state
`+0x1F14`, pending state `+0x1F18`, resolver vfunc `+0x38` = `0x020D8404`.

| field state | singleton | class |
|---|---|---|
| 3 | `0x02128AE0` | `CFieldToCaptureState` (P variant `0x02128AE8`) |
| 7 | `0x02128C10` | `CFieldAuthoringEventState` (event/cutscene runner) |

There are two entry points, and both converge on the same common script function:

```text
A) WILD CONTACT  ov2 0x020D5780 (inside field update 0x020D51AC)
   when ctx+0x1F24 bit1 && current state == 1 && no pending state
        && ctx+0x1F28 = touched CFieldWildPokemon:
     CaptureSetup_Clear; CaptureSetup_Add(wild+0x85C dex, wild+0x08, kind)
     play SE 0x55/0x54, queue script "sToCapture", pending state = 7

B) SCRIPTED      field VM group 3 (table ov2 0x02125860):
     0x0CA2 CAP_CLEAR, 0x0CA5/0x0CA6 CAP_ADD, 0x0CA7 BGM, 0x0CB0 arena, ...
     0x0CAD/0x0CAE CAP_START -> CFieldAuthoringEventState +0xCC = 0xC
       -> mode 0xC: play SE 0x55/0x54, run script "sToCapture", mode 7

sToCapture  (common field script, ACF +0xF2934, symbol table at +0x915C)
     wait; fade 0x0C90(0,1,30) x2; wait on 0x0C92; CALL 0x102E; return
0x102E  (group 4 table ov2 0x02125D3C index 0x2E, handler 0x0211D5F0)
     [*0x021260E0 + 0x1F18] = 3        <- the ONLY single-player state-3 writer
        -> CFieldToCaptureState -> scene 0x29 -> scene 2 (see section 3)
```

### Script symbol tables

Scripts carry a symbol table at `[hdr+4, hdr+8)`: 12-byte entries
`{u32 name0, u32 name1, u32 addr/4}`. Names are base 40, six characters per
word (`0-9`=1..10, letters=11..36 case-insensitive, `_`=37, `-`=38, `/`=39),
as packed by ARM9 `0x020667E0`. This is how `sToCapture` was located.
`tools/analyze_field_captures.py` uses it to label every capture with its
enclosing script function (e.g. `M02_00_BT473`, `MQ01_EV002_0`).

### Field capture sweep

```bash
bash tools/setup_guardian_tools.sh && bash tools/extract_localization.sh   # optional: names
python3 tools/analyze_field_captures.py
```

Result: **60 scripts, 164 setup sequences, 158 of which end in CAP_START**.
CSVs go to `research/capture/generated/field_capture_{calls,sequences}.csv`, and
a snapshot is tracked at `research/capture/field_capture_sequences_2026-11-17.csv`.
Targets are Ranger IDs, named via section 6c: for example `M02_00_BT473`
Mamoswine, `BT157` Typhlosion, `BT160` Feraligatr, `BT245` Suicune and
`BT131` Lapras, plus multi-target captures such as six Sunkern in
`MQ01_EV002_0`. The `BTnnn` number in an event label is the target's
National Dex number (24 of 24 labels match), which independently confirms the
ID→Dex mapping.

## 6. Free-roaming wild spawns — solved (statically)

Map placement packages are NARCs in `data_game_us.acf`, one per map variant
(entries 7341–8130). The ARM9 loader is `0x0203F8F4`, which mounts them as `"MPK"`, `"MLY"` and `"MLG"`
(these are archive mount names, not on-disk magics):

```text
NARC  ->  file "MPIF" (20-byte map info) + file "LYR\0"+NARC
            -> NARC[0] -> NARC of layers: {u32 type, u32 count, records}
layer types (CMapPlacementDataLayer*, vfunc0 = type; factory 0x0203FB18):
  1 Enemy  2 Npc  3 Object  4 EventRect  5 StartPoint  6 RunawayPoint
  8 FloorAttribute  9 WallAttribute  10 Shadow
Enemy record, 26 bytes on disk (descriptor 0x0209C370, unpacker 0x0203F5B8
-> 0x1E-byte runtime record):
  s16 x, s16 z, u8 f2, u8 f3, u16 rangerId, u16 f5, u16 f8..f15
```

The field spawns them in ov2 `0x020D6EC8`/`0x020D741C`, which store
`record.rangerId` at `CFieldWildPokemon+0x85C` and the `FPKD` record at
`+0x838`. Wild contact passes `+0x85C` to `CaptureSetup_Add`.

Map table: `2482.MPPS` (resource `0x9B2`, loaded into `0x020B7954`),
`0x80`-byte records. `0x0203F4A8` copies `rec[0]` (set selector), `rec[1]`
(map no.), `rec[2]` (sub-map) and `rec+8` (placement index). ov2 `0x020D6460`
loads placement entry `rec+8 + (rec[0] ? 0x1E1B : 0x1CAD)` for map
`mNNN_SS` (the geometry is in `data/mapz/mNNN_SS.acz`, Nintendo Huffman-8;
`tools/nds_huffman.py`).

Placement records, CaptureSetup entries and sky capture records all carry a
**Ranger ID** (section 6c), not a Dex number.

```bash
bash tools/extract_game_data.sh          # once
python3 tools/extract_wild_spawns.py
```

Result: **2,549 wild placements in 559 packages, 505 distinct Ranger IDs (298
species)**. 968 of them resolve to a map name through MPPS. Snapshot:
`research/capture/wild_spawns_2026-11-17.csv`.

Cross-check: `m002_00`'s placements include Ranger IDs 362/414/415/419/63,
which are exactly the targets of the scripted captures `M02_00_BT473/157/160/245/131`.
Those placements have `f2 = 2/3`, while plain roaming ones have `f2 = 0`.

## 6d. Which map owns a script

The ACF index is `0x20` header, then 9,689 × 12-byte entries `{offset, size, size}` with
data at `0x1C64C`; **resource ID = ACF entry index**. Map info (`0x0203F4A8`)
copies MPPS `rec+0xA` → runtime `+0x64` and `rec+0xC` → `+0x66`. ov2
`0x020D6800` loads the **map script** as resource `rec+0xA + 8`
(multiplayer: `+ 0xEE`) and a second per-map resource as `rec+0xC + 0xEF`
(multiplayer: `+ 0x1E5`).

All 31 capture-bearing map scripts (entries 11–229: `M02_*`, `MQnn_*` quest
events, `Mnn_P*`, `MPnn_WATEREN`, …) resolve to exactly one map. The 29
`C###_*` scripts (entries ~1150–1200) are chapter/story scripts loaded
by chapter: chapter table **`2483.CHPT`** (resource `0x9B3` → `0x020BD3F4`,
12-byte records `{u16 mppsIndex, u8, u8, s16 x, s16 z, u8 chapter, …}`) gives
each chapter's start map and position. The field builds the label
`c%03d_start` from `+8` (ov2 `0x020E3850`). The database records this as
`chapter_start_map`: a chapter's events can happen on other maps, so it's
a strong hint rather than proof.
`tools/build_capture_database.py` applies both mappings: 95 of 299 scripted
targets have a definite map and 202 more have a chapter start map. Two have neither.

## 6c. Ranger Pokémon IDs → National Dex — solved

Every capturable Pokémon, including per-encounter variants, has a **Ranger ID**
0–769. It indexes two parallel tables:

| table | resource | runtime | record |
|---|---|---|---|
| `2480.FPKD` (field data) | `0x9B0` | `0x020BD37C` | `0x58` × 770, **`+0x2E` u16 = National Dex** |
| `6846.CPOK` (capture data) | `0x1ABE` | `0x020B7C78` | `0x50` × 770, `+0x0C` = model index (sprite set = ACF entry `0x6B7 + model`) |

`tools/ranger_ids.py` gives `dex_of(id)` and `name_of(id)` (names from
localization file 0268, which is Dex-indexed).

It was found by brute-force matching against rendered sprites and confirmed
twice: (1) all 24 `BTnnn` event labels equal the mapped Dex number; (2) all
20 sky (`1C10`) captures resolve to flying Pokémon (Pidgey, Pidgeotto,
Pidgeot, Noctowl, Crobat, Skarmory, Pelipper, Staravia, Drifblim, Togekiss,
Charizard, Latias, Latios, Shaymin). IDs 381–384 have Dex values 900/901 and
no Pokémon sprite, so they're special non-Pokémon targets.

> **Correction to the 2026-10-04 notes:** the first sky script (ACF
> `+0xF844C`, `1C54(8, 13, 0)`) captures Ranger ID **13 = Pidgey** (model 8,
> which matches the traced `{0x6BF = 0x6B7 + 8}` entry), and **no Ranger ID maps
> to Dex 21 (Spearow)**. The old "Spearow / 21 at `0x0222F104`" identification
> needs an in-game recheck. The script/offset facts themselves are unaffected.

## 6b. Still open

0. Exact event maps inside chapter scripts (currently only the chapter start map).

1. Map names for the **multiplayer placement set** (entries 7707–8130, 1,581
   placements). `CCommuContext` (ov2 `0x0210E89C`) sets the selector byte, so
   these use base `0x1E1B`, and the index comes from runtime quest data at
   `0x020B8A92` (stride `0x224`). The single-player set (7341–7706) is fully
   named through MPPS.
2. What distinguishes variant IDs of the same species (e.g. Pidgey 11/12/13/389/440/506):
   difficulty, HP and behaviour in `FPKD`/`CPOK`.
3. Meaning of the Enemy fields `f2,f3,f5,f8..f15` (probably appearance
   conditions/flags and probabilities; `f13..f15` are 0/50/100).
4. Label states 1..12 of `CCaptureScene`.
5. Semantics of CaptureSetup entry fields `a/b/c` and `+0x140..+0x156`.

Tooling note: Capstone's linear `disasm()` stops at the first data word, so
scanning a whole overlay that way silently misses most of it. Scan word by word
when searching for instruction patterns.

## 7. Breakpoints that are now safe

These are in resident ARM9 and can never be overwritten by an overlay load:

| address | meaning | notes |
|---|---|---|
| `0x0203D9BC` | scene_overlay(sceneId) | `r0` = scene |
| `0x0207DF7C` | FS_LoadOverlay(0, id) | `r1` = overlay |
| `0x0203DEE0` | scene_create(sceneId) | the scene's overlay **is resident** here, so it's the right moment to arm overlay breakpoints |
| `0x020418D4` | CaptureSetup_Clear | |
| `0x02041998` | CaptureSetup_Add | `r1` = dex number, called for every capture target |

`tools/gdb/ordinary_capture_trace.gdb` sets these, logs the scene/overlay
sequence, and dumps `0x020B7A7C`/`0x020B79E8` at every scene creation.

## 9. Code patching and the live Capture Select proof of concept

### Patching without BLZ re-compression

`tools/patch_code_rom.py IN.nds --patches p.json --output OUT.nds` applies
RAM-addressed patches (`{"target": "ov003"|"arm9", "addr", "hex", "expect"}`)
and stores each touched executable **uncompressed** at the end of the ROM:

- overlays: FAT entry repointed, overlay-table word `+0x1C` (flags|size) = 0;
- ARM9: module params `compressed_static_end` = 0, header ARM9 offset/size
  updated, Nitro footer kept.

Smoke test (`--decompress arm9 ov002 ov003 ov022`, no patches): the readback
matches the analysis images byte for byte (ARM9 differs only at `0xBB4`, the
cleared field), and the ROM boots in DeSmuME with the identical
scene/overlay sequence.

### Headless emulator

`apt-get install desmume gdb-multiarch xvfb imagemagick`, then
`tools/emu/run_headless.sh ROM SCRIPT.py SECONDS LOG [SHOT_DIR]` runs
`desmume-cli --arm9gdb` under Xvfb and drives it with a GDB Python script
(Python loops with `continue` are reliable; GDB `commands` blocks are not).
Baseline boot: overlay 0, 1 → scene `0x00` → overlay 28 → scene `0x25`.

### Proof of concept (confirmed in the emulator, 2026-11-17)

`tools/emu/capture_select_poc.py` (env `RANGER_ID`, `RETURN_SCENE`):
at the title/demo scene it writes Clear defaults plus one target into
`CaptureSetup 0x020B797C`, sets the return scene `+0x144 = 0x25`, and makes the
current scene's `Update()` (ov28 `0x020D20A4`, caller `0x0200E2CC`) return
`2`. Observed:

```text
[load_overlay] 3
[scene_create] 0x02            setup: count 1, id 0xD, ret 0x25
[CCaptureContext::Init] this=0x0211E244
[capture state request] 1
```

The screenshots show a working capture battle: the HUD reads "Pokémon ×1
PIDGEY", the capture timer runs, and the styler is at 010/010. This is
**without any code patch**, so the resident scene system and `CaptureSetup`
are all a menu needs. A second run with `RANGER_ID=419` produced a SUICUNE
boss capture (boss HP bar shown), so it works for arbitrary targets. (The arena is black with `+0x13E = 0xFFFF`; set a
real arena ID for a background.)

## 8. Consequence for Capture Select

A main-menu "Capture Select" can work at the **scene level**:

1. `CaptureSetup_Clear(0x020B797C)`, then `CaptureSetup_Add(0x020B797C, dex, …)`
   for each target, set BGM/arena at `+0x13C/+0x13E`, and set the return scene
   at `+0x144` (`0x020B7AC0`) to the menu's scene. That's exactly what the field
   scripts do through commands `0x0CA2/0x0CA5/0x0CA7/0x0CB0`;
2. return scene `0x29` (with transition) or `2` (direct) from the menu scene's
   `Update()`.

The resident scene manager then loads ov3 and builds `CCaptureScene`
normally. Nothing has to jump into the middle of the capture minigame.
