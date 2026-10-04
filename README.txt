Pokengineering Graphics Catalogue — Fixed Root Detection

This version does not require catalog_graphics_sets.py to be physically located
at the exact repository root. It searches upward from both:
- the current working directory
- the script location

until it finds:
  tools/catalog_game_acf.py
  tools/inventory_recursive_containers.py

Recommended usage:

1. Extract this ZIP anywhere inside your Pokengineering checkout.
2. Open a terminal in the Pokengineering repository root.
3. Run:

   python3 catalog_graphics_sets.py

If you extracted it into a subfolder instead, you can also run:

   python3 path/to/catalog_graphics_sets.py

The script still uses:
  work/game_acf/archive/
  work/game_acf/analysis/

and writes:
  work/game_acf/graphics_catalog/

If the recursive inventory has not yet been generated, run:
  tools/extract_game_data.sh
first.
