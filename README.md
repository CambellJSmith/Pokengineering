# Pokengineering

Reverse-engineering and modding research for *Pokémon Ranger: Guardian Signs*.

## Current Milestone

The project now has two connected round-trip workflows:

```text
fat_data.bin + fat.bin + _file_IDs.txt
                ↓
   validated NitroFS extraction
                ↓
      data_localize_us.acf
                ↓
             acftool
                ↓
       275 MES resources
                ↓
             ra3mes
                ↓
         editable JSON
                ↓
             ra3mes
                ↓
          rebuilt MES
                ↓
             acftool
                ↓
 rebuilt_data_localize_us.acf
                ↓
       rebuild_nds.py
                ↓
  rebuilt FAT + DS header CRC
                ↓
 guardian_signs_modded.nds
```

The originally unpacked files under `data/` are misaligned. The tooling therefore reconstructs required files directly from the validated raw FAT payload. The complete extracted component set is sufficient to reconstruct the Nintendo DS image without committing a `.nds` file.

## Quick Start

Build the pinned Guardian Signs ACF/MES tools and extract localization text:

```bash
bash tools/setup_guardian_tools.sh
bash tools/extract_localization.sh
```

Edit files under:

```text
work/localization/json/
```

Then rebuild the localization archive and Nintendo DS image:

```bash
bash tools/rebuild_localization.sh
bash tools/build_modded_rom.sh
```

The validated full-capacity output is written to:

```text
work/guardian_signs_modded.nds
```

For a trimmed emulator-oriented image:

```bash
bash tools/build_modded_rom.sh work/localization work/guardian_signs_modded.nds --trim
```

## Tests

Verify the localization ACF/MES round trip:

```bash
bash tools/test_localization_roundtrip.sh
```

Verify baseline Nintendo DS reconstruction plus a size-changing NitroFS reinjection:

```bash
bash tools/test_rom_rebuild.sh
```

See [`docs/localization_workflow.md`](docs/localization_workflow.md) for text editing and [`docs/rom_rebuild_workflow.md`](docs/rom_rebuild_workflow.md) for ROM reconstruction, FAT shifting, validation, and emulator smoke-testing guidance.

## Repository Policy

Keep user-supplied ROM images, generated workspaces, rebuilt archives, and downloaded third-party binaries out of Git. The project should contain tooling, documentation, tests, and reconstructed source rather than additional proprietary game data.
