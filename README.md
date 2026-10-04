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
```

The exact stopping point is:

> **The scripted `CSkyCaptureBeforeState` path is mapped and bulk-swept. The next unresolved bridge is ordinary overworld encounter → normal capture launcher → `CCaptureScene`.**

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
14. Whole raw-ACF sweep: **1,695 script streams, 20 state-3 capture transitions in 16 streams**.
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
script-like streams : 1695
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
script-like streams : 1695
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

Some live ARM9 code did not usefully match the stored `arm9.bin` representation. Runtime ARM9 was therefore dumped from RAM and disassembled separately.

Do not assume arbitrary live ARM9 patches map directly to the same stored-file offset until that representation difference is understood.

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
script streams:        1695
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

Do **not** search for more `1C10` calls first.

Next objective:

```text
ordinary overworld Pokémon
        ↓
world/map actor collision
        ↓
normal-capture launcher
        ↓
CCaptureScene
        ↓
CCaptureContext
        ↓
capture definition
```

Preferred approach is **static-first**:

1. find all writes/references to the `CCaptureScene` vptr/table;
2. find callers/owners of the `0x020Dxxxx` scene methods;
3. identify allocation/construction paths for `CCaptureScene` and `CCaptureContext`;
4. trace backward to world/map actor code and encounter parameters;
5. find a stable breakpoint outside unloaded overlay RAM, or identify a reliable overlay-load boundary;
6. then perform one clean dynamic ordinary-capture trace.

After that:

1. automate ordinary-capture trigger/definition extraction;
2. map the 20 scripted state-3 triggers to maps/missions;
3. deduplicate triggers into capture definitions;
4. build the complete capture database;
5. identify a safe arbitrary-capture dispatcher;
6. implement overlay BLZ repacking/edit pipeline;
7. add **Capture Select** to the main menu.

---

## Final stopping point — 2026-10-04

> **The scripted `CSkyCaptureBeforeState` route is proven and exhaustively swept across the canonical raw ACF. The next unresolved problem is the separate ordinary overworld capture route. Start by statically tracing `CCaptureScene` / `CCaptureContext` ownership and construction, then choose a breakpoint that is valid only after overlay 3 is resident.**
