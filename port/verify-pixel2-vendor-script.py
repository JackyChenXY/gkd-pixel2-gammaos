#!/usr/bin/env python3
"""Check the actual stock source parser's length-table semantics, including -1."""

import pathlib
import struct
import sys
import zlib


def decode_stock_script(image: bytes) -> bytes:
    if len(image) < 72:
        raise ValueError("SCRIPT image is too short")
    values = struct.unpack_from(">7I4B32s", image)
    header = bytearray(image[:64])
    struct.pack_into(">I", header, 4, 0)
    if values[0] != 0x27051956 or values[1] != zlib.crc32(header) & 0xFFFFFFFF:
        raise ValueError("Invalid legacy image header/CRC")
    payload = image[64:]
    if values[3] != len(payload) or values[6] != zlib.crc32(payload) & 0xFFFFFFFF:
        raise ValueError("Invalid payload size/CRC")
    if values[9] != 6:
        raise ValueError("The stock source parser requires IH_TYPE_SCRIPT")
    length = struct.unpack_from(">I", payload)[0]
    if length == 0:
        raise ValueError("The stock source parser rejects Empty Script")
    # Emulate actual source code at 0x208fb8..0x208fec: big-endian first
    # length, then native-word loads until CMN w3,#1 sees 0xffffffff.
    pointer = 0
    while pointer + 4 <= len(payload):
        word = struct.unpack_from("<I", payload, pointer)[0]
        pointer += 4
        if word == 0xFFFFFFFF:
            break
    else:
        raise ValueError("No vendor -1 sentinel: the device would scan beyond this image")
    if pointer + length > len(payload):
        raise ValueError("First script component extends beyond payload")
    return payload[pointer:pointer + length]


def zero_sentinel_image(image: bytes) -> bytes:
    wrong = bytearray(image)
    struct.pack_into(">I", wrong, 68, 0)
    struct.pack_into(">I", wrong, 24, zlib.crc32(wrong[64:]) & 0xFFFFFFFF)
    struct.pack_into(">I", wrong, 4, 0)
    struct.pack_into(">I", wrong, 4, zlib.crc32(wrong[:64]) & 0xFFFFFFFF)
    return bytes(wrong)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: verify-pixel2-vendor-script.py PACKAGE_DIRECTORY [...]")
    for directory in sys.argv[1:]:
        root = pathlib.Path(directory)
        image = (root / "boot.ini").read_bytes()
        source = (root / "boot-script.txt").read_text(encoding="utf-8-sig").encode("utf-8")
        assert struct.unpack_from(">I", image, 68)[0] == 0xFFFFFFFF
        assert decode_stock_script(image) == source
        assert len(image) == 72 + len(source)
        # The previous bug had valid CRCs. Rebuild both CRCs after setting zero
        # to ensure this regression check fails for semantics, not integrity.
        try:
            decode_stock_script(zero_sentinel_image(image))
        except ValueError as error:
            assert "sentinel" in str(error)
        else:
            raise AssertionError("A zero-terminated script passed the vendor semantics check")
        print(f"{root.name}: exact first script component recovered; zero sentinel regression rejected")


if __name__ == "__main__":
    main()
