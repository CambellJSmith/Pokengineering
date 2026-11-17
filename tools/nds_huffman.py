#!/usr/bin/env python3
"""Nintendo DS/GBA Huffman decompression (BIOS type 0x2X: 0x24 4-bit, 0x28 8-bit).

Used by Guardian Signs' data/mapz/*.acz map files.

Layout: u8 type|bits, u24 size (0 -> u32 size follows), u8 tree_size_div2-1,
tree nodes, then the bitstream as little-endian u32 words read MSB-first.
Node byte: low 6 bits = offset; bit7 = left child is leaf, bit6 = right is leaf.
Children of node at address A are at (A & ~1) + offset*2 + 2 (+1 for right).
"""
from __future__ import annotations

import struct
import sys


def decompress(src: bytes) -> bytes:
    if src[0] & 0xF0 != 0x20:
        raise ValueError(f"not Huffman (type byte 0x{src[0]:02X})")
    bits = src[0] & 0x0F
    if bits not in (4, 8):
        raise ValueError(f"unsupported Huffman width {bits}")
    size = src[1] | src[2] << 8 | src[3] << 16
    pos = 4
    if size == 0:
        size = struct.unpack_from("<I", src, 4)[0]
        pos = 8
    tree_base = pos
    tree_size = (src[tree_base] + 1) * 2
    root = tree_base + 1
    data = tree_base + tree_size

    out = bytearray()
    pending = 0
    have_half = False
    cur = root
    while len(out) < size:
        if data + 4 > len(src):
            raise ValueError("Huffman stream truncated")
        word = struct.unpack_from("<I", src, data)[0]
        data += 4
        for i in range(31, -1, -1):
            node = src[cur]
            nxt = (cur & ~1) + (node & 0x3F) * 2 + 2
            if (word >> i) & 1:
                child, leaf = nxt + 1, node & 0x40
            else:
                child, leaf = nxt, node & 0x80
            if not leaf:
                cur = child
                continue
            value = src[child]
            cur = root
            if bits == 8:
                out.append(value)
            else:
                if have_half:
                    out.append(pending | (value & 0xF) << 4)
                    have_half = False
                else:
                    pending = value & 0xF
                    have_half = True
            if len(out) >= size:
                break
    return bytes(out)


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    dec = decompress(data)
    open(sys.argv[2], "wb").write(dec)
    print(f"{sys.argv[1]}: {len(data)} -> {len(dec)} bytes")
