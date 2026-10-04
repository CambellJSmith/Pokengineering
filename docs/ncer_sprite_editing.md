# NCER sprite editing

The first identified Guardian Signs sprite-edit target is preview `G00583__bank_0001`.

Its source resources are:

- NCLR palette: `acf:2140/acf:0001` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0001.nclr`
- NCGR graphics: `acf:2140/acf:0002` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0002.ncgr`
- NCER cell bank: `acf:2140/acf:0003` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0003.ncer`
- Identified bank: `1`

The source mapping and its in-game verification state are recorded in `docs/confirmed_graphics_assets.json`. The exact semantic name of the object is intentionally left unset until it is identified explicitly.

## Prepare the edit workspace

Run:

```bash
bash tools/prepare_g00583_sprite_mod.sh
```

This creates `work/game_acf/mods/G00583_bank_0001/` with:

- `reference_bank_0001.png` — the flattened rendered sprite for visual reference only.
- `pieces/*.png` — the editable source graphics pieces.
- `manifest.json` — exact byte ranges, palette-bank assignments, OAM users, and source hashes.
- `README.txt` — short editing rules.

The piece PNGs are indexed 16-color images. They retain the actual NCGR palette indices, including duplicate palette colors that cannot be represented safely by RGB matching alone. Keep their dimensions and palette intact while editing.

## Build the edited game

After editing the files in `pieces/`, the complete path from PNG to validated Nintendo DS image is now one command:

```bash
bash tools/build_g00583_mod.sh
```

The wrapper calls the manifest-driven `tools/build_graphics_mod.py` builder. It:

1. imports the edited source-piece PNGs and rebuilds the NCGR;
2. replaces child `0002` inside nested ACF `2140`;
3. rebuilds the nested ACF and extracts it again to verify the replacement NCGR byte-for-byte;
4. replaces top-level ACF entry `2140` and rebuilds `data_game_us.acf`;
5. replaces `data/data_game_us.acf` in a reconstructed Nintendo DS image;
6. validates the rebuilt image and checks that its NitroFS copy of `data_game_us.acf` exactly matches the rebuilt archive; and
7. writes `build_summary.json` into the edit workspace with SHA-256 hashes for the rebuilt layers.

The default ROM output is:

```text
work/guardian_signs_G00583_mod.nds
```

Use `--skip-rom` to stop after rebuilding `data_game_us.acf`, or `--full-rom` to retain full cartridge padding instead of the default trimmed image.

The underlying generic entry point is:

```bash
python3 tools/build_graphics_mod.py G00583
```

Future confirmed assets can be added to `docs/confirmed_graphics_assets.json` and use the same builder when they follow the supported nested-ACF/NCER sprite topology.

## Manual re-encode only

If only the NCGR is wanted, without repacking the game, run:

```bash
python3 tools/edit_ncer_sprite.py import \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0002.ncgr \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0001.nclr \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0003.ncer \
  work/game_acf/mods/G00583_bank_0001 \
  work/game_acf/mods/G00583_bank_0001/acf_2140__acf_0002.modified.ncgr
```

The importer verifies that the source NCGR/NCLR/NCER hashes still match the export manifest. It rejects changed dimensions, colors outside the assigned NCLR palette, partial alpha, changed indexed palettes, and unsafe source-layout conflicts.

## Verified milestone

On 2026-10-04 an edited `16x32` source piece from `G00583__bank_0001` was rebuilt through the full chain — NCGR, nested ACF, `data_game_us.acf`, and Nintendo DS image — and the modification appeared in-game while the rebuilt game remained playable. This establishes the first end-to-end graphics-mod proof for the project.

## Round-trip invariant

CI exports bank 1 of this exact retail asset and immediately imports the untouched indexed PNG pieces. The rebuilt NCGR must be byte-identical to the original. This establishes a lossless edit boundary before any replacement/repacking work begins.

The flattened `reference_bank_0001.png` is deliberately not importable: NCER OAM pieces can overlap or be reused with flips, so flattening destroys source information. Editing the source-piece PNGs preserves the actual NCGR layout.
