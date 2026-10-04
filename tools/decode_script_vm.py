#!/usr/bin/env python3

from pathlib import Path
import argparse
import struct


def u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def decode(data):
    code_start = u32(data, 0)
    code_end = u32(data, 4)

    if not (0 <= code_start <= code_end <= len(data)):
        raise ValueError(
            f"bad code range: 0x{code_start:X}..0x{code_end:X}, "
            f"file size 0x{len(data):X}"
        )

    out = []
    off = code_start

    while off + 4 <= code_end:
        word = u32(data, off)

        op = word & 0xFF
        sub = (word >> 8) & 0xFF
        raw16 = (word >> 16) & 0xFFFF
        imm16 = s16(raw16)

        ins = {
            "off": off,
            "size": 4,
            "word": word,
            "op": op,
            "sub": sub,
            "raw16": raw16,
            "imm16": imm16,
            "extra": None,
        }

        # These two VM instructions consume one additional 32-bit
        # word from the instruction stream.
        if op in (0x04, 0x11) and off + 8 <= code_end:
            ins["extra"] = u32(data, off + 4)
            ins["size"] = 8

        out.append(ins)
        off += ins["size"]

    return code_start, code_end, out


def direct_call_args(insns, index, argc):
    """
    Recover arguments only when they are immediately supplied by
    simple constant pushes. Because the VM stack grows downward,
    walking backward gives handler argument order directly.
    """
    args = []
    j = index - 1

    while len(args) < argc and j >= 0:
        ins = insns[j]

        if ins["op"] == 0x10:
            args.append(ins["imm16"])

        elif ins["op"] == 0x11 and ins["extra"] is not None:
            args.append(ins["extra"])

        else:
            return None

        j -= 1

    return args if len(args) == argc else None


def describe(ins, insns, index):
    op = ins["op"]
    off = ins["off"]

    if op == 0x00:
        return "NOP"

    if op == 0x01:
        argc = ins["sub"]
        selector = ins["raw16"]
        group = (selector >> 10) & 0x3F
        command = selector & 0x3FF

        args = direct_call_args(insns, index, argc)

        text = (
            f"CALL 0x{selector:04X} "
            f"[group={group} index=0x{command:X}] "
            f"argc={argc}"
        )

        if args is not None:
            text += " args=(" + ", ".join(
                f"0x{x & 0xFFFFFFFF:X}" for x in args
            ) + ")"

        return text

    if op == 0x08:
        target = off + 4 + ins["imm16"] * 4
        return (
            f"BRANCH_FAMILY sub={ins['sub']} "
            f"rel={ins['imm16']} -> +0x{target:X}"
        )

    if op == 0x10:
        return f"PUSH_S16 {ins['imm16']} (0x{ins['raw16']:04X})"

    if op == 0x11:
        return f"PUSH_U32 0x{ins['extra']:08X}"

    if op == 0x12:
        return "PUSH_LAST_RESULT"

    if op == 0x14:
        return f"ALU sub={ins['raw16']}"

    if op == 0x16:
        return f"COMPARE sub={ins['raw16']}"

    if op == 0x18:
        return f"SHIFT sub={ins['raw16']}"

    return (
        f"OP_{op:02X} sub=0x{ins['sub']:02X} "
        f"operand={ins['imm16']} "
        f"word=0x{ins['word']:08X}"
        + (
            f" extra=0x{ins['extra']:08X}"
            if ins["extra"] is not None else ""
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--selector", type=lambda x: int(x, 0), default=0x1C54)
    ap.add_argument("--before", type=int, default=24)
    ap.add_argument("--after", type=int, default=80)
    args = ap.parse_args()

    path = Path(args.file)
    data = path.read_bytes()

    start, end, insns = decode(data)

    print(f"file       : {path}")
    print(f"size       : 0x{len(data):X}")
    print(f"code start : 0x{start:X}")
    print(f"code end   : 0x{end:X}")
    print(f"instructions: {len(insns)}")
    print()

    targets = [
        i for i, ins in enumerate(insns)
        if ins["op"] == 0x01 and ins["raw16"] == args.selector
    ]

    print(f"selector 0x{args.selector:04X} occurrences: {len(targets)}")

    for hitno, idx in enumerate(targets, 1):
        hit = insns[idx]

        print()
        print("=" * 80)
        print(f"HIT {hitno} @ +0x{hit['off']:X}")
        print("=" * 80)

        lo = max(0, idx - args.before)
        hi = min(len(insns), idx + args.after + 1)

        for i in range(lo, hi):
            ins = insns[i]
            marker = ">>" if i == idx else "  "

            print(
                f"{marker} +0x{ins['off']:04X}  "
                f"{describe(ins, insns, i)}"
            )


if __name__ == "__main__":
    main()
