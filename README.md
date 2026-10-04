# Pokengineering

Reverse-engineering and modding research for **Pokémon Ranger: Guardian Signs** (Nintendo DS, US build, game code `B3RE`).

> **End goal:** identify the trigger and launch path for every capture in the game, then expose every capture through a new **Capture Select** option on the main menu.

This README is a **project handoff document**. It is deliberately detailed enough that the local repository and chat history can be deleted and the work resumed later from GitHub.

---

## Resume point / branch

Latest handoff work as of **2026-10-04**:

```text
branch: research/full-capture-handoff
```

It supersedes the older documentation branch/PR:

```text
docs/capture-research-readme
PR #14
```

If the handoff branch has not been merged yet:

```bash
git clone https://github.com/CambellJSmith/Pokengineering.git
cd Pokengineering
git switch research/full-capture-handoff
```

Tracked recovery-critical additions on this branch:

```text
tools/build_debug_rom.sh
tools/decode_script_vm.py
tools/analyze_capture_scripts.py
research/capture/capture_candidates_2026-10-04.csv
```

Generated files under `work/` and rebuilt `.nds` / `.acf` files are intentionally ignored because they can be regenerated from the tracked ROM components.

---

# 1. Status at a glance

Completed:

1. Validated NDS reconstruction from extracted ROM components.
2. Localization extraction/edit/rebuild.
3. Recursive `data_game_us.acf` / NARC / LZ10 resource inventory.
4. Nitro 2D graphics rendering and lossless NCER/NCGR edit round-trip.
5. End-to-end graphics mod rebuild into a working NDS.
6. ARM9 / ARM7 / all 34 ARM9 overlay mapping and BLZ decompression.
7. Live DeSmuME/GDB tracing of the introductory Spearow capture.
8. Script VM instruction format and command dispatcher substantially decoded.
9. Exact Spearow script stream found statically in the raw game ACF.
10. **Proven bridge:** `1C10 -> state 3 -> CSkyCaptureBeforeState -> LoadCapturePokemon`.
11. Whole raw ACF script sweep: **1,695 script streams, 20 state-3 capture transitions in 16 streams**.
12. A separate ordinary-capture class family (`CCaptureScene`, `CCaptureContext`, etc.) identified.
13. Current pivot: find the **ordinary overworld capture launcher** rather than looking for more `1C10` calls.

Current architecture:

```text
SCRIPTED / CSkyCaptureBeforeState PATH
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

# 2. Capture Select design rule

Keep these concepts separate:

**Capture definition:** species/form, model/resources, difficulty/HP/behaviour, boss flags, arena, attack/skill data, etc.

**Capture trigger:** story script, map actor, mission, cutscene, tutorial, collision, boss phase, etc.

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

The final menu should call the **highest safe launcher/dispatcher** that reproduces normal setup rather than blindly jumping into the low-level minigame.

---

# 3. Fresh-clone rebuild

Repository components include:

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

Build and validate:

```bash
bash tools/build_debug_rom.sh
```

Equivalent:

```bash
mkdir -p work/debug

python3 tools/rebuild_nds.py \
  --components . \
  --output work/debug/guardian_signs_debug.nds \
  --trim

python3 tools/validate_nds.py \
  work/debug/guardian_signs_debug.nds \
  --components .
```

Previously validated:

```text
debug ROM size: 104,938,556 bytes
header CRC: 0x50C9
ARM9 overlay FAT entries: 34
NitroFS entries validated: 386
```

---

# 4. Critical ACF trap

`data/data_game_us.acf` is NitroFS/FAT file ID `0x22`.

A local same-sized file named `data/data_game_us.acf` turned out **not to be byte-identical to the raw NitroFS ACF**.

Both were:

```text
0x177BAD4 bytes = 24,623,828
```

but at the known Spearow stream:

```text
ACF +0xF844C
```

the wrong representation had:

```text
97 e8 00 ce ...
```

while the canonical raw file had:

```text
10 b1 27 00 ...
```

Wrong-file sweep result:

```text
script-like streams : 280
capture transitions : 0
```

Canonical raw-file result:

```text
script-like streams : 1695
capture transitions : 20
setup-only scripts  : 0
```

Extract canonical raw ACF:

```bash
mkdir -p work/capture

python3 tools/extract_nitrofs_file.py \
  fat_data.bin fat.bin _file_IDs.txt \
  data/data_game_us.acf \
  work/capture/data_game_us.raw.acf
```

Known values:

```text
fat_data base: 0x00164C00
file ID:       0x22
raw ACF size:  0x177BAD4
```

Known Spearow bytes:

```text
ACF +0xF844C:
10 b1 27 00 00 20 00 00 00 38 27 00 00 60 80 40
```

`tools/analyze_capture_scripts.py` now defaults to extracting raw FAT ID `0x22` directly from `fat_data.bin` and validates this signature before scanning.

---

# 5. Executable map

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
RAM/entry: 0x02380000
size:      162,308 bytes
```

ARM9 overlays:

```text
34 total
34/34 compressed in retail
34/34 successfully decoded
```

Capture-heavy overlay 3:

```text
runtime base: 0x020D00C0
decoded size: 318,752 = 0x4DD20
runtime end:  ~0x0211DDE0
BSS:          36,064 = 0x8CE0
init entries: 44
```

Run static executable analysis:

```bash
bash tools/analyze_game_code.sh
```

Decoded overlay files in `work/code_analysis/executables/overlays/` are analysis copies. A decoded edit does **not** yet automatically BLZ-recompress/repack into the ROM.

---

# 6. Early Spearow false leads

Trace target: introductory **Spearow**, National Dex `21 / 0x0015`.

### `0x0222F104`

Changing writes of `21` to `396` (Starly) produced:

```text
displayed name/text: Starly
model:               Spearow
behaviour/fight:     Spearow
```

So `0x0222F104` is a UI/display identity field, **not** the actual encounter selector.

Writer:

```text
0x02018648
```

### Sequential species record

Spearow record was observed at:

```text
0x0222D1A8
```

and immediately followed by Fearow (`22`), so this is a global species-definition table, not the intro encounter definition.

### Generic species processing

Lookup helper:

```text
0x0201A5F8
```

caller helper:

```text
0x02016C84
```

overlay-3 code around `0x020D71D8` processes a sequence:

```text
23, 22, 21, 20, 19, ...
```

so the hard-coded `21` there is also **not** the unique Spearow trigger.

Do not repeat these paths.

---

# 7. Runtime ARM9 note

Several live ARM9 addresses did not match useful disassembly from stored `arm9.bin`.

Runtime ARM9 was extracted from RAM:

```bash
dd if=/tmp/starly_full_during.bin \
   of=work/code_analysis/runtime/arm9_runtime.bin \
   bs=1 count=421012 status=none
```

Disassemble with:

```bash
arm-none-eabi-objdump \
  -D -b binary -m arm \
  --adjust-vma=0x02000000 \
  work/code_analysis/runtime/arm9_runtime.bin
```

Do not assume arbitrary live ARM9 patches map directly to the same stored-file offset until the representation difference is understood.

---

# 8. Capture setup functions

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

calls `LoadCapturePokemon` near:

```text
0x02106AB8
```

Observed Spearow load context:

```text
count = 1
entry = { 0x6BF, 0xFFFFFFFF, 0x4C }
```

`0x4C` is a hard-coded parameter, **not a capture ID**.

The `0x6BF` value was derived from lookup index `13`; therefore `13` is **not** the species/capture ID either.

Direct static callers of `0x02116774`:

```text
0x021026F8
0x0210360C
0x02111C24
```

Spearow dynamically used `0x0210360C`.

---

# 9. Script VM

Interpreter:

```text
0x02065A80
```

Game-command dispatcher:

```text
0x02065E14
```

Interpreter state via `r9`:

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

Known opcodes:

```text
0x01 game command call
0x02 wait/yield family
0x08 branch family
0x10 PUSH_S16
0x11 PUSH_U32 (consumes following dword)
0x12 PUSH_LAST_RESULT
0x14 ALU
0x16 comparison
0x18 shift
```

Opcode `0x04` also consumes an additional dword.

Selector split:

```c
group = (selector >> 10) & 0x3F;
index = selector & 0x3FF;
```

For `0x1C54`:

```text
group 7
index 0x54
```

Because the value stack grows downward:

```text
PUSH 0
PUSH 13
PUSH 8
CALL 1C54 argc=3
```

calls the handler as:

```text
(8, 13, 0)
```

`tools/decode_script_vm.py` preserves this current decoder.

---

# 10. Static Spearow script bridge

Canonical raw locations:

```text
ACF offset:      0x000F844C
ROM offset:      0x0136F24C
fat_data offset: 0x0120A64C
LZ10 header:     10 b1 27 00
compressed:      0xC48
decoded size:    0x27B1
```

Known selector:

```text
decoded +0xFB0 = CALL 0x1C54
```

Critical sequence:

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

# 11. Group-7 capture-related commands

Table area:

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

Facts:

- `1C12` / `1C54` call capture-before record setup paths.
- `1C30` is configuration.
- `1C35` writes capture-manager configuration.
- `1C36` performs associated async/state work and is **not capture-specific by itself**.
- `1C10` requests state `3`.
- `1C11` returns whether pending state is still `3`.

Exact:

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

# 12. Proven state-3 bridge

Live proof:

```text
[0x02123148] = 0x02123158        state manager
[0x02123158] = 0x0211C94C       manager vptr
[0x0211C964] = 0x021018E4       vfunc +0x18 = state resolver
```

Resolver `0x021018E4` switch case `3` loads:

```text
singleton = 0x021255CC
```

and:

```text
[0x021255CC] = 0x0211CEDC
```

Static RTTI identifies the live address point `0x0211CEDC` as:

```text
22CSkyCaptureBeforeState
```

Its table includes method:

```text
0x02106744
```

which reaches:

```text
0x02117258 LoadCapturePokemon
```

Therefore:

```text
script
 ↓
1C12 / 1C54 setup
 ↓
1C10
 ↓
manager +0xE44 = 3
 ↓
state resolver 0x021018E4
 ↓
state 3 singleton 0x021255CC
 ↓
vptr 0x0211CEDC
 ↓
CSkyCaptureBeforeState
 ↓
0x02106744
 ↓
LoadCapturePokemon 0x02117258
 ↓
capture gameplay
```

**Do not spend another session re-proving this.**

---

# 13. Whole raw-ACF capture sweep

Run:

```bash
python3 tools/analyze_capture_scripts.py
```

Expected:

```text
script-like streams : 1695
capture transitions : 20
setup-only scripts  : 0
```

The 20 transitions are in **16 streams**.

Split:

```text
1C54-based: 11
1C12-based:  9
```

Multiple launches in one stream:

```text
script 1301: 3
script 1304: 2
script 1311: 2
```

Duplicate setup example:

```text
script 1326: 1C54(3,0x1A9,0), 1C35(0xA,6)
script 1328: 1C54(3,0x1A9,0), 1C35(0xA,6)
```

So **20 trigger sites do not imply 20 unique capture definitions**.

| # | Script | ACF stream | Launch | Form | Setup args | 1C35 | 1C36 | Confidence |
|---:|---:|---:|---:|---|---|---|---|---|
| 1 | 1300 | `0xF844C` | `+0xFC0` | `1C54` | `8, 0xD, 0` | `(2, 0)` | `(0x538)` | complete (100) |
| 2 | 1301 | `0xF9094` | `+0xAE8` | `1C12` | `0x63, 0, 3, 0x94, 0x80` | `(0xD, 1)` | `—` | complete (98) |
| 3 | 1301 | `0xF9094` | `+0x1648` | `1C12` | `0xE, 0, 3, 0x40, 0x80` | `(0xD, 1)` | `—` | complete (98) |
| 4 | 1301 | `0xF9094` | `+0x1DE0` | `1C54` | `0xF, 9, 0` | `(4, 2)` | `—` | complete (95) |
| 5 | 1302 | `0xFA1E4` | `+0xF08` | `1C12` | `0xD2, 0, 3, 0x60, 0x50` | `(0xD, 1)` | `—` | complete (98) |
| 6 | 1304 | `0xFA860` | `+0xFE0` | `1C12` | `0x12E, 0, 3, 0x80, 0x80` | `(0xD, 1)` | `—` | complete (98) |
| 7 | 1304 | `0xFA860` | `+0x1948` | `1C12` | `0x10, 0, 3, 0x40, 0x50` | `(0xD, 1)` | `—` | complete (98) |
| 8 | 1305 | `0xFB6E0` | `+0xD38` | `1C54` | `3, 0xFB, 0` | `(0xA, 6)` | `—` | complete (95) |
| 9 | 1311 | `0xFD598` | `+0xCF0` | `1C12` | `0x10D, 0, 3, 0x80, 0x80` | `(2, 7)` | `—` | complete (98) |
| 10 | 1311 | `0xFD598` | `+0x12F4` | `1C12` | `0xA4, 0, 3, 0x60, 0x80` | `(2, 7)` | `—` | complete (98) |
| 11 | 1315 | `0xFE688` | `+0xA3C` | `1C54` | `2, 0x68, 0` | `(7, 4)` | `—` | complete (95) |
| 12 | 1317 | `0xFEEB8` | `+0x37C` | `1C54` | `0, 0x163, 0` | `(1, 0)` | `—` | complete (95) |
| 13 | 1318 | `0xFF1A4` | `+0x82C` | `1C12` | `0x12E, 0, 3, 0xA0, 0x60` | `(0xD, 1)` | `—` | complete (98) |
| 14 | 1320 | `0xFFD20` | `+0x1360` | `1C54` | `6, 0x179, 0` | `(0xB, 6)` | `—` | complete (95) |
| 15 | 1326 | `0x101954` | `+0x8EC` | `1C54` | `3, 0x1A9, 0` | `(0xA, 6)` | `—` | complete (95) |
| 16 | 1327 | `0x101D98` | `+0x23C` | `1C54` | `0, 0x193, 0` | `(1, 2)` | `—` | complete (95) |
| 17 | 1328 | `0x101F38` | `+0x754` | `1C54` | `3, 0x1A9, 0` | `(0xA, 6)` | `—` | complete (95) |
| 18 | 1329 | `0x1022EC` | `+0x754` | `1C54` | `3, 0x1A8, 0` | `(0xA, 6)` | `—` | complete (95) |
| 19 | 1330 | `0x10269C` | `+0x208` | `1C54` | `0, 0x1A0, 0` | `(1, 4)` | `—` | complete (95) |
| 20 | 1331 | `0x102840` | `+0x2BF8` | `1C12` | `0xE, 0, 0, 0xB0, 0x80` | `—` | `(0x537)` | high (90) |

Snapshot CSV:

```text
research/capture/capture_candidates_2026-10-04.csv
```

Two broad configuration styles were observed:

```text
simple:
1C54(...)
1C35(...)
1C10
1C11 loop
```

and:

```text
complex:
1C30(...)
1C12(...)
1C12(...)
...
1C35(...)
1C10
1C11 loop
```

The current analyzer preserves the whole nearby pre-launch configuration block rather than only the nearest `1C12`.

---

# 14. Separate ordinary capture subsystem

Overlay 3 contains:

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
0x0211A76C  13CCaptureScene
0x0211A7E4  CaptureScene.cpp
0x0211A7A4  CCaptureScene function-pointer/vtable-like table
0x0211A81C  21CCaptureCommandManage
0x0211A834  25CCaptureCommandManageData
0x0211A888  15CCaptureContext
0x0211AA2C  CCaptureContext function-pointer table
0x0211AB00  23CCaptureActorDataManage
0x0211AB1C  34CCaptureBeforeEventActorDataManage
0x0211AB44  35CCapturePokemonSkillActorDataManage
```

Known `CCaptureScene` table entries:

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
plus ARM9 entries such as 0x0200DF14 / 0x0200DF38 / 0x0203E900
```

This is the current route to ordinary captures.

---

# 15. Last dynamic experiment: what actually happened

A breakpoint at:

```text
0x020D012C
```

was tried as a tentative `CCaptureScene` constructor candidate.

Two separate ordinary Pokémon captures did **not** hit it.

Therefore:

```text
0x020D012C is not a proven normal-capture entry
```

A follow-up plan attempted breakpoints on ten `CCaptureScene` table methods. That test is **inconclusive**, not negative evidence, because:

1. multi-line commands were pasted into GDB as one malformed command;
2. reconnecting GDB to the same DeSmuME process proved unreliable;
3. after a clean restart DeSmuME was white because ARM9 was correctly waiting at `0x02000800`;
4. most importantly, overlay-3 software breakpoints installed before overlay 3 is loaded can be overwritten by the overlay loader.

So **do not conclude those ten methods are unused**. They have not yet been tested with overlay 3 definitely resident.

---

# 16. GDB / DeSmuME operating notes

Launch used:

```bash
cd ~/Documents/GitHub/desmume-gdb/desmume/src/frontend/posix

./build/cli/desmume-cli \
  --arm9gdb 3333 \
  --disable-sound \
  ~/Documents/GitHub/Pokengineering/work/debug/guardian_signs_debug.nds
```

External DeSmuME checkout is not part of this repository.

Connect:

```bash
gdb -q
```

then one command at a time:

```gdb
set architecture arm
target remote localhost:3333
```

Healthy initial stop:

```text
0x02000800 in ?? ()
```

Important quirks:

- white DeSmuME screen before `continue` is expected;
- reconnects to one DeSmuME instance often fail — restart DeSmuME for a fresh GDB connection;
- hardware watchpoints are unreliable;
- interrupting a freely running target is unreliable;
- software breakpoints in unloaded overlay RAM can be overwritten;
- enter GDB commands one per line or use a `.gdb` file;
- normal-speed launch is easier to control; use the emulator boost key when needed rather than permanently disabling the limiter.

---

# 17. Do-not-repeat list

Do not go back to:

- raw species-21 searches;
- `0x0222F104` as the capture selector;
- `0x0222D1A8` as the intro encounter definition;
- `0x0201A264` as the encounter trigger;
- `0x02012DA8` / `0x02012DB8` generic pool-manager paths;
- `0x0201A5F8` alone as the unique trigger;
- `0x020D71D8` hard-coded `21` as the intro trigger;
- `0x021007A8` as launch;
- `0x020D40CC` as launch;
- `0x4C` as capture ID;
- lookup index `13` as capture/species ID;
- raw-searching compressed ROM for `0x1C54`;
- treating `1C30`, `1C35`, or `1C36` alone as launchers;
- claiming state `3` is unknown;
- re-proving the `1C10` state bridge;
- trusting a convenient `data/data_game_us.acf` without signature validation;
- claiming the 20 `1C10` sites are all captures;
- treating `0x020D012C` as a proven normal-capture constructor.

---

# 18. Key address reference

| Address | Current meaning |
|---|---|
| `0x02065A80` | script VM interpreter |
| `0x02065E14` | VM command dispatcher |
| `0x0211C9C8` | group-7 command table area |
| `0x021026BC` | `1C10` |
| `0x021026D8` | `1C11` |
| `0x021026F8` | `1C12` |
| `0x021029C4` | `1C30` |
| `0x02102E28` | `1C35` |
| `0x02102E44` | `1C36` |
| `0x0210360C` | `1C54` |
| `0x02116774` | capture-before record writer |
| `0x02117258` | `LoadCapturePokemon` |
| `0x02117388` | load-entry helper |
| `0x02123148` | global state-manager pointer |
| `0x02123158` | observed live manager |
| `0x021018E4` | state resolver |
| `0x021255CC` | state-3 singleton |
| `0x0211CEDC` | `CSkyCaptureBeforeState` live vptr/address point |
| `0x02106744` | state method leading to capture load |
| `0x0211A76C` | `CCaptureScene` RTTI/name |
| `0x0211A7A4` | `CCaptureScene` table |
| `0x0211A888` | `CCaptureContext` RTTI/name |
| `0x0211AA2C` | `CCaptureContext` table |
| `0x0222F104` | display/name identity field only |
| `0x0222D1A8` | Spearow entry in species table |
| `0x0201A5F8` | species-object lookup |

---

# 19. Reproduce current scripted-capture result

```bash
# build ROM if necessary
bash tools/build_debug_rom.sh

# run canonical raw-ACF sweep
python3 tools/analyze_capture_scripts.py
```

Expected headline:

```text
Known Spearow signature verified at +0xF844C.
script-like streams : 1695
capture transitions : 20
setup-only scripts  : 0
```

Generated reports go to:

```text
research/capture/generated/capture_analysis.md
research/capture/generated/capture_analysis.json
research/capture/generated/capture_candidates.csv
research/capture/generated/all_script_calls.csv
research/capture/generated/script_index.csv
```

Large generated JSON/CSV files do not need to be committed because the tracked analyzer and source data regenerate them.

---

# 20. Exact next task

**Do not search for more `1C10` calls first.**

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

Preferred approach is now **static-first**:

1. find writes/references to the `CCaptureScene` vptr/table;
2. find callers/owners of the `0x020Dxxxx` scene methods;
3. identify allocation/construction paths for `CCaptureScene` and `CCaptureContext`;
4. trace backward to world/map actor code and encounter parameters;
5. select a reliable breakpoint outside unloaded overlay RAM, or identify the overlay-load boundary;
6. then perform one clean dynamic ordinary-capture trace.

After that:

1. automate ordinary-capture trigger/definition extraction;
2. map the 20 scripted state-3 triggers to maps/missions;
3. deduplicate triggers into capture definitions;
4. build the capture database;
5. identify a safe arbitrary-capture dispatcher;
6. implement overlay repacking;
7. add `Capture Select` to the main menu.

---

## Exact stopping point, 2026-10-04

> **The `CSkyCaptureBeforeState` script path is mapped and bulk-swept. The next unresolved bridge is ordinary overworld encounter → normal capture launcher → `CCaptureScene`. The attempted `CCaptureScene` breakpoint sweep was not completed cleanly because overlay-3 breakpoints were being set before a reliable post-load stop point existed.**
