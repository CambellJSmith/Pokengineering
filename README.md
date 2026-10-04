# Pokengineering

Reverse-engineering and modding research for *Pokémon Ranger: Guardian Signs*.

## Current Milestone

The first supported workflow is a complete localization ACF/MES round trip for the US retail game:

```text
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
```

Start with:

```bash
bash tools/setup_guardian_tools.sh
bash tools/extract_localization.sh /path/to/data_localize_us.acf
```

After editing files under `work/localization/json/`, rebuild with:

```bash
bash tools/rebuild_localization.sh
```

Run the automated extraction/edit/rebuild/re-extraction verification with:

```bash
bash tools/test_localization_roundtrip.sh /path/to/data_localize_us.acf
```

See [`docs/localization_workflow.md`](docs/localization_workflow.md) for the complete workflow, output layout, repository hygiene rules, and the next reverse-engineering milestone.

## Repository Policy

Keep user-supplied ROM images, generated workspaces, rebuilt archives, and downloaded third-party binaries out of Git. The project should contain tooling, documentation, tests, and reconstructed source rather than additional proprietary game data.
