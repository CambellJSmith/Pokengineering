# NCER sprite editing

The first identified Guardian Signs sprite-edit target is preview `G00583__bank_0001`.

Its source resources are:

- NCLR palette: `acf:2140/acf:0001` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0001.nclr`
- NCGR graphics: `acf:2140/acf:0002` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0002.ncgr`
- NCER cell bank: `acf:2140/acf:0003` -> `work/game_acf/graphics_catalog/payloads/acf_2140__acf_0003.ncer`
- Identified bank: `1`

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

## Re-encode

After editing the files in `pieces/`, run:

```bash
python3 tools/edit_ncer_sprite.py import \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0002.ncgr \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0001.nclr \
  work/game_acf/graphics_catalog/payloads/acf_2140__acf_0003.ncer \
  work/game_acf/mods/G00583_bank_0001 \
  work/game_acf/mods/G00583_bank_0001/acf_2140__acf_0002.modified.ncgr
```

The importer verifies that the source NCGR/NCLR/NCER hashes still match the export manifest. It rejects changed dimensions, colors outside the assigned NCLR palette, partial alpha, changed indexed palettes, and unsafe source-layout conflicts.

## Round-trip invariant

CI exports bank 1 of this exact retail asset and immediately imports the untouched indexed PNG pieces. The rebuilt NCGR must be byte-identical to the original. This establishes a lossless edit boundary before any replacement/repacking work begins.

The flattened `reference_bank_0001.png` is deliberately not importable: NCER OAM pieces can overlap or be reused with flips, so flattening destroys source information. Editing the source-piece PNGs preserves the actual NCGR layout.
