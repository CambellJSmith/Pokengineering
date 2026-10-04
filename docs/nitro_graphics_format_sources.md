# Nitro 2D format references

The preview renderer implementation was cross-checked against established Nintendo DS Nitro graphics tooling rather than inferred from Guardian Signs payloads alone.

Primary implementation references used during development:

- Tinke NCGR reader: common Nitro header, RAHC fields, character dimensions, color depth, tiled/linear flag, and graphics-data pointer.
- Tinke NCLR reader: TTLP fields, palette data pointer, 4bpp/8bpp palette sizing, and BGR555 conversion.
- Tinke NSCR reader: NRCS dimensions and 16-bit map entries (tile index, X/Y flip, palette bank).
- Tinke NCER and image helpers: CEBK bank/OAM layout, OAM bitfields and dimensions, OBJ tile-offset calculation, palette-bank selection, priority ordering, and flips.

The renderer intentionally treats resource co-location as structural evidence only. It does not promote contiguous resources to proven semantic pairs.
