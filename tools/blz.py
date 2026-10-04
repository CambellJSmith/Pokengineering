#!/usr/bin/env python3
from __future__ import annotations

import struct
from dataclasses import dataclass


class BlzError(ValueError):
    pass


@dataclass(frozen=True)
class BlzInfo:
    header_size: int
    compressed_length: int
    extra_size: int
    passthrough_length: int
    decoded_size: int


def inspect(data: bytes) -> BlzInfo | None:
    """Inspect Nintendo DS backwards-LZ (BLZ/code compression) metadata.

    The format stores an 8-byte size trailer at the end of the compressed
    region. A small amount of unrelated appended data is tolerated because
    ARM9 binaries can carry a footer; overlays normally do not.
    """
    if len(data) < 8:
        return None

    for appended in range(0, min(0x20, len(data) - 7), 4):
        end = len(data) - appended
        if end < 8:
            continue
        packed, extra_size = struct.unpack_from("<II", data, end - 8)
        header_size = (packed >> 24) & 0xFF
        compressed_length = packed & 0x00FFFFFF
        if header_size < 8 or header_size > end:
            continue
        if compressed_length < header_size or compressed_length > end:
            continue
        padding = data[end - header_size : end - 8]
        if any(value != 0xFF for value in padding):
            continue
        passthrough = end - compressed_length
        decoded_size = end + extra_size
        if decoded_size < passthrough:
            continue
        return BlzInfo(
            header_size=header_size,
            compressed_length=compressed_length,
            extra_size=extra_size,
            passthrough_length=passthrough,
            decoded_size=decoded_size + appended,
        )
    return None


def decompress(data: bytes) -> bytes:
    """Decompress Nintendo DS BLZ/code-compressed bytes.

    Tokens are consumed from the end toward the beginning and output is also
    produced backward. This is the executable-code compression used by Nitro
    overlays and commonly by ARM9 binaries.
    """
    info = inspect(data)
    if info is None:
        raise BlzError("payload does not contain a valid BLZ trailer")

    # Detect optional bytes appended after the BLZ stream. The inspector's
    # decoded_size includes them, so recover their amount from the chosen
    # trailer position by testing the same small aligned suffix range.
    appended = 0
    stream_end = len(data)
    for candidate in range(0, min(0x20, len(data) - 7), 4):
        end = len(data) - candidate
        if end < 8:
            continue
        packed, extra = struct.unpack_from("<II", data, end - 8)
        header = (packed >> 24) & 0xFF
        comp_len = packed & 0x00FFFFFF
        if (
            header == info.header_size
            and comp_len == info.compressed_length
            and extra == info.extra_size
            and end - comp_len == info.passthrough_length
            and header >= 8
            and all(value == 0xFF for value in data[end - header : end - 8])
        ):
            appended = candidate
            stream_end = end
            break

    stream = data[:stream_end]
    suffix = data[stream_end:]

    # An extra-size value of zero is the canonical uncompressed envelope.
    if info.extra_size == 0:
        return stream + suffix

    header_start = len(stream) - info.header_size
    compressed_start = info.passthrough_length
    compressed = stream[compressed_start:header_start]
    prefix = stream[:compressed_start]

    decoded_tail_size = len(stream) + info.extra_size - len(prefix)
    if decoded_tail_size <= 0:
        raise BlzError("invalid BLZ decoded size")
    output = bytearray(decoded_tail_size)
    out_pos = decoded_tail_size
    read_pos = len(compressed)

    while out_pos > 0:
        if read_pos <= 0:
            raise BlzError("BLZ stream ended before output was complete")
        flags = compressed[read_pos - 1]
        read_pos -= 1

        for bit in range(7, -1, -1):
            if out_pos == 0:
                break

            if flags & (1 << bit):
                if read_pos < 2:
                    raise BlzError("truncated BLZ back-reference")
                byte1 = compressed[read_pos - 1]
                byte2 = compressed[read_pos - 2]
                read_pos -= 2

                length = (byte1 >> 4) + 3
                displacement = (((byte1 & 0x0F) << 8) | byte2) + 3
                already_written = decoded_tail_size - out_pos

                # Some retail encoders use the reserved short-distance case at
                # the very end of a stream. Nitro-compatible decoders interpret
                # that case as distance 2 once at least two bytes exist.
                if displacement > already_written:
                    if already_written < 2:
                        raise BlzError(
                            f"BLZ back-reference distance {displacement} exceeds "
                            f"{already_written} produced bytes"
                        )
                    displacement = 2

                for _ in range(length):
                    if out_pos == 0:
                        break
                    destination = out_pos - 1
                    source = destination + displacement
                    if source >= decoded_tail_size:
                        raise BlzError("BLZ back-reference points outside decoded output")
                    output[destination] = output[source]
                    out_pos -= 1
            else:
                if read_pos <= 0:
                    raise BlzError("truncated BLZ literal")
                out_pos -= 1
                output[out_pos] = compressed[read_pos - 1]
                read_pos -= 1

    return bytes(prefix + output + suffix)
