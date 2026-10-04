# Guardian Signs code reverse engineering

The project now treats the Nintendo DS executable code as a first-class reverse-engineering target rather than only cataloguing assets.

Guardian Signs stores its always-resident ARM9 program in `arm9.bin`, its ARM7 program in `arm7.bin`, its ARM9 overlay table in `a9ovr.bin`, and the packed ARM9 overlay payload region in `a9ovr_data.bin`. `fat.bin` supplies the physical ROM ranges referenced by each overlay-table file ID.

## Build the code map

From the repository root run:

```bash
bash tools/analyze_game_code.sh
```

The command writes `work/code_analysis/` with:

- `summary.json` — executable load addresses, entry points, overlay counts, compression counts, RAM-overlap groups, and hashes;
- `memory_map.csv` — resident ARM9/ARM7 regions and every ARM9 overlay RAM range;
- `overlays.csv` — overlay ID, FAT file ID, RAM address/size, BSS size, static-initializer range, compression metadata, physical ROM range, hash, and overlapping overlay IDs;
- `static_initializers.csv` — function-pointer seeds recovered from uncompressed overlays' static initializer tables, including ARM/Thumb state from the low address bit;
- `strings.csv` — printable ASCII strings with both file offsets and loaded RAM addresses for resident ARM9 and uncompressed overlays;
- `ghidra_targets.csv` — one row per standalone program to import, with the correct load address and Ghidra processor language;
- `executables/arm9.bin`, `executables/arm7.bin`, and `executables/overlays/*.raw.bin` — exact analysis inputs when the default extraction mode is used.

Use `--metadata-only` when only the tables are wanted:

```bash
bash tools/analyze_game_code.sh --metadata-only
```

## Why overlays must be separate programs

Nintendo DS ARM9 overlays are loaded into RAM only when needed. Multiple overlay IDs can occupy the same RAM window at different times, so importing every overlay into one flat address space would create false conflicts. The generated `overlaps_overlay_ids` field and `overlay_ram_overlap_groups` summary make that explicit.

Analyze `arm9` as the resident program and each overlay as its own Ghidra program. Cross-references between resident code and overlays should be recorded as project metadata rather than fabricated as simultaneously resident memory.

## Ghidra import settings

`ghidra_targets.csv` provides the intended settings. For ARM9 and ARM9 overlays use:

```text
Processor: ARM:LE:32:v5t
```

For ARM7 use:

```text
Processor: ARM:LE:32:v4t
```

Load each raw executable at the `load_address` listed in the CSV. ARM9 also has a known `entry_point` from the DS header.

The extracted root `arm9.bin` can contain footer data after the executable body. The analysis copy deliberately contains only the header-declared executable bytes so file offsets correspond directly to the loaded ARM9 image.

## Static initializer seeds

Each standard Nintendo DS overlay-table entry contains a start/end RAM range for the overlay's static initializer pointer table. For an uncompressed overlay, the analyzer converts that RAM range back to file offsets and records each pointer in `static_initializers.csv`.

The low bit of an ARM function pointer is the interworking state bit:

- low bit clear → ARM entry;
- low bit set → Thumb entry, with the actual code address equal to `pointer & ~1`.

These are high-value function seeds for automatic analysis and manual naming.

## Compressed overlays

The final overlay-table word carries a 24-bit compressed-size field and an 8-bit flags field. The analyzer records those fields and treats flag bit 0 as the standard Nitro overlay compression flag.

Compressed payloads are extracted verbatim, hashed, and mapped, but are deliberately marked `importable=False` in `ghidra_targets.csv`. Decompression is the next executable-tooling milestone if Guardian Signs actually uses compressed ARM9 overlays; inventing code addresses from compressed bytes would be incorrect.

## First substantive target

Once the retail memory map is generated, the next reverse-engineering target is the **capture subsystem**. The practical workflow is:

1. identify overlays that contain capture-screen or capture-mechanics strings/data references;
2. import those overlays and ARM9 into Ghidra at the generated addresses;
3. seed known entry points and static initializers;
4. trace callers and callees around capture-state setup/update/teardown;
5. name functions conservatively as their behavior is established;
6. commit symbols, notes, and reconstructed C-like behavior to the repository;
7. make a small gameplay modification to prove the mapped code path is correct.

That moves the project from resource replacement into actual engine reverse engineering and is directly useful for both gameplay mods and a later native reimplementation.
