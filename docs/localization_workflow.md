# Guardian Signs Localization Workflow

This milestone establishes a reproducible edit/rebuild path for the US retail `data_localize_us.acf` archive from *Pokémon Ranger: Guardian Signs*.

The workflow uses two maintained external tools without vendoring them into this repository:

- `acftool` extracts ACF entries, preserves their compression state in `filelist.json`, and rebuilds the archive.
- `ra3mes` converts Guardian Signs MES text resources to editable JSON and back.

`tools/setup_guardian_tools.sh` pins both tools to known revisions so the workflow is reproducible.

## Local Setup

Requirements:

- Linux
- Git
- Make
- GCC or Clang
- Python 3

Build the helper tools:

```bash
bash tools/setup_guardian_tools.sh
```

The resulting executables are placed in `tools/bin/`, which is ignored by Git.

## Extract Localization

Use a `data_localize_us.acf` extracted from a ROM you own:

```bash
bash tools/extract_localization.sh /path/to/data_localize_us.acf
```

The default workspace is `work/localization/` and is ignored by Git.

Important outputs:

```text
work/localization/
├── original.acf
├── editable/
│   ├── filelist.json
│   ├── 0000.*
│   ├── 0001.*
│   └── ...
├── json/
│   ├── 0000.json
│   ├── 0001.json
│   └── ...
└── catalog.csv
```

The first 275 entries in the retail Guardian Signs localization ACF are MES text resources. The extraction script converts all 275 to JSON.

`catalog.csv` records metadata only: archive index, extracted filename, compression state, byte size, SHA-256, MES conversion status, and string count. It does not copy game dialogue into the catalogue.

## Edit Text

The JSON files are flat objects keyed by three-digit string indexes. Control codes such as `[E]`, `[R]`, `[C:X]`, and `[P:X]` are part of the text format and should be preserved when needed.

You can edit a JSON file directly, or replace one string deterministically:

```bash
python3 tools/set_localization_text.py work/localization <file_index> <string_index> "replacement text"
```

For example, `file_index` identifies one of the ACF entries and `string_index` identifies one string inside that MES file. Choose a line you can deliberately trigger in-game for a useful smoke test rather than changing an arbitrary sentinel or unused string.

## Rebuild ACF

After editing the JSON:

```bash
bash tools/rebuild_localization.sh
```

This converts all 275 JSON files back into MES payloads, keeps the original ACF entry names and compression states, and creates:

```text
work/localization/rebuilt_data_localize_us.acf
```

The untouched source copy remains at:

```text
work/localization/original.acf
```

## Automated Round-Trip Test

Run:

```bash
bash tools/test_localization_roundtrip.sh /path/to/data_localize_us.acf
```

The test:

1. extracts the ACF;
2. converts the localization MES entries to JSON;
3. replaces one string with a deterministic test marker;
4. rebuilds the ACF;
5. re-extracts the rebuilt ACF;
6. converts the modified MES entry back to JSON; and
7. verifies that the changed string survived the full ACF/MES round trip.

All test output is created in a temporary directory and removed automatically. The original dialogue is not printed by the test.

## In-Game Verification

The current milestone ends at a rebuilt `data_localize_us.acf`. To test it in-game, replace the matching NitroFS file in a working copy of your own ROM and rebuild that ROM with your preferred Nintendo DS filesystem tool. Keep the rebuilt ROM and generated game data outside Git.

A successful in-game smoke test should deliberately target a known, easily triggered line and confirm that only the intended text changed.

## Repository Hygiene

Do not add ROM images, rebuilt ACF archives, extracted editing workspaces, or downloaded third-party tool binaries to the repository. `.gitignore` covers the standard paths used by this workflow.

The repository should increasingly contain reverse-engineering notes, source code, tooling, tests, and format documentation rather than additional copies of original game data.

## Next Milestone

After the localization round trip is stable, the next useful work is:

1. automate safe NitroFS reinjection/rebuild for a user-supplied ROM;
2. identify and document a deterministic visible text entry for the first emulator smoke test;
3. catalogue `data_game_us.acf` using the same ACF infrastructure; and
4. begin mapping ARM9/overlay resource-loading calls to the documented file IDs and archive entries.
