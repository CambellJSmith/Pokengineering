# Guardian Signs ROM Rebuild Workflow

This milestone turns the existing extracted *Pokémon Ranger: Guardian Signs* components back into a Nintendo DS image and supports size-changing NitroFS replacements.

## What Is Reconstructed

The repository already contains the fixed ROM regions needed for reconstruction:

```text
header.bin
arm9.bin
a9ovr.bin
a9ovr_data.bin
arm7.bin
fnt.bin
fat.bin
itl.bin
fat_data.bin
_file_IDs.txt
```

The original DS header describes the fixed layout. For the current US extraction:

```text
0x00000000  header region
0x00004000  ARM9
             ARM9 footer/padding
             ARM9 overlay table
             ARM9 overlay data
             ARM7
             FNT
             FAT
             icon/title data (itl.bin)
0x00164C00  NitroFS payload
```

`itl.bin` ends at the same `0x00164C00` address independently derived by the FAT signature-validation tooling. This closes the previously missing link between the fixed ROM components and `fat_data.bin`.

The FAT contains 420 entries. FAT IDs `0x00` through `0x21` are the 34 ARM9 overlay files and remain at their original addresses. The mapped NitroFS filesystem starts at FAT ID `0x22` and contains 386 files.

## Rebuild Rules

`tools/rebuild_nds.py` deliberately keeps the fixed executable layout unchanged.

When a NitroFS file changes size, the rebuilder:

1. preserves all overlay FAT entries exactly;
2. preserves the original bytes between NitroFS files;
3. inserts the replacement at its existing filesystem position;
4. shifts later NitroFS files by the resulting size delta;
5. rewrites every affected absolute FAT start/end range;
6. updates the header used-ROM size at `0x80`;
7. recalculates the Nintendo DS header CRC at `0x15E`; and
8. refuses to build if the result exceeds the retail cartridge capacity.

The physical retail capacity encoded by this ROM is 128 MiB. A full build is padded to that capacity with `0xFF`. `--trim` emits only the used ROM region while retaining the same internal addresses.

## Build A Modded Localization ROM

First complete the localization workflow:

```bash
bash tools/setup_guardian_tools.sh
bash tools/extract_localization.sh
```

Edit the JSON files under:

```text
work/localization/json/
```

Then rebuild the localization archive:

```bash
bash tools/rebuild_localization.sh
```

Create and validate the Nintendo DS image:

```bash
bash tools/build_modded_rom.sh
```

The default output is:

```text
work/guardian_signs_modded.nds
```

For a trimmed emulator-oriented image:

```bash
bash tools/build_modded_rom.sh work/localization work/guardian_signs_modded.nds --trim
```

All paths under `work/` are ignored by Git.

## Replace Any Mapped NitroFS File

The lower-level rebuilder accepts repeated path-based replacements:

```bash
python3 tools/rebuild_nds.py \
  --output work/custom.nds \
  --replace "data/data_localize_us.acf=work/localization/rebuilt_data_localize_us.acf"
```

Additional `--replace` arguments may target other exact paths from `_file_IDs.txt` as those formats become understood.

The tool resolves paths to FAT IDs itself. This avoids hard-coding numeric IDs in mod scripts while still reporting the resolved ID during the build.

## Validate A Rebuilt ROM

Run the independent validator at any time:

```bash
python3 tools/validate_nds.py work/guardian_signs_modded.nds
```

To verify an intentional replacement byte-for-byte:

```bash
python3 tools/validate_nds.py \
  work/guardian_signs_modded.nds \
  --expect "data/data_localize_us.acf=work/localization/rebuilt_data_localize_us.acf"
```

The validator checks:

- Nintendo DS header CRC;
- used-ROM size versus physical image size;
- original cartridge-capacity metadata;
- ARM9, ARM9 overlay table/data, ARM7, FNT, and icon/title bytes;
- preservation of all 34 overlay FAT entries;
- monotonic, non-overlapping NitroFS FAT ranges within the used ROM; and
- any requested replacement files against their exact in-ROM bytes.

## Automated Test

Run:

```bash
bash tools/test_rom_rebuild.sh
```

The test creates two temporary trimmed ROM images and deletes them afterward.

The baseline image has no replacements. Its rebuilt header and FAT must match the extracted originals exactly.

The modified image uses a temporary localization ACF that is deliberately made larger. The test proves that:

- the replacement occupies the exact rebuilt FAT range;
- all FAT entries before the replacement remain unchanged;
- the next NitroFS entry shifts by exactly the replacement size delta;
- the used-ROM size shifts by the same delta;
- overlay FAT entries remain unchanged; and
- the independent validator accepts the final image.

This is a structural reconstruction/reinjection proof. The next manual smoke test is to change a deliberately chosen visible dialogue line, build `guardian_signs_modded.nds`, and boot it in a DS emulator to confirm the modified line appears in-game.

## Distribution

Do not commit or distribute generated `.nds` images or rebuilt proprietary archives. The toolchain is intended to operate on data extracted from a copy of the game the user is authorized to work with. Generated ROMs and workspaces remain ignored by Git.
