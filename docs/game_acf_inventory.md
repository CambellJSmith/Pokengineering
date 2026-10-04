# Guardian Signs Game ACF Inventory

This milestone inventories the US retail `data/data_game_us.acf` archive from *Pokémon Ranger: Guardian Signs* without committing extracted game payloads.

## Source

The archive is Nintendo DS FAT file ID `0x22`. The repository's checked-in `data/` payloads are known to be misaligned, so `tools/extract_game_data.sh` reconstructs the archive directly from:

```text
fat_data.bin
fat.bin
_file_IDs.txt
```

The validated source archive is 24,623,828 bytes and begins with the expected `acf\0` signature.

## Measured Top-Level Inventory

The CI-backed inventory currently reports:

| Type | Count |
| --- | ---: |
| Total ACF slots | 9,689 |
| Real entries | 9,458 |
| Unused entries | 231 |
| Confidently recognized entries | 6,730 |
| Unknown entries | 2,728 |
| Repeated unknown clusters | 20 |
| Extracted/decompressed payload bytes | 54,044,313 |

Recognized top-level formats:

| Format | Count |
| --- | ---: |
| NCGR graphics | 1,679 |
| NCLR palettes | 1,545 |
| Nested ACF archives | 1,110 |
| NARC archives | 790 |
| NSCR screens | 662 |
| NCER cells | 472 |
| NANR animations | 472 |

These counts are generated from file signatures after `acftool` has extracted/decompressed the top-level ACF.

## Measured Recursive Inventory

The recursive pass follows every directly recognized ACF/NARC container and NARC signatures embedded behind short wrapper headers. It preserves every top-level slot and adds each reachable child as another catalogue row.

The CI-backed recursive inventory reports:

| Type | Count |
| --- | ---: |
| Total inventory rows | 26,951 |
| Real entries | 26,720 |
| Unused entries | 231 |
| Recognized entries | 14,603 |
| Unknown entries | 12,117 |
| Extracted/inventoried payload bytes | 86,696,168 |
| Maximum logical depth | 4 |
| Parsed ACF containers | 1,110 |
| Parsed NARC containers | 2,364 |
| Container parse errors | 0 |

Recursive effective format counts:

| Format | Count |
| --- | ---: |
| Unknown | 12,117 |
| NCER cells | 3,710 |
| NCGR graphics | 3,630 |
| NCLR palettes | 2,655 |
| NARC archives | 1,577 |
| ACF archives | 1,110 |
| Embedded/wrapped NARC archives | 787 |
| NSCR screens | 662 |
| NANR animations | 472 |

The 1,577 direct NARC signatures plus 787 embedded/wrapped NARC signatures account for all 2,364 NARC containers parsed by the recursive walk. The wrapper case is significant: stopping at files whose first four bytes were not `NARC` would have left 787 archives unexpanded.

The deepest reachable container path is four logical levels below the root inventory. No reachable ACF or NARC container failed structural validation, and CI verifies that recursion did not stop because of a cycle or the depth limit.

No additional raw NARC child required LZ10 decoding in the measured retail archive. The recursive implementation still supports LZ10-wrapped child containers, and CI exercises that path with synthetic nested ACF/NARC fixtures.

## Stable Logical Paths

`recursive_catalog.csv` gives each resource a stable path derived from its parent container type and numeric slot rather than from temporary extracted filenames. Examples have this form:

```text
acf:0123
acf:0123/acf:0007
acf:0456/narc:0012
acf:0456/narc:0012/narc:0003
```

Every non-root row records its `parent_path`, and CI requires all logical paths to be unique and all parents to exist. This gives later reverse-engineering work a durable identifier for correlating assets with ARM9/overlay loading code and for targeting replacements.

Wrapped containers keep the wrapper entry as its own logical row. Their children are then appended beneath that row using the parsed container type, so the wrapper's identity and the NARC's internal slot numbers are both preserved.

## What This Tells Us

The game archive is dominated by the standard Nintendo DS 2D graphics stack:

```text
NCGR  character/tile graphics
NCLR  palettes
NSCR  tile maps/screens
NCER  sprite cell/layout data
NANR  sprite animation data
```

Recursive traversal substantially increases the visible NCGR/NCLR/NCER population, confirming that many graphics sets are organized inside nested containers rather than only in the top-level ACF.

The container topology is also more structured than the top-level catalogue alone showed. The retail archive contains both ordinary NARCs and a large family of NARCs behind short wrapper headers. Recursing through those wrappers extends the observed hierarchy to depth 4 while remaining structurally valid across all 2,364 NARCs and 1,110 ACFs.

No `BMD0`, `BTX0`, `BCA0`, `BTA0`, `BTP0`, `BMA0`, or `BVA0` effective signatures were found anywhere in the reachable recursive ACF/NARC inventory. That still does not prove the game lacks those resource types: they may use proprietary wrappers beyond the current short embedded-magic scan, live outside this game ACF, or use formats not yet recognized.

The unknown count rises from 2,728 at the top level to 12,117 recursively because the inventory now exposes thousands of previously hidden child files. Those unknowns are a much better reverse-engineering target than the original flat list because each now carries a parent path, archive neighborhood, depth, size, hash, and signature metadata.

## Local Workflow

Build the pinned extraction tools once:

```bash
bash tools/setup_guardian_tools.sh
```

Extract and catalogue the game ACF:

```bash
bash tools/extract_game_data.sh
```

The ignored local workspace is:

```text
work/game_acf/
├── source_data_game_us.acf
├── original.acf
├── archive/
│   ├── filelist.json
│   └── ...extracted entries...
└── analysis/
    ├── catalog.csv
    ├── unknown_clusters.csv
    ├── summary.json
    ├── recursive_catalog.csv
    └── recursive_summary.json
```

`catalog.csv` includes, for every top-level slot:

- ACF index and extracted filename;
- raw/compressed/unused state from `filelist.json`;
- extracted size and SHA-256;
- Shannon entropy and printable-byte ratio;
- first 16 bytes as hexadecimal metadata;
- printable four-byte magic when present;
- detected known format and embedded-magic offset;
- initial little-endian 16-bit/32-bit values;
- size alignment hints; and
- an unknown-cluster key.

`recursive_catalog.csv` adds parent/child logical paths, depth, parent container type, decoded-format metadata, container type and child count, plus parse/decode status for every reachable ACF/NARC descendant.

`unknown_clusters.csv` groups repeated top-level unknown binary prefixes so likely families of proprietary records can be investigated together instead of one file at a time.

## Classification Policy

Known formats are identified conservatively by their file signatures. Nintendo compressed-stream detection uses Nitro compression type bytes plus decoded-size validation before attempting decompression. The recursive layer also validates LZ10 streams itself so valid literal-heavy streams are not excluded solely because they expand poorly.

Direct ACF/NARC containers are parsed only after exact signature checks. Embedded ACF/NARC candidates are limited to signatures discovered by the existing short-prefix scan, then must pass the same structural parser as direct containers. CI fails on any detected container that cannot be parsed, which prevents an incidental byte sequence from silently becoming part of the recursive tree.

The catalogue is heuristic metadata, not a claim that every file's gameplay purpose is known. Archive paths and neighborhoods now provide the context needed for that semantic reverse engineering.

## Next Reverse-Engineering Layer

With recursive container discovery complete, the highest-value next steps are:

1. group adjacent NCGR/NCLR/NSCR/NCER/NANR children by parent path and slot neighborhood into likely graphics sets;
2. classify the 787 NARC wrapper headers to determine whether they carry IDs, flags, or other semantic metadata;
3. rank the 12,117 remaining unknown child files by repeated prefix, parent archive, size regularity, entropy, and neighboring recognized resources;
4. identify a visually obvious graphics set and perform the first non-text in-game replacement;
5. trace that asset's stable logical path back into ARM9/overlay resource-loading code; and
6. use those loader relationships to begin assigning semantic names to archive families and proprietary tables.

The recursive inventory means unknown files no longer need to be reverse engineered as isolated top-level blobs. They can now be investigated in the exact container and neighborhood where the game stores them.
