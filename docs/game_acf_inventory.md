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

## What This Tells Us

The top-level game archive is dominated by the standard Nintendo DS 2D graphics stack:

```text
NCGR  character/tile graphics
NCLR  palettes
NSCR  tile maps/screens
NCER  sprite cell/layout data
NANR  sprite animation data
```

That is useful because those formats are already documented and can be converted independently of Guardian Signs-specific code.

The more important architectural result is the number of nested containers:

```text
1,110 ACF archives
790 NARC archives
```

The top-level ACF is therefore not a flat asset store. Much of the semantic organization is likely one or more levels deeper. A top-level unknown entry may also turn out to be a Guardian Signs-specific table or wrapper around a standard resource.

No top-level `BMD0`, `BTX0`, `BCA0`, `BTA0`, `BTP0`, `BMA0`, or `BVA0` signatures were found by the current classifier. That does not establish that the game lacks those resource types; they may be inside nested containers, wrapped in custom structures, or represented by formats not yet recognized.

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
    └── summary.json
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

`unknown_clusters.csv` groups repeated unknown binary prefixes so likely families of proprietary records can be investigated together instead of one file at a time.

## Classification Policy

Known formats are identified conservatively by their file signatures. Nintendo compressed-stream detection uses exact Nitro compression type bytes and validates the decoded-size header before classifying an entry. This avoids treating arbitrary files that merely begin with a common byte value as compressed streams.

The catalogue is heuristic metadata, not a claim that every file's gameplay purpose is known. Archive index neighborhoods and nested-container contents still need semantic reverse engineering.

## Next Reverse-Engineering Layer

The highest-value next step is recursive container inventory:

1. extract the 1,110 nested ACF archives and catalogue their children;
2. inventory NARC contents and map standard Nitro resources inside them;
3. preserve parent/child archive paths so every asset has a stable logical identifier;
4. correlate adjacent NCGR/NCLR/NSCR/NCER/NANR entries into likely graphics sets;
5. rank the remaining proprietary binary families by count, size regularity, entropy, and archive neighborhood;
6. identify a visually obvious asset set and perform the first non-text in-game replacement; and
7. use discovered archive/index relationships later when labeling ARM9 and overlay resource-loading functions.

The 2,728 top-level unknown entries should not all be reverse engineered independently. Nested-container analysis and neighborhood grouping should reduce that problem substantially before manual binary-format work begins.
