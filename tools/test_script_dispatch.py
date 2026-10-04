"""Checks for command bitfields and non-contiguous captured VM arguments."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from analyze_script_dispatch import analyze_capture, decode_command, u32


class ScriptDispatchTests(unittest.TestCase):
    def test_native_word_and_signed_upper_halfword(self):
        self.assertEqual(decode_command(0x1C540301), {
            'word': '0x1C540301', 'vm_type': 1, 'argument_count': 3,
            'bank': 7, 'index': 0x54})
        # ARM uses ldrsh/asr then masks; high-bit banks must stay unsigned here.
        self.assertEqual(decode_command(0xFFFFFFFF)['bank'], 63)
        self.assertEqual(decode_command(0xFFFFFFFF)['index'], 1023)
        self.assertEqual(decode_command(0x80000001)['bank'], 32)

    def test_noncontiguous_argument_cursor(self):
        base = 0x02000000
        vm, pc, args, table = base + 0x100, base + 0x204, base + 0x800, base + 0x1000
        ram = bytearray(0x400000)
        for address, value in [(vm, pc), (vm + 4, args),
                               (base + 0xC20CC + 7 * 4, table),
                               (table + 0x54 * 4, 0x0210360C),
                               (args, 8), (args + 4, 13), (args + 8, 0)]:
            struct.pack_into('<I', ram, address - base, value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ram.bin').write_bytes(ram)
            (root / 'capture.log').write_text(f'DISPATCH_VM=0x{vm:08x}\nDISPATCH_WORD=0x1c540301\n')
            result = analyze_capture(root / 'ram.bin', root / 'capture.log', root)
            self.assertEqual(result['arguments'], [8, 13, 0])
            self.assertEqual(result['command_address'], '0x02000200')
            self.assertEqual(result['argument_address'], '0x02000800')
            self.assertEqual(json.loads((root / 'capture.json').read_text()), result)

    def test_image_bounds(self):
        for address in (0x1FFFFFF, 0x2000001):
            with self.assertRaises(ValueError):
                u32(bytes(4), 0x02000000, address)
        with self.assertRaises(ValueError):
            decode_command(-1)


if __name__ == '__main__':
    unittest.main()
