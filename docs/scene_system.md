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

## 6e. More capture sources (2026-11-18)

| source | data | how it starts | count |
|---|---|---|---|
| **Capture tutorials** | capture scripts `0x5E1 + n` (ACF 1506–1512, symbols `INIT`/`MAIN`) | field script `CAP_CLEAR; CAP_150=n; CAP_START`. `CCaptureContext::Init` (ov3 `0x020D20BC`) loads the script when `CaptureSetup+0x150` (= request `+0x14`) > 0, and it spawns its own Pokémon ("The Capture tutorial has begun.") | 7 (5 used by story events: n = 2, 3, 4, 5, 7) |
| **Sky enemies (free flight)** | `9529.SPKD` (resource `0x2539` → `0x020BD494`), 16-byte records, `+4` = Ranger ID | sky command `1C76(actor, spkdIndex, …)` (ov3 `0x02103D64`) spawns an object with Ranger ID at `+0x9C6`. On capture it adds itself through ov3 `0x02111C24` → `0x02116774` | 33 records / 16 IDs (new: Latios, Drifloon, Honchkrow, Chatot) |
| **Co-op captures** | `2488.MPCP` (resource `0x9B8` → `0x020BD4C0`), 48-byte records, `+0` = Ranger ID + stats | multiplayer (ov26/ov3) | 223 IDs (42 not seen anywhere else) |

**Capture-script commands that add targets mid-capture:** `3C03` (add,
handler ov3 `0x020FE094` → `CaptureSetup_Add`) and `3C05` (add + spawn,
`0x020FE0E8`); group 8 aliases them as `2005`/`2007`, because the group-15 table
`0x0211C610` is the group-8 table `0x0211C608` + 2 entries. A sweep of all
1,683 scripts finds them **only in the tutorial scripts**:

| tutorial | capture script | targets added |
|---|---|---|
| 1 | 1506 | none (explanation only) |
| 2 | 1507 | Pikachu (386) ×2, spawned |
| 3 | 1508 | Cyndaquil (391); verified in emulator: "The Poké Assist tutorial has begun." |
| 4 | 1509 | Pikachu (388) |
| 5 | 1510 | Gligar (390) |
| 6 | 1511 | Cyndaquil (391) |
| 7 | 1512 | Pikachu (386) |

So there are no other hidden mid-battle reinforcements.

**Intrusion (`CCaptureIntrusionState`) isn't a Pokémon source.** It iterates
3 fixed slots of the `0x88`-stride capture-before records at preset screen
positions: other players joining a co-op capture.

`tools/build_capture_database.py` now includes these sources (`sky_enemy`,
`coop`, `tutorial` with its targets): 3,132 rows, **584 Ranger IDs / 306 species**.

## 6b. Still open

0. Exact event maps inside chapter scripts (currently only the chapter start map).
0a. Exact event maps inside chapter scripts need runtime state. Map
    `EventRect` layers hold `{x, z, w, h, eventId}` (ids ~300+), which the field
    registers in an event manager (ov2 `0x020D7B64` → `0x02105A28`); the
    chapter script decides what each id does at run time.

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

## 10. Capture Select ROM patch (battle menu)

Build:

```bash
bash tools/build_debug_rom.sh                                   # base ROM
python3 tools/build_capture_database.py                         # (if the DB changed)
python3 tools/capture_select/build_patch.py                     # needs keystone-engine + console-setup-linux font
python3 tools/patch_code_rom.py work/debug/guardian_signs_debug.nds \
    --patches work/capture_select/capture_select_patch.json \
    --output work/capture_select/capture_select.nds
```

**Title-menu button:** the third title-menu button (selection 2 of `CDemoMenuState`, ov28; handler `0x020D96B8`, formerly *Ranger Net* → scene `0x2B`) now sets the reopen counter (STATE+10), so the wrapper opens the menu ~32 frames later. Its label (message bank 0232 #006) is changed to "Capture Select" by `tools/capture_select/relabel_title_button.sh`, which rebuilds `data/data_localize_us.acf` into the base ROM.

**Controls on the title/demo screen:** SELECT opens the **Capture Select**
menu on the bottom screen (the top screen goes navy). UP/DOWN move (hold to
repeat), LEFT/RIGHT page by 20, **L/R jump to the previous/next section**
(story & quest events → tutorials → sky → co-op → wild → extra), **START
cycles the styler preset** (NORMAL / STRONG / MAX, shown in the header),
**A** starts the highlighted battle and **B** closes the menu. The footer
shows the position (`156/764`). **After a battle the menu reopens by itself
on the same entry** (about 30 frames after the title reloads), so battles can
be played back to back.

Styler presets write the player record before the battle: level →
`CaptureSetup+0x6C`, energy → `+0x75/+0x76` (STRONG 25/60, MAX 50/99;
NORMAL keeps the Clear defaults 1/10). Verified in the emulator: `+0x75/76 =
99` shows `099/099` energy; Clear's level 1 matches "Styler Level 01".

**Menu entries (764)**, generated from `research/capture/capture_database.csv`
(full list: `work/capture_select/capture_select_list.csv`):
- every distinct scripted field capture with **all** its targets (up to 8)
  and options (BGM, arena, flags `+0x142`, `+0x140`, `+0x154`, `+0x156`),
  labelled with the event (e.g. `041 Beldum x8 C031_AF008_1`);
- the 7 capture tutorials (`Capture tutorial TUTORIALn`, `+0x150 = n`);
- every sky capture: scripted `1C10` and free-flight `SPKD` enemies (`SKY`);
- every co-op capture Pokémon (`CO-OP`, from `MPCP`);
- every remaining wild Ranger ID (`WILD m010_02` …);
- **EXTRA**: every other Ranger ID with capture data but no trigger found
  (182 entries, `EXTRA #374` …). This adds the three species no source
  covered, Palkia (369, 428), Heatran (370, 371, 429) and Giratina
  (373, 374, 431, 432, 453; both formes), plus leftover variants of other
  species. **All 309 species with capture data are now selectable.**
  Verified: `EXTRA #374` → GIRATINA (Origin Forme) boss capture. The other
  EXTRA entries haven't been tried one by one.

**Arena backgrounds (2026-11-18).** In the field, `CFieldToCaptureState::Enter`
asks the field context (vfunc `+0x50`, ov2 `0x020D89DC`) for the arena when
`CaptureSetup+0x13E` is `0xFFFF`. It uses the current map's MPPS record:
byte `+0x6C + floorType` for floor types 0–14, `+0x7B` for 15–22, `+0x7C` for
23–30, `+0x7A` for 31 (floor type from the `FloorAttribute` placement layer
at the player). From the title there's no field, so the menu writes the
arena itself: the script's `CAP_ARENA` if set, else the battle's map default
`MPPS +0x6C` (the scripted event's map, else its chapter start map, or the wild
Pokémon's map), else fallback arena 13. All 582 battles now get a background
(319 from their map, the rest from the fallback). Verified: `001 Pichu`
(m002_00, arena 13) and a `SKY` Starly (fallback) both show a sand-and-grass
field instead of black.

**Arena catalog** (all 66 arena IDs used by MPPS or scripts, screenshotted
with `tools/emu/batch_battles.py`; screenshots are local only):

| look | arena IDs |
|---|---|
| grass / meadow | 0, 15, 16, 19, 77, 78 |
| sand, sand + grass | 2, 13, 67, 74 |
| dirt / earth | 4, 21, 23, 24, 25, 33, 44, 45, 49, 50, 79, 80 |
| water (sea bed, ocean, lake, cave water) | 5, 9, 51, 39 |
| stone, ruins, tiles | 6, 7, 8, 14, 17, 18, 20, 41, 42, 43, 52, 65, 69, 70, 71, 72, 75, 76, 82 |
| indoor (wood, carpet, mats, metal grates) | 11, 12, 27, 32, 34, 35, 37, 38, 66, 68 |
| snow / ice | 26, 28, 36, 46 |
| dark cave | 31 |
| volcanic | 10, 40 |
| **sky (clouds)** | **48** |
| grey fog | 47 |
| ornate temple | 73, 81 |

**Arena choice per battle (2026-11-18 review)**, first match wins
(`arena_from` column in `capture_select_list.csv`):
1. `script`: the event's own `CAP_ARENA` (3 battles);
2. `map`: the battle's map default (321);
3. `manual:sky`: SKY battles → 48 (15);
4. `manual:legendary`: Heatran → 40, Giratina → 31, Palkia/Dialga/Arceus →
   81, Mew → 17, Deoxys → 48, Shaymin → 77 (22);
5. `manual:sky-species`: species seen only in sky captures (Pidgeotto,
   Skarmory, Honchkrow, Chatot, Togekiss…) → 48 (9);
6. `habitat`: the most common arena among the maps where the same species is
   placed or scripted (393; co-op and EXTRA entries);
7. `fallback` 13: only `Tutorial 1` (its area matches tutorial 2's).

**Implementation** (`tools/capture_select/build_patch.py`):
- ov28 is grown: BSS materialised, code cave at `0x020EEA00`–`0x020F76AC`
  (code + strings ≈1.2 KB, 8×8 font 768 B from `Lat15-VGA8`, 532 × 64-byte
  battle records). It stays below the heap (`0x0212CFC0`).
- `Update` (vtable slot 2) of `CDemoScene`/`CGameTitleScene` → wrapper.
  When the menu is closed, the original Update runs unless SELECT is newly
  pressed. While it's open, the title logic is skipped. Every frame the
  wrapper re-asserts engine A (bottom screen) in mode 5 with BG3 as a 256×192
  direct-colour bitmap in VRAM bank C (`VRAMCNT_C = 0x89` → main BG
  `0x06020000`; bank C is unused on the title, and the original value is
  restored on exit), handles input, and redraws only when the selection
  changes.
- A: `CaptureSetup_Clear`, `CaptureSetup_Add3` for each target, BGM `+0x13C`,
  arena `+0x13E`, return scene `+0x144 = 0x2C`; returns scene `2`.
- Menu state is at `CaptureSetup+0x128` (unused tail of player record 3,
  which only multiplayer uses and Clear doesn't touch): `+0` index, `+2` top,
  `+4` previous keys, `+6` open, `+7` dirty, `+8` saved VRAMCNT_C,
  `+9` key-repeat counter, `+10` reopen counter (set by a launch; the menu
  reopens once it reaches 32 title frames), `+11` styler preset. All 8 entry
  slots stay free for targets.
- While open, the menu also blanks the top screen (sub engine DISPCNT
  `0x10000`, navy backdrop). After a capture, the title runs a transition that
  maps VRAM D to the sub engine and mirrors the bottom screen there.
- Keystone pitfall: a conditional `bl` to a forward label assembled as a
  branch-to-self (hung the menu). The builder now rejects any self-branch.

**Verified** in headless DeSmuME (`tools/emu/test_capture_select_menu.py`,
keys injected at the wrapper's `mvn r5, r5`, `0x020EEA20`):
SELECT draws the menu; DOWN ×3 moves the highlight to `004 Celebi C006_EV005`;
A loads `CaptureSetup count=1 ids=[193] ret=0x2C` and a CELEBI boss capture
runs.

2026-11-18 additions, verified the same way: `041 Beldum x8` → `count=8`
(eight Beldum on screen); `145 Capture tutorial TUTORIAL1` → `count=0
s150=1`; `162 Latios SKY` → LATIOS boss capture; `002 Buizel+Croagunk` →
`flags=0x2 v154=13 bgm=1` copied from the event.

**Finishing a capture** (`tools/emu/test_capture_finish.py`, 2026-11-18):
the capture's state numbers, read from the singletons' vptrs, are
`1 Normal, 2 Win, 3 Lose, 4 Runaway, 5 Reward, 6 Intrusion, 7 exit,
9 Result, 10 AddBrowser, 11 CheckRelease, 12 DataChange`. Forcing **Win (2)**
in a menu-launched capture leads the game to **Result (9)**: "Capture Rank S",
styler level/EXP, waiting for "Touch to skip". Touch can't be injected, so the
test then steps **AddBrowser (10)** ("Your Browser has registered a new
Pokémon!"), **CheckRelease (11)** and **exit (7)**. The game returns to the
title scene `0x2C` and redraws normally, with no hang or crash.

**Browser registration is skipped for menu battles.** The AddBrowser state
writes to the in-memory save (on the title screen no save is loaded, and the
Browser page showed `R-000` with an unrelated sprite). The patch therefore
hooks the `CCaptureScene` state switch: the load of the requested state
(ov3 `0x020D05D8`, `ldr r5,[r2,#0x14]`) becomes a `bl` to a cave after ov3's
BSS (`0x02126AC0`). That cave turns a request for AddBrowser (10) or
CheckRelease (11) into exit (7) when the return scene (`CaptureSetup+0x144`)
is the title `0x2C`, which only Capture Select sets (field captures use
`0x1B`). Menu battles still show the capture-rank result screen, then return
to the title. Verified (`test_capture_finish.py` on the patched ROM): Win →
Result → request AddBrowser (10) → immediately scene `0x2C`, with no
Browser screen and a normal title afterwards.

**Not yet verified:** finishing a capture with real (touch) input (result/browser
states may touch save data); real hardware/flashcarts.

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
