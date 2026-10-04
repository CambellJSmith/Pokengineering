#!/usr/bin/env python3
"""Reproduce B3RE native-dispatch evidence without a live debugger.

Inputs stay local. Generated hashes, disassembly and pointer CSV may be shared.
This is a targeted analysis of known addresses, not a general script parser.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ARM9_BASE = 0x02000000
OVERLAY_BASE = 0x020D00C0
TABLE = 0x0211C9C8


def decode_command(word):
    if not 0 <= word <= 0xFFFFFFFF:
        raise ValueError('command must be an unsigned 32-bit word')
    return {'word': f'0x{word:08X}', 'vm_type': word & 255,
            'argument_count': (word >> 8) & 255,
            'bank': (word >> 26) & 63, 'index': (word >> 16) & 1023}


def u32(data, base, address):
    offset = address - base
    if offset < 0 or offset + 4 > len(data):
        raise ValueError(f'address outside image: 0x{address:08X}')
    return struct.unpack_from('<I', data, offset)[0]


def disassemble(path, base, start, end, objdump):
    result = subprocess.run([objdump, '-D', '-b', 'binary', '-m', 'arm',
                           f'--adjust-vma={base}', f'--start-address={start}',
                           f'--stop-address={end}', str(path)], check=True,
                          capture_output=True, text=True).stdout
    return result.replace(str(path), path.name)


def analyze(arm9_path, overlay_path, output, objdump):
    arm9, overlay = arm9_path.read_bytes(), overlay_path.read_bytes()
    # Reject images whose addressing or key instructions differ from this build.
    expected = {0x02065A80: 0xE92D4FF8, 0x02065AE0: 0xE5910000,
                0x02065AFC: 0xEA0000C4, 0x02065E60: 0xE12FFF33,
                0x0206675C: 0x020C20CC, 0x02066764: 0x000003FF}
    for address, word in expected.items():
        if u32(arm9, ARM9_BASE, address) != word:
            raise ValueError(f'B3RE dispatcher signature mismatch at 0x{address:08X}')
    if u32(overlay, OVERLAY_BASE, TABLE + 4 * 0x54) != 0x0210360C:
        raise ValueError('overlay bank-7 entry 0x54 differs from the known build')
    output.mkdir(parents=True, exist_ok=True)
    manifest = {'format': 'guardian-script-dispatch-v1', 'inputs': {
        'arm9': {'size': len(arm9), 'sha256': hashlib.sha256(arm9).hexdigest()},
        'overlay_003': {'size': len(overlay), 'sha256': hashlib.sha256(overlay).hexdigest()}},
        'inferred_spearow_command': decode_command(0x1C540301),
        'table_span_note': '240 observed pointer words before a zero and text; not a proven VM bound'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with (output / 'bank7.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['bank', 'index', 'slot_address', 'handler_pointer', 'code_address', 'state'])
        for index in range(240):
            slot = TABLE + 4 * index
            pointer = u32(overlay, OVERLAY_BASE, slot)
            writer.writerow([7, f'0x{index:03X}', f'0x{slot:08X}',
                             f'0x{pointer:08X}', f'0x{pointer & ~1:08X}',
                             'thumb' if pointer & 1 else 'arm'])
    regions = [(arm9_path, ARM9_BASE, 0x02065930, 0x02065998, 'vm_setup'),
               (arm9_path, ARM9_BASE, 0x02065A80, 0x02065B6C, 'vm_fetch'),
               (arm9_path, ARM9_BASE, 0x02065E14, 0x02065E88, 'native_dispatch'),
               (arm9_path, ARM9_BASE, 0x0206672C, 0x02066778, 'vm_loop'),
               (overlay_path, OVERLAY_BASE, 0x020D1D3C, 0x020D1D78, 'bank_registration'),
               (overlay_path, OVERLAY_BASE, 0x02100A38, 0x02100A50, 'bank_registration_2'),
               (overlay_path, OVERLAY_BASE, 0x0210360C, 0x02103694, 'capture_handler')]
    for path, base, start, end, name in regions:
        (output / f'{name}.asm').write_text(disassemble(path, base, start, end, objdump))
    return manifest


def analyze_capture(ram_path, log_path, output):
    """Decode separate VM cursors from the companion GDB capture."""
    ram = ram_path.read_bytes()
    if len(ram) != 0x400000:
        raise ValueError('capture must contain main RAM 0x02000000..0x02400000')
    fields = {}
    for line in log_path.read_text().splitlines():
        if line.startswith(('DISPATCH_VM=', 'DISPATCH_WORD=')):
            key, value = line.split('=', 1)
            fields[key] = int(value.strip(), 16)
    vm, word = fields['DISPATCH_VM'], fields['DISPATCH_WORD']
    command = decode_command(word)
    if command['vm_type'] != 1:
        raise ValueError('capture is not a native-call VM instruction')
    next_pc = u32(ram, ARM9_BASE, vm)
    args = u32(ram, ARM9_BASE, vm + 4)
    table = u32(ram, ARM9_BASE, 0x020C20CC + command['bank'] * 4)
    if not table:
        raise ValueError('captured bank is unregistered')
    slot = table + command['index'] * 4
    command.update(vm=f'0x{vm:08X}', command_address=f'0x{next_pc - 4:08X}',
                   argument_address=f'0x{args:08X}', table=f'0x{table:08X}',
                   slot=f'0x{slot:08X}', handler=f'0x{u32(ram, ARM9_BASE, slot):08X}',
                   arguments=[u32(ram, ARM9_BASE, args + i * 4)
                              for i in range(command['argument_count'])],
                   ram_sha256=hashlib.sha256(ram).hexdigest())
    output.mkdir(parents=True, exist_ok=True)
    (output / 'capture.json').write_text(json.dumps(command, indent=2) + '\n')
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm9', type=Path, required=True)
    parser.add_argument('--overlay', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('work/script_dispatch'))
    parser.add_argument('--objdump', default='arm-none-eabi-objdump')
    parser.add_argument('--ram', type=Path)
    parser.add_argument('--capture-log', type=Path)
    options = parser.parse_args()
    if bool(options.ram) != bool(options.capture_log):
        parser.error('--ram and --capture-log must be supplied together')
    try:
        result = analyze(options.arm9, options.overlay, options.output, options.objdump)
        if options.ram:
            result['capture'] = analyze_capture(options.ram, options.capture_log, options.output)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'error: {error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
