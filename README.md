# Pokengineering

Reverse-engineering and modding research for **Pokémon Ranger: Guardian Signs** (Nintendo DS, US build / game code `B3RE`).

This repository has moved well beyond simple text extraction. It now contains a reproducible ROM reconstruction path, recursive archive and graphics analysis, lossless Nitro 2D graphics editing, executable/overlay mapping, BLZ decompression, and an active dynamic reverse-engineering effort aimed at one specific end goal:

> **Identify the trigger and launch path for every capture in the game, then expose every capture through a new Capture Select option on the main menu.**

The current capture work is not complete, but it has already reached the point where individual ARM9 functions, live capture-state fields, species lookup routines, overlay call sites, and runtime structures are being traced instruction-by-instruction.

---

## Project status at a glance

The major milestones completed so far are:

1. **Validated Nintendo DS reconstruction** from the extracted ROM components.
2. **Localization extraction/edit/rebuild** for the US localization ACF/MES resources.
3. **Recursive `data_game_us.acf` inventory** across ACF, NARC, wrapped NARC, LZ10 and Nitro resources.
4. **Nintendo DS Nitro 2D graphics rendering** for NCGR/NCLR/NSCR/NCER/NANR resources.
5. **Lossless NCER sprite edit round-trip** back into NCGR source graphics.
6. **End-to-end graphics mod build pipeline** through nested archives and back into a rebuilt ROM.
7. **Automatic graphics identification/indexing** using exact visual fingerprints, silhouettes, shared source data and resource topology.
8. **ARM9 / ARM7 / overlay executable map**, including successful BLZ decompression of all 34 ARM9 overlays.
9. **Dynamic ARM9 capture tracing in DeSmuME**, including live memory instrumentation and GDB breakpoints.
10. **Confirmed distinction between a display/name species field and the actual capture fight identity.**
11. **Confirmed species-definition table parsing and species lookup paths.**
12. **Confirmed a generic overlay-3 routine that processes a sequence of species IDs, proving that one apparent Spearow caller is not the encounter trigger.**

The current work is focused on separating:

```text
story / map / mission / script trigger
                ↓
        capture launch request
                ↓
     encounter-specific parameters
                ↓
        species / capture state
                ↓
        capture engine setup
                ↓
          live capture fight
                ↓
        result / return handling
```

The eventual menu feature should call the **highest safe capture launcher** we can identify, rather than blindly invoking a low-level battle routine without the state that the normal event scripts establish first.

---

# 1. Repository and ROM reconstruction

The project is based on extracted Nintendo DS components rather than requiring the original `.nds` image to remain present locally.

Important root-level components include:

```text
arm9.bin
arm7.bin
a9ovr.bin
a9ovr_data.bin
fat.bin
fat_data.bin
header.bin
_file_IDs.txt
...
```

The extracted component set is sufficient to rebuild a valid Nintendo DS image.

The core reconstruction tools are:

```text
tools/rebuild_nds.py
tools/validate_nds.py
```

A debug ROM can be rebuilt directly with:

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

A locally tested rebuild produced:

```text
work/debug/guardian_signs_debug.nds
size: 104,938,556 bytes
header CRC: 0x50C9
ARM9 overlay FAT entries preserved: 34
NitroFS entries validated: 386
```

The important practical result is that the project can regenerate a bootable analysis ROM from repository data without depending on the original ROM file still being present on one computer.

---

# 2. Localization pipeline

The original localization workflow remains available.

```text
fat_data.bin + fat.bin + _file_IDs.txt
                ↓
   validated NitroFS extraction
                ↓
      data_localize_us.acf
                ↓
             acftool
                ↓
          MES resources
                ↓
             ra3mes
                ↓
         editable JSON
                ↓
             ra3mes
                ↓
          rebuilt MES
                ↓
             acftool
                ↓
 rebuilt_data_localize_us.acf
                ↓
       rebuild_nds.py
                ↓
        rebuilt NDS image
```

Initial extraction:

```bash
bash tools/setup_guardian_tools.sh
bash tools/extract_localization.sh
```

Editable localization output is written under:

```text
work/localization/json/
```

Rebuild:

```bash
bash tools/rebuild_localization.sh
bash tools/build_modded_rom.sh
```

See:

- [`docs/localization_workflow.md`](docs/localization_workflow.md)
- [`docs/rom_rebuild_workflow.md`](docs/rom_rebuild_workflow.md)

---

# 3. Main game archive inventory

`data/data_game_us.acf` is NitroFS/FAT file ID `0x22`.

The project reconstructs this archive from the validated raw FAT payload and walks the archive recursively instead of trusting the originally unpacked `data/` tree, which was found to contain alignment problems.

Run:

```bash
bash tools/extract_game_data.sh
```

Top-level measured US archive figures:

```text
ACF slots:                    9,689
real entries:                 9,458
extracted/decompressed bytes: 54,044,313
```

The recursive inventory later expanded this to:

```text
inventory rows:               26,951
real resources:               26,720
maximum logical depth:        4
parsed ACF containers:        1,110
parsed NARC containers:       2,364
wrapped/embedded NARCs:       787
recognized resources:         14,603
unknown resources:            12,117
container parse errors:       0
cycles:                       0
max-depth stops:              0
```

The recursive inventory intentionally distinguishes **structural relationships** from **semantic identification**. Two graphics resources being adjacent or inside the same archive is evidence of co-location, not proof that they form one sprite/background/palette set.

See [`docs/game_acf_inventory.md`](docs/game_acf_inventory.md).

---

# 4. Nitro graphics reverse engineering

The graphics pipeline now handles the major Nintendo DS Nitro 2D resource types used by Guardian Signs:

```text
NCGR  character/tile graphics
NCLR  palettes
NSCR  tile maps/screens
NCER  cell/OAM sprite layouts
NANR  animation resources
```

The complete recursive graphics catalogue contains **11,129** recognized graphics resources:

```text
NCGR: 3,630
NCLR: 2,655
NSCR:   662
NCER: 3,710
NANR:   472
```

The renderer is deliberately conservative. It can emit deterministic previews and structural candidate relationships without pretending uncertain pairings are confirmed facts.

Useful entry points include:

```bash
bash tools/render_game_graphics.sh
bash tools/identify_game_graphics.sh
```

A full retail preview run exposed an important edge case: 1,328 NCGR resources declared dimensions larger than their physically stored tile/pixel payload. The renderer was corrected to use exact physical extents for diagnostic rendering rather than inventing nonexistent tiles.

See:

- [`docs/nitro_graphics_previews.md`](docs/nitro_graphics_previews.md)
- [`docs/nitro_graphics_format_sources.md`](docs/nitro_graphics_format_sources.md)
- [`docs/automatic_graphics_identification.md`](docs/automatic_graphics_identification.md)

---

# 5. First proven graphics edit path

`G00583__bank_0001` became the first in-game verified graphics asset used to prove a complete edit/rebuild path.

The project now supports:

```text
NCER/OAM layout
      +
NCGR indexed graphics
      +
NCLR palette
      ↓
lossless indexed PNG pieces
      ↓
edit
      ↓
re-import while preserving palette indices
      ↓
rebuilt NCGR
      ↓
rebuilt nested ACF
      ↓
rebuilt data_game_us.acf
      ↓
rebuilt NDS
```

The NCER editor rejects edits that would silently destroy source information, including incompatible dimensions, palette changes, partial alpha, ambiguous overlapping source ranges, and other non-round-trippable transformations.

Relevant files:

```text
tools/edit_ncer_sprite.py
tools/build_graphics_mod.py
tools/build_g00583_mod.sh
docs/confirmed_graphics_assets.json
```

See [`docs/ncer_sprite_editing.md`](docs/ncer_sprite_editing.md).

---

# 6. Executable and overlay reverse engineering

The current executable-analysis tooling is centered on:

```text
tools/analyze_nds_code.py
tools/analyze_game_code.sh
tools/blz.py
```

Run:

```bash
bash tools/analyze_game_code.sh
```

The retail US executable map currently establishes:

## ARM9

```text
ROM offset:       0x00004000
RAM address:      0x02000000
entry point:      0x02000800
executable size:  421,012 bytes
SHA-256:          4171ab911318eda40020c8643ff07b56bec55ad393bc81a8236adf949fc38ff6
```

The checked-in `arm9.bin` is 421,024 bytes because it contains the executable payload plus a 12-byte footer.

## ARM7

```text
RAM address: 0x02380000
entry point: 0x02380000
size:        162,308 bytes
```

## ARM9 overlays

The game has:

```text
34 ARM9 overlays
34 / 34 compressed in the retail image
34 / 34 successfully BLZ-decoded by the analysis tooling
```

Most overlays share the runtime region beginning around `0x020D00C0`; some use other load addresses, including:

```text
overlay 2:  0x020D1B80
overlay 3:  0x020D00C0
overlay 4:  0x0226C000
overlay 28: 0x020D1B80
```

Examples of decoded sizes/state:

```text
overlay 2:  345,440 bytes RAM + 28,384 BSS; 47 initializer entries
overlay 3:  318,752 bytes RAM + 36,064 BSS; 44 initializer entries
overlay 4:  291,488 bytes RAM + 267,264 BSS; 2 initializer entries
overlay 23:  37,792 bytes
overlay 26:  93,344 bytes
overlay 27: 109,504 bytes
overlay 28:  48,000 bytes RAM + 70,400 BSS
overlay 30:  23,904 bytes RAM + 124,160 BSS
```

The analysis produces:

```text
work/code_analysis/summary.json
work/code_analysis/memory_map.csv
work/code_analysis/overlays.csv
work/code_analysis/static_initializers.csv
work/code_analysis/strings.csv
work/code_analysis/ghidra_targets.csv
work/code_analysis/executables/arm9.bin
work/code_analysis/executables/arm7.bin
work/code_analysis/executables/overlays/overlay_000.bin ... overlay_033.bin
```

Current indexed totals:

```text
static-initializer pointer entries: 158
ASCII strings:                      2,125
Ghidra import targets:              36
```

The 36 import targets are ARM9, ARM7, and all 34 decoded ARM9 overlays.

See [`docs/code_reverse_engineering.md`](docs/code_reverse_engineering.md).

### Important overlay-editing limitation

The files under:

```text
work/code_analysis/executables/overlays/
```

are **decoded analysis copies**.

Editing one of those files does **not** currently patch the retail ROM automatically. A complete executable mod pipeline still needs to perform:

```text
decoded overlay edit
        ↓
BLZ recompression
        ↓
replace/update packed overlay bytes
        ↓
update any required overlay/FAT metadata
        ↓
rebuild ROM
        ↓
validate
```

That is separate from the already working graphics archive rebuild path.

---

# 7. Capture Select end goal

The current reverse-engineering target is deliberately broader than merely finding the capture minigame engine.

The desired final feature is approximately:

```text
Main Menu
├── Continue
├── New Game
└── Capture Select
    ├── Capture 0001
    ├── Capture 0002
    ├── ...
    └── every launchable capture in the game
```

To do this correctly, the project needs to distinguish at least two concepts:

## Capture definition

The data describing what happens inside a capture, for example:

- species / form / variant
- model/resources
- capture parameters
- attack/behaviour parameters
- boss/special flags
- arena/environment resources
- other encounter-specific state

## Capture trigger

The event that requests the capture, for example:

- story script
- map event
- mission event
- cutscene
- interaction
- scripted boss phase
- tutorial progression

The same underlying capture definition may be reachable from more than one trigger.

The intended long-term database should therefore be able to represent both, for example:

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

The preferred implementation is to identify a **high-level capture dispatcher/launcher** that performs the required setup. Calling the innermost capture engine blindly is risky because normal event code may initialize resources, target state, player state, return destinations, boss flags, difficulty values, and other context before entering the capture scene.

---

# 8. Dynamic capture tracing setup

The first live target chosen for tracing is the very first introductory capture: **Spearow**, National Pokédex ID **21 / `0x0015`**.

Early notes accidentally referred to the target as Starly. That was corrected: the actual intro capture being traced is Spearow.

## DeSmuME GDB stub

The distribution DeSmuME build being used did not expose the required GDB functionality, so a source build with the GDB stub enabled was used.

The CLI build accepts:

```bash
desmmume-cli --arm9gdb 3333 guardian_signs_debug.nds
```

The exact local executable used during research was built from DeSmuME source under a separate local checkout and launched as:

```bash
./build/cli/desmume-cli \
  --arm9gdb 3333 \
  /path/to/Pokengineering/work/debug/guardian_signs_debug.nds
```

Connect with:

```bash
arm-none-eabi-gdb
```

then:

```gdb
set architecture arm
target remote localhost:3333
```

The initial ARM9 stop was:

```text
PC = 0x02000800
```

which exactly matches the ARM9 entry point recovered independently from the Nintendo DS header.

A local GDB installation may print a Python warning similar to:

```text
cannot import name 'INTENSITY_BOLD' from '_gdb'
```

This only limits GDB's Python integration; ordinary register, memory, breakpoint and disassembly commands used in this research still work.

---

# 9. Why DeSmuME itself was instrumented

Hardware watchpoints exposed through the DeSmuME GDB stub were not reliable enough for this task. GDB could create a watchpoint, but the emulator did not consistently stop/report when the watched location changed.

Normal execution breakpoints work much better.

To get exact write PCs for live ARM9 memory fields, the local DeSmuME source was therefore instrumented in `MMU.cpp` inside the ARM9 `write32` callback.

The instrumentation prints values such as:

```text
address
value being written
ARM9 instruction address / PC
LR
SP
```

This turned the emulator itself into a precise memory-write tracer.

The DeSmuME modification is currently a local research aid rather than a checked-in dependency of Pokengineering.

---

# 10. First RAM-diff pass: searching for Spearow ID 21

Two snapshots of the overlay window were initially captured:

```gdb
dump binary memory /tmp/starly_before.bin 0x020d00c0 0x02130000
dump binary memory /tmp/starly_during.bin 0x020d00c0 0x02130000
```

The filenames retain the early mistaken `starly` name.

Overlay matching showed that overlay 3 matched its decoded image at essentially 100% both before and during the capture. This established that overlay 3 remained resident through the transition. It does **not** by itself prove that overlay 3 is the capture engine.

Full 4 MiB main-RAM snapshots were then captured:

```gdb
dump binary memory /tmp/starly_full_before.bin  0x02000000 0x02400000
dump binary memory /tmp/starly_full_during.bin  0x02000000 0x02400000
```

A search for newly appearing 16-bit and 32-bit values equal to Spearow's ID, `21`, produced multiple candidates.

Especially interesting 32-bit hits included:

```text
0x020C73B4
0x021AF89C
0x0222F104
0x0222F22C
0x023526D4
```

The first field selected for direct tracing was:

```text
0x0222F104
```

---

# 11. `0x0222F104`: exact writer found

DeSmuME instrumentation showed:

```text
[CAPTURETRACE] WRITE32 addr=0222F104 val=00000000 pc=02079C3C lr=020685E8
[CAPTURETRACE] WRITE32 addr=0222F104 val=00000000 pc=02079C3C lr=020685E8
[CAPTURETRACE] WRITE32 addr=0222F104 val=00000015 pc=02018648 lr=0201A7B8
```

This established the exact instruction writing `21`:

```text
writer PC = 0x02018648
```

The relevant runtime ARM function is:

```asm
02018624: push {r4, lr}
02018628: add  r0, r0, r2, lsl #2
0201862c: add  r0, r0, #8192
02018630: ldr  r0, [r0, #872]
02018634: mov  r4, r1
02018638: cmp  r0, #0
0201863c: moveq r0, #0
02018640: popeq {r4, pc}
02018644: blx  r0
02018648: str  r4, [r0, #8]
0201864c: pop  {r4, pc}
```

Conceptually:

```c
object = callback_from_table(base, index)();
object->field_08 = original_r1;
```

During the Spearow trace:

```text
original r1 = 21
```

At first the live `LR` value appeared to point at `0x0201A7B8`, but this was misleading because the function itself performs `BLX r0` before the store, altering `LR`.

Because the function begins with:

```asm
push {r4, lr}
```

the original caller return address could instead be recovered from the stack at the moment of the store.

The saved return address was:

```text
saved LR = 0x0201A5DC
```

and the direct call is therefore:

```asm
0201A5D8: bl 0x02018624
0201A5DC: ...
```

---

# 12. Controlled experiment: Spearow name changed to Starly, fight did not

A critical experiment was performed in the DeSmuME `write32` hook:

```text
if address == 0x0222F104 and value == 21:
    replace value with 396
```

where:

```text
21  = Spearow
396 = Starly
```

Result:

```text
displayed Pokémon name: Starly
text references:         Starly
visual Pokémon model:    still Spearow
capture behaviour:       still Spearow
actual fight:             still the original Spearow fight
```

This is an important negative result.

It proves that `0x0222F104` is **not sufficient to select the actual capture encounter**. It appears to be a live species/name/identity field used by UI/text logic, while the gameplay/model/behaviour state is controlled elsewhere.

This prevented the project from incorrectly declaring the first `21` field to be the capture selector.

---

# 13. Tracing the caller of the species/name setter

The wrapper around `0x02018624` is:

```asm
0201A5CC: push {r3, r4, r5, lr}
0201A5D0: mov  r5, r0
0201A5D4: ldr  r0, [r5, #56]
0201A5D8: bl   0x02018624
0201A5DC: movs r4, r0
...
```

`r1` and `r2` are passed through to the setter unchanged.

Searching direct callers of `0x0201A5CC` found three branches inside the same parser:

```text
0x0201A2CC  with r2 = 1
0x0201A328  with r2 = 2
0x0201A388  with r2 = 3
```

The parser begins at approximately `0x0201A264` and reads a packed record through `r9`:

```asm
0201A28C: ldrh r0, [r9, #2]
0201A290: ldrh r1, [r9]
0201A294: ldrh r5, [r9, #4]
0201A298: cmp  r0, #1
0201A29C: ldrh r6, [r9, #6]
0201A2A0: ldrh r7, [r9, #8]
0201A2A4: ldrh r8, [r9, #10]
0201A2A8: add  r9, r9, #12
```

This gives a base 12-byte record layout:

```text
+0x00  u16  species / ID passed into live species object creation
+0x02  u16  record type (observed 1, 2, 3)
+0x04  u16  parameter A
+0x06  u16  parameter B
+0x08  u16  parameter C
+0x0A  u16  parameter D
```

The type-specific branches consume additional bytes after the 12-byte header:

```text
type 1: consumes another 8 bytes
type 2: consumes another 4 bytes
type 3: consumes another 4 bytes
```

At this point it looked plausible that this might be an encounter-definition format. The next GDB experiment showed that interpretation was too optimistic.

---

# 14. Exact Spearow record found in RAM

A GDB breakpoint was placed at:

```text
0x0201A28C
```

The breakpoint was then conditioned on:

```gdb
*(unsigned short *)$r9 == 21
```

When it stopped, the Spearow record was located at:

```text
r9 = 0x0222D1A8
```

The six base halfwords were:

```text
21, 1, 43, 176, 8, 16
```

Raw bytes:

```text
15 00  01 00  2B 00  B0 00  08 00  10 00
```

The following bytes were:

```text
06 00 00 00 01 00 00 00
```

which fit the extra 8-byte payload consumed by the type-1 branch.

The complete observed 20-byte Spearow record is therefore:

```text
15 00 01 00 2B 00 B0 00 08 00 10 00 06 00 00 00 01 00 00 00
```

Immediately after it, memory begins:

```text
16 00 01 00 ...
```

where:

```text
0x0016 = 22 = Fearow
```

This adjacency is strong evidence that the parser is walking a **species-definition database/table**, not a one-off story encounter table.

That was another useful correction: it stopped us from confusing globally loaded per-species data with the actual capture trigger.

---

# 15. Species lookup routine `0x0201A5F8`

The function beginning at:

```text
0x0201A5F8
```

loops through live species objects and compares the requested ID against the field at object offset `+0x08`:

```asm
0201A618: ldr  r0, [ip, r3, lsl #2]
0201A61C: cmp  r0, #0
0201A620: beq  ...
0201A624: ldr  r2, [r0, #8]
0201A628: cmp  r1, r2
```

A conditional breakpoint was placed on entry:

```gdb
break *0x0201A5F8
condition <breakpoint> $r1 == 21
```

During the Spearow capture load, the breakpoint hit with:

```text
r0 = 0x0222CF44
r1 = 0x00000015  (21)
r2 = 0x00000015  (21)
r3 = 0
lr = 0x02016CAC
sp = 0x027E36F0
pc = 0x0201A5F8
```

The direct caller is:

```asm
02016CA4: mov r1, r2
02016CA8: bl  0x0201A5F8
02016CAC: cmp r0, #0
```

The enclosing function begins at:

```text
0x02016C84
```

and receives the species ID directly in `r2`:

```asm
02016C84: push {r4, lr}
02016C88: ldr  ip, [pc, #60]
02016C8C: mov  r4, r3
02016C90: mla  r0, r1, ip, r0
02016C94: add  r0, r0, #4096
02016C98: ldr  r0, [r0, #604]
02016C9C: cmp  r0, #0
02016CA0: popeq {r4, pc}
02016CA4: mov  r1, r2
02016CA8: bl   0x0201A5F8
02016CAC: cmp  r0, #0
02016CB0: popeq {r4, pc}
02016CB4: ldr  r1, [r0, #12]
02016CB8: cmp  r1, #1
02016CBC: popne {r4, pc}
02016CC0: mov  r1, r4
02016CC4: bl   0x0201A96C
02016CC8: pop  {r4, pc}
```

This is more gameplay-adjacent than the text/name field because it retrieves a live species object, checks its state/type at `+0x0C`, and conditionally applies another operation.

However, the next caller trace showed that this particular Spearow lookup still was not the unique story encounter trigger.

---

# 16. Stack recovery led into ARM9 overlay 3

At the conditional species-21 breakpoint, `0x02016C84` had already executed:

```asm
push {r4, lr}
```

Therefore its original caller return address remained saved at `[sp+4]`.

GDB showed:

```text
[sp+4] = 0x020D71DC
```

This address lies inside **ARM9 overlay 3**, whose runtime image begins at:

```text
0x020D00C0
```

Disassembling overlay 3 around the call revealed:

```asm
020D717C: mov r1, #1
020D7180: mov r2, #23
020D7188: bl  0x02016C84

020D71A4: mov r1, #1
020D71A8: mov r2, #22
020D71AC: bl  0x02016C84

020D71CC: mov r1, #1
020D71D0: mov r2, #21
020D71D8: bl  0x02016C84

020D71EC: mov r1, #1
020D71F0: mov r2, #20
020D71F8: bl  0x02016C84

020D7218: mov r1, #1
020D721C: mov r2, #19
020D7224: bl  0x02016C84
```

This is decisive context.

The overlay is explicitly applying the same helper to a **sequence of species IDs** (`23`, `22`, `21`, `20`, `19`, ...). Therefore the `21` call at `0x020D71D8` is not a unique "launch the intro Spearow encounter" instruction.

It is a generic species-processing routine that happens to include Spearow in its sequence.

This finding prevented another false-positive call chain from being mistaken for the capture dispatcher.

---

# 17. Runtime ARM9 image versus on-disk `arm9.bin`

When the first writer address (`0x02018648`) was disassembled against the repository's on-disk `arm9.bin`, the result did not match the valid code executing in RAM.

A runtime ARM9 image was therefore extracted directly from the 4 MiB RAM snapshot:

```bash
mkdir -p work/code_analysis/runtime

dd \
  if=/tmp/starly_full_during.bin \
  of=work/code_analysis/runtime/arm9_runtime.bin \
  bs=1 \
  count=421012 \
  status=none
```

The size `421012` matches the executable size from the DS header.

Runtime disassembly is then performed with:

```bash
arm-none-eabi-objdump \
  -D -b binary -m arm \
  --adjust-vma=0x02000000 \
  work/code_analysis/runtime/arm9_runtime.bin
```

For convenience, a full text disassembly can be generated with:

```bash
arm-none-eabi-objdump \
  -D -b binary -m arm \
  --adjust-vma=0x02000000 \
  work/code_analysis/runtime/arm9_runtime.bin \
  > work/code_analysis/runtime/arm9_runtime.asm
```

The exact reason for every difference between the stored ARM9 representation and the live runtime image has not yet been fully characterized, so the project should not assume that arbitrary runtime ARM9 patches can simply be written at the same offset in `arm9.bin` without further analysis.

---

# 18. Current address map for capture research

The most important live addresses discovered so far are:

| Address | Current interpretation | Confidence / evidence |
|---|---|---|
| `0x0222F104` | Live species/name field | **Confirmed behaviorally**: changing 21→396 changes displayed name to Starly but not model/fight |
| `0x02018648` | Writer of `object+0x08` for the above field | **Confirmed by DeSmuME write instrumentation** |
| `0x02018624` | Generic object field setter/helper | **Confirmed by runtime disassembly** |
| `0x0201A5CC` | Wrapper around `0x02018624` | **Confirmed by runtime disassembly** |
| `0x0201A264` | Parser for variable-length species records | **Strongly supported by record walk and sequential species data** |
| `0x0222D1A8` | Spearow species record in loaded table | **Confirmed by conditional GDB breakpoint** |
| `0x0201A5F8` | Lookup live object by species ID at object `+0x08` | **Confirmed by disassembly and conditional breakpoint** |
| `0x02016C84` | Helper receiving species ID in `r2`, then looking up live species object | **Confirmed by disassembly** |
| `0x020D71D8` | Overlay-3 call with hard-coded `r2=21` | **Confirmed, but rejected as unique encounter trigger** because adjacent calls process 23,22,20,19 etc. |
| `0x0222F22C` | Second 32-bit RAM field that newly becomes `21` during the capture | **Unresolved; next high-value experiment** |

Other `21` hits observed during the original full-RAM diff remain candidates, but they are lower priority until stronger causal evidence is available.

---

# 19. Current next experiment: `0x0222F22C`

The most interesting unresolved 32-bit hit is:

```text
0x0222F22C
```

It is notable because:

```text
0x0222F22C - 0x0222F104 = 0x128
```

Both addresses became `21` during the same capture load, suggesting that they may be analogous fields in related structures, duplicated capture-state blocks, or separate UI/gameplay representations.

The next controlled experiment is intentionally narrow:

```text
leave 0x0222F104 untouched
change only writes of 21 to 0x0222F22C into 396
```

Then compare independently:

```text
displayed name
Pokémon model
capture behaviour
fight parameters
```

If changing only `0x0222F22C` changes the actual capture model/behaviour, it becomes a much stronger candidate for the gameplay-side species/encounter field.

If it does not, the write PC still identifies the subsystem that owns the second copy, which is useful evidence for the next trace.

---

# 20. What has been ruled out

The capture investigation has already eliminated several tempting but incorrect conclusions:

### `0x0222F104` is not the complete capture selector

It controls displayed species identity/name strongly enough to make the game say "Starly", but the fight remains Spearow.

### The `0x0222D1A8` Spearow record is not necessarily the intro encounter definition

It is immediately followed by Fearow (`22`) and was discovered while a parser walked a sequential species database. It is much more likely to be globally loaded per-species data.

### `0x020D71D8` is not the unique Spearow launch trigger

Overlay 3 calls the same helper for a descending sequence of species IDs around it.

### Overlay 3 remaining resident is not proof that overlay 3 is "the capture overlay"

The before/during binary match only shows that it was resident and unchanged across the observed transition.

### Logged LR values after an indirect `BLX` cannot automatically be treated as the direct caller

The original caller had to be recovered from the saved stack frame instead.

These negative results are deliberately documented because they prevent future work from repeating the same false trails.

---

# 21. Practical GDB techniques that have worked

## Conditional breakpoint on species table parsing

```gdb
break *0x0201A28C
condition 1 *(unsigned short *)$r9 == 21
continue
```

Inspect the record:

```gdb
info registers r9
x/6uh $r9
x/24bx $r9
```

## Conditional breakpoint on species lookup

```gdb
break *0x0201A5F8
condition 2 $r1 == 21
continue
```

Inspect call state:

```gdb
info registers r0 r1 r2 r3 lr sp pc
x/16i $lr-32
```

## Recover saved caller LR from a known prologue

If the current function began with:

```asm
push {r4, lr}
```

then while stopped deeper inside it:

```gdb
x/wx $sp+4
```

can recover the original return address, provided the stack frame has not been rearranged in the intervening path.

This was how the overlay-3 caller at `0x020D71DC` was found.

---

# 22. ARM disassembly commands used during the trace

Disassemble a runtime ARM9 range:

```bash
arm-none-eabi-objdump \
  -D -b binary -m arm \
  --adjust-vma=0x02000000 \
  --start-address=0x020185E0 \
  --stop-address=0x020186B0 \
  work/code_analysis/runtime/arm9_runtime.bin
```

Disassemble decoded overlay 3 at its runtime address:

```bash
arm-none-eabi-objdump \
  -D -b binary -m arm \
  --adjust-vma=0x020D00C0 \
  --start-address=0x020D7140 \
  --stop-address=0x020D7240 \
  work/code_analysis/executables/overlays/overlay_003.bin
```

Search a generated ARM9 disassembly for direct callers:

```bash
grep -n -B 12 -A 12 'bl.*201a5cc' \
  work/code_analysis/runtime/arm9_runtime.asm
```

These simple static searches have been used together with live GDB register state rather than relying on static disassembly alone.

---

# 23. Research method being used

The capture work follows a deliberately evidence-driven loop:

```text
1. Observe a real capture in the unmodified game.
2. Snapshot or instrument relevant memory.
3. Find candidate values associated with the target species/event.
4. Trace exact writers/readers at runtime.
5. Recover callers using breakpoints and stack frames.
6. Disassemble only the functions/overlays implicated by runtime evidence.
7. Perform a controlled mutation.
8. Compare name/model/behaviour/fight independently.
9. Reject fields that only affect presentation or generic species processing.
10. Move one layer higher toward the event/dispatcher that actually selected the capture.
```

The controlled-mutation step is particularly important. Seeing `21` in memory is not enough; Guardian Signs stores species IDs in many places for text, resources, global species data and active state. A field is only promoted to a strong capture-selector candidate after changing it produces the expected gameplay effect.

---

# 24. Remaining work before Capture Select is possible

The main technical milestones still ahead are:

1. **Identify the gameplay-side field or request structure that actually selects the active capture.**
2. **Find the writer/caller chain for that field.**
3. **Trace backward into the story/map/script/event system.**
4. **Identify a reusable high-level capture-launch function or dispatcher.**
5. **Determine all required launch parameters and preconditions.**
6. **Determine result/return handling so a menu-launched capture can exit cleanly.**
7. **Enumerate every capture definition and every trigger in the game.**
8. **Determine whether duplicate triggers share a capture definition.**
9. **Create a machine-readable capture database in the repository.**
10. **Implement an executable/overlay patch pipeline capable of reinserting modified code reliably.**
11. **Add a new main-menu entry and capture-selection UI.**
12. **Launch each capture through the discovered dispatcher with correct context.**
13. **Regression-test normal story progression so the new menu path does not break ordinary gameplay.**

---

# 25. Suggested future capture database

Once the dispatcher and source data are identified, captures should be recorded in a reproducible dataset rather than left as handwritten notes.

A possible schema is:

```text
capture_id
species_id
species_name
form_or_variant
capture_definition_source
capture_definition_offset
trigger_type
trigger_source
trigger_offset
map_id
mission_id
story_flags
launch_function
launch_overlay
launch_arguments
required_prestate
capture_parameters
return_handler
return_destination
verified_in_game
notes
```

The distinction between `capture_definition_*` and `trigger_*` is intentional.

---

# 26. Tests and validation

Existing repository validation includes localization, ROM reconstruction, archive cataloguing, graphics parsing/rendering and executable analysis.

Useful commands include:

```bash
bash tools/test_localization_roundtrip.sh
bash tools/test_rom_rebuild.sh
bash tools/test_game_acf_catalog.sh
bash tools/analyze_game_code.sh
```

Additional graphics-specific regression tools and CI jobs were added during the graphics milestones.

The executable analysis has also been validated against the real retail component set, including successful decoding of all 34 overlays.

---

# 27. Development history / merged milestones

The recent reverse-engineering progression is represented by the merged pull requests:

```text
PR #7   complete current project snapshot
PR #8   deterministic Nitro graphics preview renderer
PR #9   physical-extent fix for retail NCGR previews
PR #10  lossless NCER sprite edit round-trip
PR #11  end-to-end graphics mod build automation
PR #12  automatic graphics identification index
PR #13  ARM9 / overlay executable code map and BLZ decoding
```

PR #13 is the milestone that made the current capture-engine work practical by producing runtime-address-aware ARM9/overlay analysis targets.

---

# 28. Repository policy

The priority is **recoverability and reproducibility**.

Anything unique to the project—source code, reverse-engineering notes, confirmed addresses, patch logic, analysis scripts, format knowledge, machine-readable registries and other irreplaceable work—should be committed to GitHub rather than existing only on one development machine.

Large disposable outputs such as temporary RAM dumps, regenerated preview caches and rebuilt emulator ROMs can remain local when they can be reproduced from repository state.

The repository already contains the component data required to reconstruct the working analysis ROM; the original `.nds` file itself is not required for day-to-day project recovery.

Dynamic research that currently exists only as local emulator instrumentation should be converted into a documented patch/script or repository tool once the instrumentation stabilizes.

---

# 29. Current handoff point

If development is resumed from this README, the highest-value immediate task is:

> **Instrument writes to `0x0222F22C`, leave `0x0222F104` unchanged, and test whether replacing only `21` with `396` changes the actual Spearow capture model/behaviour.**

The expected comparison is:

```text
                         original       F104 experiment       F22C experiment
species text/name        Spearow        Starly                ?
model                    Spearow        Spearow               ?
behaviour/fight          Spearow        Spearow               ?
```

If `0x0222F22C` changes gameplay, trace its writer immediately.

If it only changes another presentation/state copy, keep its writer PC as evidence and continue searching for the state that determines model/behaviour.

The core rule for the rest of this reverse engineering effort is simple:

> **Do not treat a species ID in memory as the capture trigger until a controlled mutation proves that it controls the actual encounter.**
