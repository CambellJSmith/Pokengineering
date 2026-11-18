# Pokengineering

Reverse-engineering and modding research for **Pokémon Ranger: Guardian Signs** (Nintendo DS, US build, game code `B3RE`).

> **End goal:** identify every capture trigger/definition in the game, then expose every capture through a new **Capture Select** option on the main menu.

This README is the canonical project handoff. It is intentionally detailed enough that the local checkout and chat history can be deleted and work can resume later from GitHub alone.

## Canonical recovery point

As of **2026-10-04**, the latest handoff is merged to **`main`** via PR **#16**. The older documentation-only PR #14 was closed as superseded.

```bash
git clone https://github.com/CambellJSmith/Pokengineering.git
cd Pokengineering
```

Recovery-critical files now tracked on `main`:

```text
tools/build_debug_rom.sh
tools/decode_script_vm.py
tools/analyze_capture_scripts.py
research/capture/capture_candidates_2026-10-04.csv
tools/decompress_arm9.py          (2026-11-17)
tools/rtti_hierarchy.py           (2026-11-17)
tools/scene_map.py                (2026-11-17)
tools/gdb/ordinary_capture_trace.gdb (2026-11-17)
research/capture/scene_table.csv  (2026-11-17)
research/code/rtti_classes.txt    (2026-11-17)
docs/scene_system.md              (2026-11-17)
tools/analyze_field_captures.py   (2026-11-17)
research/capture/field_capture_sequences_2026-11-17.csv
tools/extract_wild_spawns.py      (2026-11-17)
tools/nds_huffman.py              (2026-11-17)
tools/build_capture_database.py   (2026-11-17)
tools/ranger_ids.py               (2026-11-17)
research/capture/capture_database.csv (v1)
research/capture/wild_spawns_2026-11-17.csv
```

The exact stopping point (updated **2026-11-17**) is:

> **Capture Select is a working ROM patch.** On the title screen, SELECT opens a 764-battle menu covering all 309 species with capture data (story/quest events with their full target groups and options, capture tutorials, sky captures, co-op captures, wild Pokémon, and EXTRA variants). Each battle has an arena background. Controls: L/R jump between sections, START picks a styler preset (Normal/Strong/Max), and A starts the battle; the menu reopens on the same entry afterwards, and Browser registration is skipped. Build steps and internals: **[docs/scene_system.md](docs/scene_system.md)** §10.

Do **not** restart from species-ID searches or from `1C10`; those paths are already understood as described below.

---

## 1. Major completed milestones

1. Reproducible Nintendo DS reconstruction from tracked extracted components.
2. ROM validation including DS header CRC, FAT and overlay entries.
3. US localization extraction/edit/rebuild workflow.
4. Recursive `data_game_us.acf` / ACF / NARC / LZ10 inventory.
5. Nitro 2D graphics rendering for NCGR/NCLR/NSCR/NCER/NANR.
6. Lossless NCER/NCGR sprite edit round-trip.
7. End-to-end graphics-mod rebuild into a working NDS.
8. Automatic graphics identification/cataloguing.
9. ARM9 / ARM7 / all 34 ARM9 overlay mapping and BLZ decompression.
10. Dynamic Spearow capture tracing in DeSmuME + GDB.
11. Script VM instruction format and game-command dispatcher substantially decoded.
12. Exact Spearow script stream found in the canonical raw game ACF.
13. **Proven state bridge:** `1C10 -> state 3 -> CSkyCaptureBeforeState -> LoadCapturePokemon`.
14. Whole raw-ACF sweep: **1,683 script streams, 20 state-3 capture transitions in 16 streams**.
15. Separate ordinary-capture class family identified: `CCaptureScene`, `CCaptureContext`, `CCapturePokemon`, etc.

Current high-level architecture:

```text
SCRIPTED / SKY-CAPTURE PATH
script
  ↓
1C12 / 1C54 setup
  ↓
1C10
  ↓
CSkyCaptureBeforeState
  ↓
LoadCapturePokemon
  ↓
capture gameplay

ORDINARY OVERWORLD PATH
world Pokémon / map actor
  ↓
collision / encounter trigger
  ↓
UNKNOWN NORMAL-CAPTURE LAUNCHER       ← NEXT PROBLEM
  ↓
CCaptureScene
  ↓
CCaptureContext / capture engine
```

The 20 `1C10` sites are **not** assumed to be every capture in the game.

---

## 2. Capture Select design rule

Keep these separate:

- **Capture definition:** species/form, model/resources, difficulty/HP/behaviour, boss flags, arena, attack/skill data, etc.
- **Capture trigger:** story script, map actor, mission, cutscene, tutorial, collision, boss phase, etc.

The same definition may have multiple triggers.

Target database shape:

```text
capture_id
species
variant/form
source_script
source_offset
source_map_or_mission
trigger_conditions
capture_parameters
launcher_function
overlay
return_destination
notes
```

The final menu should call the **highest safe launcher/dispatcher** that reproduces normal setup rather than blindly jumping into the low-level capture minigame.

---

## 3. Fresh-clone ROM rebuild

Tracked reconstruction inputs include:

```text
arm9.bin
arm7.bin
a9ovr.bin
a9ovr_data.bin
fat.bin
fat_data.bin
header.bin
_file_IDs.txt
```

Build + validate:

```bash
bash tools/build_debug_rom.sh
```

Output:

```text
work/debug/guardian_signs_debug.nds
```

Previously validated values:

```text
debug ROM size:          104,938,556 bytes
header CRC:              0x50C9
ARM9 overlay FAT entries: 34
NitroFS entries:          386
```

`.nds` files are intentionally not tracked because they can be regenerated.

---

## 4. Critical raw-ACF trap

`data/data_game_us.acf` is NitroFS/FAT file ID **`0x22`**.

A same-sized local `data/data_game_us.acf` was found to be byte-different from the canonical raw NitroFS file. Both were `0x177BAD4` bytes, but at the known Spearow stream:

```text
ACF +0xF844C
wrong representation: 97 e8 00 ce ...
canonical raw ACF:     10 b1 27 00 ...
```

Scanning the wrong representation produced the false result:

```text
script-like streams : 280
capture transitions : 0
```

Canonical raw result:

```text
script-like streams : 1683
capture transitions : 20
setup-only scripts  : 0
```

Canonical raw-AFC facts:

```text
fat_data base: 0x00164C00
FAT file ID:   0x22
raw ACF size:  0x177BAD4
Spearow ACF:   +0xF844C
Spearow header: 10 b1 27 00
```

`tools/analyze_capture_scripts.py` now defaults to reconstructing FAT ID `0x22` directly from `fat_data.bin` and validates the Spearow signature before scanning. Do not bypass this check without a reason.

Run:

```bash
python3 tools/analyze_capture_scripts.py
```

Expected headline:

```text
Known Spearow signature verified at +0xF844C.
script-like streams : 1683
capture transitions : 20
setup-only scripts  : 0
```

---

## 5. Executable / overlay map

ARM9:

```text
ROM offset:      0x00004000
RAM base:        0x02000000
entry point:     0x02000800
executable size: 421,012 bytes
SHA-256: 4171ab911318eda40020c8643ff07b56bec55ad393bc81a8236adf949fc38ff6
```

ARM7:

```text
RAM / entry: 0x02380000
size:        162,308 bytes
```

ARM9 overlays:

```text
34 total
34/34 compressed in retail
34/34 successfully BLZ-decoded
```

Capture-heavy overlay 3:

```text
runtime base: 0x020D00C0
decoded size: 318,752 = 0x4DD20
runtime end:  ~0x0211DDE0
BSS:          36,064 = 0x8CE0
init entries: 44
```

Run:

```bash
bash tools/analyze_game_code.sh
```

Decoded overlays under `work/code_analysis/executables/overlays/` are analysis copies. Editing them does **not** yet BLZ-recompress/repack into the ROM; an overlay edit pipeline is still required later.

---

## 6. Spearow trace: important false leads already ruled out

Intro target: **Spearow**, National Dex `21 / 0x0015`.

> **2026-11-17 correction:** the script's capture ID is Ranger ID `13`, which `FPKD+0x2E` maps to **Dex 16 Pidgey** (model 8). No Ranger ID maps to Dex 21, so there's no Spearow capture data in the game. Treat "Spearow" below as "the intro sky target (Pidgey)" until rechecked in-game. See `docs/scene_system.md` section 6c.

### `0x0222F104` is display identity only

Changing writes of `21` to `396` (Starly) caused:

```text
displayed name/text: Starly
model:               Spearow
behaviour/fight:     Spearow
```

Therefore `0x0222F104` is not the actual encounter selector. Writer observed at `0x02018648`.

### `0x0222D1A8` is a species-table entry, not the story encounter

The Spearow record was immediately followed by Fearow (`22`), consistent with a sequential global species table.

### `0x0201A5F8` / `0x02016C84` path is generic species processing

Overlay 3 around `0x020D71D8` applies the same helper to a sequence such as `23, 22, 21, 20, 19, ...`; the hard-coded `21` there is not the unique intro trigger.

### Other rejected paths / assumptions

Do not restart from:

```text
0x0201A264                  generic species/resource parser
0x02012DA8 / 0x02012DB8    generic pool manager
0x021007A8                  battle-loop helper
0x020D40CC                  predicate
0x4C                        not capture ID
0x02041F5C                  generic accessor
0x02022754                  generic array getter
13                          lookup index, not capture/species ID
1C30 / 1C35 / 1C36 alone   not launchers
raw search for 0x1C54      invalid for compressed script discovery
```

State `3` is **not unknown**; it is confirmed `CSkyCaptureBeforeState`.

---

## 7. Runtime ARM9 note

**Solved 2026-11-17:** `arm9.bin` is BLZ-compressed (module params `compressed_static_end = 0x02066C94`). `python3 tools/decompress_arm9.py` writes `work/code_analysis/runtime/arm9_decompressed.bin`, which matches RAM 1:1 for `0x02000000-0x020AA898`. Static BSS is `0x020AA0A0-0x020D00C0`.

ARM9 patches therefore need BLZ recompression, the same way overlays do. Alternatively, clear `compressed_static_end` and store ARM9 uncompressed, if it still fits.

---

## 8. Script VM facts

Interpreter:

```text
0x02065A80
```

Game-command dispatcher:

```text
0x02065E14
```

VM state via `r9`:

```text
+0x00 instruction pointer
+0x04 value-stack pointer
+0x08 call/control-stack pointer
+0x0C saved/local base
+0x10 last command return value
+0x14 current/script context
+0x18 bound/error context
+0x20 wait/countdown
```

Normal instruction word:

```text
byte0   opcode
byte1   subtype / argc / flags
upper16 signed operand
```

Known opcode semantics:

```text
0x01 game command call
0x02 wait/yield family
0x08 branch family
0x10 PUSH_S16
0x11 PUSH_U32 (consumes next dword)
0x12 PUSH_LAST_RESULT
0x14 ALU
0x16 comparison
0x18 shift
```

Opcode `0x04` also consumes an additional dword.

Selector split:

```c
group = (selector >> 10) & 0x3f;
index = selector & 0x3ff;
```

Example: `0x1C54` = group 7, index `0x54`.

Because the value stack grows downward:

```text
PUSH 0
PUSH 13
PUSH 8
CALL 1C54 argc=3
```

passes handler arguments `(8, 13, 0)`.

`tools/decode_script_vm.py` preserves the current decoder.

---

## 9. Exact Spearow script stream

Canonical locations:

```text
ACF offset:      0x000F844C
ROM offset:      0x0136F24C
fat_data offset: 0x0120A64C
LZ10 header:     10 b1 27 00
compressed size: 0xC48
decoded size:    0x27B1
```

Critical decoded sequence:

```text
+0x0FA4 PUSH 0
+0x0FA8 PUSH 13
+0x0FAC PUSH 8
+0x0FB0 CALL 1C54 args=(8,13,0)

+0x0FB4 PUSH 0
+0x0FB8 PUSH 2
+0x0FBC CALL 1C35 args=(2,0)

+0x0FC0 CALL 1C10

+0x0FC4 PUSH 0x538
+0x0FC8 CALL 1C36(0x538)

+0x0FCC CALL 1C11
+0x0FD0 PUSH_LAST_RESULT
+0x0FD4 conditional backward branch -> +0xFCC
```

---

## 10. Group-7 capture-related commands

Command table area:

```text
0x0211C9C8
```

Mappings:

```text
1C10 -> 0x021026BC
1C11 -> 0x021026D8
1C12 -> 0x021026F8
1C30 -> 0x021029C4
1C35 -> 0x02102E28
1C36 -> 0x02102E44
1C54 -> 0x0210360C
```

Current semantics:

- `1C12` / `1C54`: capture-before record setup paths.
- `1C30`: configuration setter.
- `1C35`: capture-manager configuration.
- `1C36`: associated async/state work; not capture-specific alone.
- `1C10`: request pending state ID `3`.
- `1C11`: test whether pending state is still `3`.

Exact core behaviour:

```c
1C10() {
    (*(Global **)0x02123148)->field_E44 = 3;
    return 0;
}

1C11() {
    return (*(Global **)0x02123148)->field_E44 == 3;
}
```

---

## 11. Proven state-3 bridge

Live observations:

```text
[0x02123148] = 0x02123158   live state manager
[0x02123158] = 0x0211C94C   manager vptr
[0x0211C964] = 0x021018E4   vfunc +0x18 = state resolver
```

Resolver `0x021018E4`, case `3`, returns singleton:

```text
0x021255CC
```

whose live vptr is:

```text
0x0211CEDC
```

Static RTTI identifies that address point as:

```text
22CSkyCaptureBeforeState
```

Its table includes method `0x02106744`, which reaches:

```text
0x02117258 LoadCapturePokemon
```

Therefore this bridge is proven and does not need more GDB confirmation:

```text
script
  ↓
1C12 / 1C54 setup
  ↓
1C35/config as applicable
  ↓
1C10
  ↓
manager +0xE44 = 3
  ↓
state resolver 0x021018E4
  ↓
state-3 singleton 0x021255CC
  ↓
CSkyCaptureBeforeState vptr 0x0211CEDC
  ↓
0x02106744
  ↓
LoadCapturePokemon 0x02117258
  ↓
capture gameplay
```

---

## 12. Capture-before / load functions

Important overlay-3 functions:

```text
0x02116774  capture-before record writer
0x02117258  LoadCapturePokemon
0x02117388  unique capture-load entry helper
```

Known `CSkyCaptureBeforeState` method:

```text
0x02106744
```

which calls `LoadCapturePokemon` near `0x02106AB8`.

Observed Spearow capture-load context:

```text
count = 1
entry = { 0x6BF, 0xFFFFFFFF, 0x4C }
```

`0x4C` is a hard-coded parameter, not a capture ID. The `0x6BF` value was derived from lookup index `13`; `13` is also not a capture/species ID.

Direct static callers of `0x02116774`:

```text
0x021026F8
0x0210360C
0x02111C24
```

Spearow dynamically used `0x0210360C` (`1C54`).

---

## 13. Whole-game scripted capture sweep

`tools/analyze_capture_scripts.py` performs aligned VM decoding across embedded LZ10 script streams in the canonical raw ACF.

Validated result:

```text
script streams:        1683
scripts with 1C10:       16
capture transitions:     20
setup-only scripts:       0
```

Of the 20 launch transitions:

```text
11 use 1C54-style setup
 9 use 1C12-style setup
19 were scored complete
 1 was scored high-confidence
all 20 have the 1C11 pending-state wait loop
```

Some scripts contain multiple launches:

```text
script #1301: 3
script #1304: 2
script #1311: 2
```

The same configuration can occur at multiple trigger sites, so these are **trigger sites**, not necessarily unique capture definitions.

Tracked snapshot:

```text
research/capture/capture_candidates_2026-10-04.csv
```

The analyzer regenerates richer Markdown/JSON/CSV reports under:

```text
research/capture/generated/
```

Large generated reports are not required for recovery because the canonical source components and analyzer are tracked.

---

## 14. Separate ordinary capture subsystem

Overlay 3 contains a distinct class family including:

```text
13CCaptureScene
CaptureScene.cpp
21CCaptureCommandManage
25CCaptureCommandManageData
15CCaptureContext
CaptureContext.cpp
23CCaptureActorDataManage
34CCaptureBeforeEventActorDataManage
35CCapturePokemonSkillActorDataManage
15CCapturePokemon
21CCapturePokemonManage
20CCapturePokemonHPBar
20CCapturePokemonState
26CCapturePokemonNormalState
27CCapturePokemonScriptManage
```

Important static addresses:

```text
0x0211A76C  13CCaptureScene RTTI/name
0x0211A7E4  CaptureScene.cpp string
0x0211A7A4  CCaptureScene function-pointer/vtable-like table
0x0211A81C  CCaptureCommandManage RTTI/name
0x0211A834  CCaptureCommandManageData RTTI/name
0x0211A888  CCaptureContext RTTI/name
0x0211AA2C  CCaptureContext function-pointer table area
0x0211AB00  CCaptureActorDataManage
0x0211AB1C  CCaptureBeforeEventActorDataManage
0x0211AB44  CCapturePokemonSkillActorDataManage
```

Known `CCaptureScene` table entries include:

```text
0x020D014C
0x020D0150
0x020D0520
0x020D0734
0x020D07BC
0x020D07DC
0x020D07FC
0x020D0168
0x020D02DC
0x020D0478
```

This subsystem is the current route to ordinary overworld captures.

---

## 15. Last dynamic experiment and why it was inconclusive

`0x020D012C` was tried as a tentative `CCaptureScene` constructor candidate because it loads a pointer near the `CCaptureScene` table. Two normal captures did **not** hit it.

Conclusion:

```text
0x020D012C is not a proven normal-capture entry point
```

A follow-up sweep attempted breakpoints on ten `CCaptureScene` table methods. That test was **not completed cleanly** because:

1. multi-line GDB commands were accidentally pasted as one malformed command;
2. DeSmuME's GDB stub reconnects poorly, so the process often needs restarting for a fresh connection;
3. DeSmuME starts white at `0x02000800` until GDB issues `continue`;
4. most importantly, software breakpoints placed in overlay-3 RAM **before overlay 3 is loaded can be overwritten by the overlay loader**.

Therefore do **not** interpret the failed breakpoint attempt as evidence that the table methods are unused.

The next dynamic trace must first establish that overlay 3 is resident, or break at a stable caller/loader outside the unloaded overlay region.

---

## 16. DeSmuME / GDB operating notes

Local research used a DeSmuME source build with ARM9 GDB stub:

```bash
cd ~/Documents/GitHub/desmume-gdb/desmume/src/frontend/posix

./build/cli/desmume-cli \
  --arm9gdb 3333 \
  --disable-sound \
  ~/Documents/GitHub/Pokengineering/work/debug/guardian_signs_debug.nds
```

The external DeSmuME checkout is not tracked in this repository.

Connect in a fresh second terminal:

```bash
gdb -q
```

Then enter **one command per line**:

```gdb
set architecture arm
target remote localhost:3333
```

Healthy initial stop:

```text
0x02000800 in ?? ()
```

Then:

```gdb
continue
```

Important quirks:

- white screen before `continue` is expected;
- reconnecting GDB to the same DeSmuME instance is unreliable; restart DeSmuME for a fresh connection;
- hardware watchpoints are unreliable;
- interrupting a freely running target is unreliable;
- ordinary execute breakpoints work much better;
- software breakpoints in an unloaded overlay can be overwritten when that overlay loads;
- conditional breakpoints on extremely hot dispatchers can make the emulator appear frozen;
- use a `.gdb` command file for larger command batches rather than multi-line interactive paste.

---

## 17. Key address reference

| Address | Current meaning |
|---|---|
| `0x02065A80` | script VM interpreter |
| `0x02065E14` | VM game-command dispatcher |
| `0x0211C9C8` | group-7 command table area |
| `0x021026BC` | `1C10` handler |
| `0x021026D8` | `1C11` handler |
| `0x021026F8` | `1C12` handler |
| `0x021029C4` | `1C30` handler |
| `0x02102E28` | `1C35` handler |
| `0x02102E44` | `1C36` handler |
| `0x0210360C` | `1C54` handler |
| `0x02116774` | capture-before record writer |
| `0x02117258` | `LoadCapturePokemon` |
| `0x02117388` | unique load-entry helper |
| `0x02123148` | global state-manager pointer |
| `0x02123158` | observed live state manager |
| `0x021018E4` | state resolver |
| `0x021255CC` | state-3 singleton |
| `0x0211CEDC` | `CSkyCaptureBeforeState` live vptr/address point |
| `0x02106744` | state method leading to capture load |
| `0x0211A76C` | `CCaptureScene` RTTI/name |
| `0x0211A7A4` | `CCaptureScene` table |
| `0x0211A888` | `CCaptureContext` RTTI/name |
| `0x0211AA2C` | `CCaptureContext` table area |
| `0x0222F104` | UI/display species identity only |
| `0x0222D1A8` | Spearow species-table entry |
| `0x0201A5F8` | species-object lookup |

---

## 18. Exact next task

Statically, every capture source is now located and extracted (`docs/scene_system.md` sections 4–6). Next:

1. **Refine the capture database.** v1 exists: `python3 tools/build_capture_database.py` → `research/capture/capture_database.csv` (2,868 rows: sky 20, scripted 299 targets, wild 2,549; 534 Ranger IDs = 304 species, all named via `tools/ranger_ids.py`). Map scripts are now resolved through MPPS (`rec+0xA + 8`, `docs/scene_system.md` §6d), giving 95 of 299 scripted targets a definite map. Chapter scripts get their chapter's start map from `2483.CHPT` (202 targets). Open items: exact event maps inside chapter scripts, and decode the placement condition fields so roaming variants can be deduplicated into definitions.
2. The 1,581 unnamed wild placements are all in the **multiplayer** placement set (entries 7707–8130, base `0x1E1B`, selected by `CCommuContext`). They matter for Capture Select only if co-op captures are wanted; their map index comes from runtime quest data `0x020B8A92`.
3. Work out what distinguishes variant Ranger IDs of the same species (`FPKD`/`CPOK` fields: HP, difficulty, behaviour).
4. Optional dynamic confirmation: `gdb -q -x tools/gdb/ordinary_capture_trace.gdb`, walk into a wild Pokémon, and expect `[CAP_ADD] dex=…` and scenes `1 → 0x29 → 2 → 0x1B → 1`.
5. Capture Select: **done as a ROM patch** (`tools/capture_select/build_patch.py` + `tools/patch_code_rom.py`; see item 5 in the previous list and `docs/scene_system.md` §10). Remaining: real touch input and real hardware tests.
6. Pick per-target arena/BGM from the database (`CAP_ARENA`/`CAP_BGM` of the original script, or the map's default arena).

---

## 19. 2026-11-17 static breakthrough (summary)

Full details: **[docs/scene_system.md](docs/scene_system.md)**.

```bash
bash tools/analyze_game_code.sh
python3 tools/decompress_arm9.py
python3 tools/rtti_hierarchy.py 'Capture|Field.*State'   # class hierarchy + vtables
python3 tools/scene_map.py --csv research/capture/scene_table.csv
```

- `arm9.bin` was compressed. Decompressing it resolved the runtime mismatch.
- 460 RTTI classes recovered across ARM9 + 34 overlays (`research/code/rtti_classes.txt`).
- Scene manager: `scene_overlay 0x0203D9BC`, `scene_create 0x0203DEE0`. All 58 scene IDs are mapped to an overlay, a constructor and a class.
- `CCaptureScene` is scene `2` (ov3, ctor `0x020D013C`). `0x020D012C` is only the base ctor.
- Ordinary chain: field state 3 `CFieldToCaptureState` → scene `0x29` `CBossProduceScene` → scene `2` → scene `0x1B`.
- Resident capture request block: `0x020B7AB8` (= transition block `0x020B7A7C + 0x3C`). `+8` = return scene, `+0` = BGM kind, `+2` = arena/BG.
- `LoadCapturePokemon` is a resource preloader, not a target selector.
- Ov2/ov3/ov22 overlap in RAM. Use the resident breakpoints in `tools/gdb/ordinary_capture_trace.gdb`.

---

### Second pass (same day): capture setup and trigger

- Resident `CaptureSetup` struct at `0x020B797C`: `+0` count, `+0xC` entries `{u32, u16 dexId, u16, u16}`, `+0x13C` BGM, `+0x13E` arena, `+0x144` return scene, `+0x15C` result. API: `0x020418D4` clear, `0x02041998` add.
- Field states: 3 = `CFieldToCaptureState`, 7 = `CFieldAuthoringEventState`. Pending state is at `[*0x021260E0 + 0x1F18]`.
- Field script group-3 capture commands `0x0CA2–0x0CB2` decoded. The common script `sToCapture` calls `0x102E`, which is the only single-player writer of field state 3.
- Script symbol tables decoded (base-40 names). `tools/analyze_field_captures.py` finds **158 started field captures in 60 scripts**, labelled by event (`M02_00_BT473` …) and named via localization file `0268`.
- `0x02041998` is resident and called for every capture target, so it's the ideal dynamic breakpoint (already in the GDB script).
- Stream count is 1,683 (both tools agree; the earlier "1,695" figure was wrong). Sky `1C10` transitions are still 20.

---

### Third pass (same day): wild placements

- Map placement packages: ACF entries 7341–8130 (NARC → `MPIF` + `LYR` → NARC → layer NARC). Layer type 1 = `CMapPlacementDataLayerEnemy`, 26-byte records `{x, z, f2, f3, rangerId, …}`.
- Map table `2482.MPPS`: placement entry = `rec+8 + (rec[0] ? 0x1E1B : 0x1CAD)`, map name `m{rec[1]:03}_{rec[2]:02}`.
- `tools/extract_wild_spawns.py`: **2,549 placements, 505 Ranger IDs**, 968 with resolved map names. Cross-checked against the scripted `M02_00_BT*` captures.
- Ranger Pokémon ID (0–769) ≠ Dex. `FPKD+0x2E` gives the Dex number (`tools/ranger_ids.py`), confirmed by all 24 `BTnnn` labels and by all sky captures resolving to flyers. The intro sky target is Ranger ID 13 = **Pidgey**, not Spearow.
- `data/mapz/*.acz` = Nintendo Huffman-8 map geometry (`MBG0`); decoder in `tools/nds_huffman.py`.

---

### Fourth pass (same day): IDs, maps, patching, live proof of concept

- Ranger ID → Dex via `FPKD+0x2E` (`tools/ranger_ids.py`). It's confirmed by all 24 `BTnnn` labels, by every sky capture being a flyer, and **on screen** ("PIDGEY" for ID 13).
- Script → map: map script = MPPS `rec+0xA + 8`. Chapter scripts → chapter start map via `2483.CHPT`. 297 of 299 scripted targets now have a map or chapter map.
- Placement set `0x1E1B` (entries 7707–8130) = multiplayer (`CCommuContext`).
- `tools/patch_code_rom.py`: patch ARM9/overlays and store them uncompressed. Boot-tested.
- `tools/emu/`: headless DeSmuME + GDB. **`capture_select_poc.py` launches a real capture battle of any Ranger ID from the title screen**, with no code patches (`docs/scene_system.md` §9).

---

## Final stopping point — 2026-11-18

> **Capture Select menu: 764 battles covering all 309 species, each with an arena background; L/R section jumps, START styler presets, auto-return to the menu after each battle.** New sources since 2026-11-17: 7 capture tutorials (capture scripts 1506–1512), free-flight sky enemies (`SPKD`), co-op captures (`MPCP`), and full option copying (8 targets, flags, `+0x140/0x150/0x154/0x156`). The database has 584 Ranger IDs / 306 species; tutorial entries are named after their targets. "Intrusion" turned out to be co-op players joining, not Pokémon. A forced-win capture now runs Result → Browser registration → back to the title without crashing (`tools/emu/test_capture_finish.py`). Menu battles skip Browser registration and the release check (ov3 state-switch hook), so they don't touch save data through those screens. Still open: real touch input, real hardware. See `docs/scene_system.md` §6e and §10.
