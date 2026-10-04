# Automatic graphics identification

Guardian Signs contains thousands of graphics resources whose raw archive positions do not provide semantic names. `tools/identify_graphics.py` builds a deterministic identification layer on top of the rendered preview catalogue.

It does **not** pretend to know a character/object name from pixels alone. Semantic names remain confirmed only when they are recorded explicitly in `docs/confirmed_graphics_assets.json`. The automatic layer instead answers the questions that can be established mechanically: which previews are exact duplicates, which share an alpha silhouette, which share the same NCGR source, which have the same resource/layout structure, which look unusually close to a confirmed asset, and whether the resource topology is sprite-, background-, or tile-sheet-like.

## Run it

A full graphics render is required because the identifier fingerprints the actual rendered RGBA pixels. If `work/game_acf/graphics_previews/` already contains the full preview render, run:

```bash
bash tools/identify_game_graphics.sh
```

If full preview PNGs do not exist yet, generate them first:

```bash
rm -rf work/game_acf/graphics_previews
bash tools/render_game_graphics.sh
bash tools/identify_game_graphics.sh
```

The identifier writes:

- `work/game_acf/graphics_identification/identified_candidates.csv` — one row per rendered candidate, with structural class, hashes, family IDs, confirmed-asset relationships, and review score.
- `work/game_acf/graphics_identification/families.csv` — duplicate/variant/source/structure groups.
- `work/game_acf/graphics_identification/summary.json` — counts and the exact interpretation rules used.
- `work/game_acf/graphics_identification/index.html` — a searchable local gallery of the identified candidates.

Open the gallery with:

```bash
xdg-open work/game_acf/graphics_identification/index.html
```

## Automatic classes

The structural presentation class is conservative:

- `animated_sprite_candidate` — an NCER cell bank whose contiguous graphics run also contains NANR animation data.
- `sprite_cell_bank` — an NCER cell-bank preview without adjacent NANR evidence.
- `background_or_ui_screen` — an NSCR-composed preview.
- `graphics_tile_sheet` — an NCGR+NCLR sheet without a selected NCER/NSCR presentation.

These are resource-role classifications, not semantic claims about what the picture depicts.

## Automatic relationships

The identifier uses several independent signals:

### Exact visual match

`exact_visual` means canvas dimensions and every rendered RGBA pixel match exactly. This is the strongest visual duplicate relationship.

### Same alpha shape

`same_alpha_shape` means dimensions and the per-pixel opaque/transparent mask match while RGB pixels may differ. This is useful for palette swaps or color variants. Fully opaque/fully transparent canvases are excluded because a rectangular background alpha plane is not a useful silhouette.

### Shared NCGR

`shared_ncgr` means the candidate graphics resolve to NCGR payloads with the same SHA-256. This is a source-level relationship even if a different palette/layout renders the graphics differently.

### Same resource set / structure

Candidates are also grouped when their complete NCGR/NCLR/layout source hashes match or when their presentation dimensions and parsed Nitro metadata share the same structure.

### Near visual

A 64-bit difference hash provides a review hint for candidates with the same preview type and similar aspect ratio. A Hamming distance of 5 or less is recorded as `near_visual` to a confirmed asset. This is deliberately treated only as a suggestion, never as proof of identity.

## Confirmed identity propagation

The confirmed registry is the semantic anchor. When a candidate is manually identified and verified in-game, add/update it in `docs/confirmed_graphics_assets.json`. On the next identification run, the tool will automatically locate:

- exact rendered duplicates of that confirmed asset;
- candidates sharing its NCGR source;
- same-silhouette color/palette variants; and
- close visual review candidates.

This means each genuinely confirmed asset makes the rest of the catalogue easier to classify without weakening the distinction between fact and heuristic similarity.

## Current first anchor

`G00583__bank_0001` is currently the first in-game-verified graphics anchor. Its exact semantic name remains intentionally unset until explicitly identified. The identifier will nevertheless use its confirmed resource mapping as a reference point for automatically related graphics.
