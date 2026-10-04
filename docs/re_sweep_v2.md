# Reverse-engineering sweep v2

The original local cross-image sweep used during the Spearow investigation has been preserved verbatim in:

```text
research/archive/pokengineering_re_sweep_v2.zip
```

The archive contains:

```text
tools/re_sweep_v2.py
runtime_observations.txt
README.txt
```

A normalized copy of the live observations is also tracked at:

```text
research/capture/runtime_observations_2026-10-04.txt
```

## What the tool does

`re_sweep_v2.py` combines runtime ARM9 and decoded overlay analysis and can incorporate live GDB facts. It performs ARM disassembly, direct cross-image call recovery, PC-relative literal recovery, pointer/table scanning, string/RTTI-ish extraction, basic jump-table switch recovery, optional before/during RAM diffs, and fixed-point expansion around seed addresses.

It is heuristic static analysis: direct calls and literal relationships are more trustworthy than inferred pointer tables or RTTI proximity.

## Historical run command

```bash
python3 tools/re_sweep_v2.py \
  --overlay work/code_analysis/executables/overlays/overlay_003.bin \
  --base 0x020D00C0 \
  --arm9 work/code_analysis/runtime/arm9_runtime.bin \
  --arm9-base 0x02000000 \
  --before /tmp/starly_full_before.bin \
  --during /tmp/starly_full_during.bin \
  --runtime-facts runtime_observations.txt \
  --keyword Capture \
  --keyword CapturePokemon \
  --keyword LoadCapturePokemon \
  --keyword CaptureBeforeState \
  --seed 0x02106744 \
  --seed 0x02117258 \
  --seed 0x02117388 \
  --seed 0x02041F5C \
  --out work/re_sweep_v2/reverse_engineering_report_v2.md
```

The tool requires `arm-none-eabi-objdump` in `PATH`.

The current root README contains the distilled conclusions from this sweep. This archive is retained so no unique local tooling is lost if the original workstation checkout is deleted.
