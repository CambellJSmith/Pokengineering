# Nitro graphics previews

The preview pipeline has two layers:

- `tools/render_nitro_graphics.py` is the strict Nintendo DS Nitro 2D parser/renderer.
- `tools/render_guardian_graphics.py` applies the specific format variants observed in Guardian Signs and records every compatibility exception instead of hiding it.

Use the project wrapper:

```bash
bash tools/render_game_graphics.sh
```

By default it reads `work/game_acf/graphics_catalog/` and writes `work/game_acf/graphics_previews/`.

## Supported resources

The pipeline parses:

- NCGR (`RGCN` / `RAHC`) character graphics.
- NCLR (`RLCN` / `TTLP`) BGR555 palettes.
- NSCR (`RCSN` / `NRCS`) tilemaps, including tile flips and palette banks.
- NCER (`RECN` / `KBEC`) cell banks and non-affine OAM layouts.
- NANR (`RNAN`) common headers and section inventories. Animation playback is intentionally not inferred yet.

Guardian Signs also uses Nintendo DS texture-format values in the NCGR/NCLR format field beyond ordinary 4bpp and 8bpp palettes. The compatibility layer handles the observed A3I5, 2bpp/4-color, 4bpp/16-color, 8bpp/256-color, A5I3, and direct RGB555 encodings. It also handles the observed one-byte NSCR map variant and stale or padded common/section size declarations where the physical payload provides an unambiguous bound.

Those deviations are not silently normalized. They are written to `format_anomalies.csv`.

## Outputs

The output directory contains:

- `resource_inspection.csv` — parse result and structural metadata for every graphics resource.
- `candidate_previews.csv` — structurally valid combined-preview candidates.
- `unresolved.csv` — ambiguous or technically incompatible combinations that were deliberately not guessed.
- `format_anomalies.csv` — observed Guardian-specific size and texture-format variants used by the compatibility layer.
- `summary.json` — counts and renderer policy metadata.
- `atomic/palettes/` — palette swatch PNGs.
- `atomic/indices/` — standalone NCGR diagnostic PNGs.
- `candidates/sheets/` — colorized NCGR+NCLR candidate sheets.
- `candidates/backgrounds/` — NSCR background candidates.
- `candidates/cells/` — renderable NCER cell-bank candidates.

## Pairing policy

A combined preview is attempted only when one maximal contiguous graphics run contains exactly one NCGR and exactly one NCLR. That is structural evidence only; it is not proof that the resources are semantically paired. `semantic_pairing_proven` therefore remains `False` in every generated candidate row.

If a run contains multiple possible graphics, palette, screen, or cell resources, the renderer records the ambiguity instead of choosing one. Unsupported affine cells, out-of-range tile references, palette incompatibilities, and other technical conflicts are likewise recorded in `unresolved.csv`.

`--metadata-only` performs the same parsing and candidate validation without writing PNG files. CI uses that mode against the full retail catalogue while the synthetic tests exercise actual PNG generation.
