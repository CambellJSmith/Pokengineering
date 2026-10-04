# Nitro graphics previews

`tools/render_nitro_graphics.py` parses the standard Nintendo DS Nitro 2D resources exported by the Guardian Signs graphics catalogue and produces deterministic PNG diagnostics and candidate composites.

Supported parsing:

- NCGR (`RGCN` / `RAHC`) character graphics, 4bpp and 8bpp.
- NCLR (`RLCN` / `TTLP`) BGR555 palettes.
- NSCR (`RCSN` / `NRCS`) text-background tilemaps, including tile flips and 4bpp palette banks.
- NCER (`RECN` / `KBEC`) cell banks and non-affine OAM layouts.
- NANR (`RNAN`) common header and section inventory. Animation playback is intentionally not inferred yet.

Run the renderer against the committed/extracted catalogue:

```bash
bash tools/render_game_graphics.sh
```

By default the output is `work/game_acf/graphics_previews/`. The renderer writes `resource_inspection.csv`, `candidate_previews.csv`, `unresolved.csv`, `summary.json`, atomic palette/index previews, and structurally supported background/cell candidates.

## Pairing policy

A combined preview is attempted only when one maximal contiguous graphics run contains exactly one NCGR and exactly one NCLR. That is a structural candidate relationship, not proof that the resources are semantically paired. `semantic_pairing_proven` therefore remains `False` in every generated candidate row.

If a run contains multiple possible graphics, palette, screen, or cell resources, the renderer records the ambiguity instead of choosing one. Technical incompatibilities such as color-depth mismatch, missing palette banks, out-of-range tile references, affine OAM, or out-of-range cell graphics are also reported in `unresolved.csv`.

`--metadata-only` performs the same parsing and candidate validation without writing PNGs. CI uses this mode to validate the retail catalogue while keeping the test output small.
