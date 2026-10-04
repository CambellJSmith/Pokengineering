# Guardian Signs native script dispatch (B3RE)

The ARM9 interpreter at `0x02065A80` dispatches VM instruction type **1** through a banked native-handler registry. The previous shorthand “script opcode 0x54” means **native handler index 0x54**, not the low-byte VM instruction type. Overlay 003 registers bank **7** and its entry **0x54** is `0x0210360C`.

## Evidence and confidence

These findings were reconstructed on 2026-10-04 from the existing local `work/code_analysis/runtime/arm9_runtime.bin` (base `0x02000000`) and decoded `overlay_003.bin` (base `0x020D00C0`). The original runtime dump's acquisition procedure is not recorded here. Input SHA-256 hashes and targeted disassembly are preserved under `script_dispatch_evidence/`; inputs themselves remain local. This analysis is address-specific to the inspected B3RE build.

The supplied prior live observation, not repeated during this analysis, was:

```text
PC=0x0210360C  LR=0x02065E64
r0=0x0212536C r1=3 r2=0x54 r3=0x0210360C
payload words: 8, 13, 0, 0, 4, 0x0212653C, 0xFFF, 0, ...
```

Only the first three words are command arguments according to r1. Later words must not be interpreted as additional arguments to this call.

The pre-existing untracked [runtime observations](spearow_prior_runtime_observations.txt) are also preserved verbatim. They describe an earlier breakpoint at `0x02117258`, not this dispatcher invocation; do not combine their register values into a single snapshot.

## Command word and separate cursors

At `0x02065AC8..0x02065AE4`, r9 is the VM context. The interpreter fetches one little-endian 32-bit word from `[r9+0]`, increments that cursor by four, and stores the fetched word at `[sp]`. The low byte selects a VM instruction via the jump table at `0x02065AF8`; type 1 branches through `0x02065AFC` to `0x02065E14`.

For type 1:

| Bits | Meaning | Instructions |
|---|---|---|
| 0..7 | VM type = 1 | `0x02065AE8..0x02065AFC` |
| 8..15 | number of 32-bit arguments | `ldrb r7,[sp,#1]` at `0x02065E18` |
| 16..25 | native handler index, 0..1023 | signed halfword read, masked with `0x3FF` |
| 26..31 | registry bank, 0..63 | arithmetic shift by 10, masked with `0x3F` |

The masks make the signed-halfword implementation equivalent to unsigned bitfield extraction. Registry base `0x020C20CC` is loaded from literal `0x0206675C`. The mask `0x3FF` is loaded from `0x02066764`.

```c
word = *vm.command_cursor++;
argc = (word >> 8) & 0xff;
index = (word >> 16) & 0x3ff;
bank = (word >> 26) & 0x3f;
table = registry[bank];
if (table != NULL && table[index] != NULL) {
    // actual call registers: r0=args, r1=argc, r2=index, r3=handler
    vm.last_result = table[index](vm.argument_cursor, argc);
}
if (vm.command_cursor != NULL) {
    vm.argument_cursor += argc; // 32-bit words, using cursor after handler returns
}
```

This pseudocode covers the native-call case, not the complete interpreter. The null-bank and null-handler paths call diagnostic function `0x02065998`. The result is stored at `[r9+0x10]`. The instruction loop also adjusts its execution counter; scheduling semantics need separate analysis.

The VM consumes command words and arguments through **separate pointers**. Do not parse this as a fixed `[header,arg0,arg1,arg2]` record. `0x02065970` resets the argument cursor to `[vm+0x1C] + 4*[vm+0x18]` and the other stack cursor to `[vm+0x1C]`, suggesting a shared allocation with stacks growing toward each other. The on-disk script format and loader remain unresolved.

| VM offset | Observed use |
|---|---|
| +0x00 | command cursor; already advanced when native call begins |
| +0x04 | argument/value-stack cursor passed as r0 |
| +0x08 | second stack cursor |
| +0x0C | saved cursor/frame-related field |
| +0x10 | native return value |
| +0x14 | saved execution-related field |
| +0x18 | size/count used by reset and diagnostics |
| +0x1C | backing allocation base |
| +0x20 | delay counter |

## Bank registration and capture entry

ARM9 function `0x02065930` stores r1 into `registry[r0]`. Overlay callsites `0x020D1D5C` and `0x02100A4C` pass bank 7 and table `0x0211C9C8` (literals at `0x020D2208` and `0x02100BC0`). Entry 0x54 lives at:

```text
0x0211C9C8 + 4*0x54 = 0x0211CB18
*(uint32_t *)0x0211CB18 = 0x0210360C
```

The observed table span contains 240 pointer words before a zero at `0x0211CD88` and text at `0x0211CD8C`. This is an observed static span, not a proven declared table length or a VM bounds check. `bank7.csv` inventories those entries without assigning speculative names.

Bank 7, index 0x54, argc 3, type 1 imply **`0x1C540301`**, or bytes **`01 03 54 1C`**. This command word is inferred from the static registration and supplied live registers; its actual script address and value await the companion runtime capture. A byte search for these four bytes alone is only a candidate search, not proof of a script or capture trigger.

Handler `0x0210360C`:

1. Loads arg0 as a 32-bit object key, and truncates arg1 and arg2 to unsigned 16-bit values.
2. Calls object resolver `0x0210227C` with arg0. If it returns null, returns zero without writing a record.
3. Sets bit `0x08000000` in the object's word at +0x1E8.
4. Calls the object's virtual function at vtable +0x2C. Reads two words from its returned pointer.
5. Calls `0x02116774` with destination `0x02126550`, arg1, arg0, arg2, and stack words `{0, returned_word0, returned_word1, returned_word0, returned_word1}`.
6. Returns zero.

The capture-record-writer label for `0x02116774` comes from prior project tracing. This handler's call and argument marshalling are independently confirmed by the saved overlay. The gameplay meanings of 13 and 0, bit 0x08000000, and the virtual return words remain unassigned. In particular, **13 is not established as a species ID**.

## Reproduce offline

From the repository root, using the existing runtime and decoded-overlay files:

```bash
python3 tools/analyze_script_dispatch.py \
  --arm9 work/code_analysis/runtime/arm9_runtime.bin \
  --overlay work/code_analysis/executables/overlays/overlay_003.bin
python3 -m unittest discover -s tools -p 'test_script_dispatch.py'
```

If decoded overlays are missing, `bash tools/analyze_game_code.sh` regenerates them but **deletes its entire output directory first**, including a runtime dump stored there. Preserve that dump elsewhere before running it. The retail ARM9 file is not automatically substituted for the runtime image.

## One capture instead of repeated manual dumps

There was no active emulator/GDB process visible during this analysis.

To start the existing local debug ROM from scratch in terminal 1:

```bash
cd ~/Documents/GitHub/desmume-gdb/desmume/src/frontend/posix
./build/cli/desmume-cli --arm9gdb 3333 ~/Documents/GitHub/Pokengineering/work/debug/guardian_signs_debug.nds
```

Starting a new emulator begins a new run. In terminal 2, from the repository root containing these new tools:

```bash
mkdir -p work/script_dispatch
arm-none-eabi-gdb
```

In GDB (only connect if not already connected):

```gdb
set architecture arm
target remote localhost:3333
source tools/gdb/capture_native_54.gdb
continue
```

Play to the encounter. The script stops immediately **before** the native call at `0x02065E60`, selects calls whose handler is `0x0210360C`, records VM/register/header details, and saves main RAM once. It leaves the game paused. If already stopped at the handler entry, that call has passed this breakpoint: continue to another invocation or restart the encounter only when desired. Existing breakpoints may stop first; inspect them before disabling any.

Then run in a separate shell:

```bash
python3 tools/analyze_script_dispatch.py \
  --arm9 work/code_analysis/runtime/arm9_runtime.bin \
  --overlay work/code_analysis/executables/overlays/overlay_003.bin \
  --ram work/script_dispatch/capture_ram.bin \
  --capture-log work/script_dispatch/dispatch_capture.log
```

`work/script_dispatch/capture.json` resolves the actual command address, separate argument address, current bank table, handler, count and argument values. The GDB capture uses standard commands without GDB Python. It overwrites the same capture filenames on the next matching call; preserve a capture before continuing. The GDB script successfully loaded in the installed ARM GDB and created its breakpoint in a batch syntax check, but has not run against a live emulator in this session.

Next: map captured command and backing-allocation bytes to script resources, trace VM creation/loading, and build a resource-aware scanner. Only then enumerate every capture command; raw four-byte matches cannot establish that inventory.
