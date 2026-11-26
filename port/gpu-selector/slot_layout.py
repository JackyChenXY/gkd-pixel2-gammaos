"""Validate both GPT copies of the released Pixel 2 card and reserve its Mali slot."""
import hashlib
import struct
import uuid
import zlib

SECTOR = 512
TABLE_SIZE = 128 * 128
DISK_GUID = uuid.UUID("10e4d830-2e2a-409a-b641-c9ccd806744c").bytes_le
SLOT_ID = uuid.UUID("40c0c68f-e8a8-4ea1-90e5-f649f5628a17").bytes_le
LINUX_DATA = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4").bytes_le
LINUX_RESERVED = uuid.UUID("8da63339-0007-60c0-c436-083ac8230908").bytes_le
TEMPLATE_TABLE = "fca82b0c0f8152b912547d4c8ee19beab8390fef12a14f785a831788ef0122f4"
FACTORY_LAST = 14680063
TYPE_OFFSET = 9 * 128
USER_END = 14 * 128 + 40


def update_header(block, table, current, alternate, table_lba):
    last = max(current, alternate)
    if (len(block) != SECTOR or block[:8] != b"EFI PART" or
            struct.unpack_from("<II", block, 8) != (0x10000, 92) or
            block[56:72] != DISK_GUID or
            struct.unpack_from("<4Q", block, 24) != (current, alternate, 34, last - 33) or
            struct.unpack_from("<QII", block, 72) != (table_lba, 128, 128)):
        raise ValueError("Unexpected Pixel 2 GPT header")
    buf = bytearray(block)
    stored_crc, = struct.unpack_from("<I", buf, 16)
    buf[16:20] = bytes(4)
    if zlib.crc32(buf[:92]) != stored_crc:
        raise ValueError("GPT header checksum mismatch")
    struct.pack_into("<I", buf, 88, zlib.crc32(table))
    struct.pack_into("<I", buf, 16, zlib.crc32(buf[:92]))
    return bytes(buf)


def reserve(primary, backup, disk_bytes):
    """Return updated primary and backup images. The caller controls storage and writes."""
    last = disk_bytes // SECTOR - 1
    if (disk_bytes % SECTOR or last < FACTORY_LAST or
            len(primary) != TABLE_SIZE + 2 * SECTOR or len(backup) != TABLE_SIZE + SECTOR):
        raise ValueError("Wrong capacity or GPT copy sizes")
    table = primary[2 * SECTOR:]
    old_crc = zlib.crc32(table)
    if (primary[510:512] != b"\x55\xaa" or primary[450] != 0xee or
            backup[:-SECTOR] != table or
            int.from_bytes(primary[SECTOR + 88:SECTOR + 92], "little") != old_crc or
            int.from_bytes(backup[-SECTOR + 88:-SECTOR + 92], "little") != old_crc):
        raise ValueError("Invalid protective MBR, mismatched GPT copies or entries checksum")
    entry = table[TYPE_OFFSET:TYPE_OFFSET + 128]
    if (entry[:16] not in (LINUX_DATA, LINUX_RESERVED) or entry[16:32] != SLOT_ID or
            struct.unpack_from("<3Q", entry, 32) != (641024, 1402879, 0) or
            entry[56:].decode("utf-16le").rstrip("\0") != "backup" or
            struct.unpack_from("<Q", table, USER_END)[0] != last - 33):
        raise ValueError("Unexpected Mali or userdata partition")
    # First boot expands userdata. Validate all 128 entries against the original
    # template after normalizing just its final LBA and the two accepted slot types.
    normalized = bytearray(table)
    normalized[TYPE_OFFSET:TYPE_OFFSET + 16] = LINUX_DATA
    struct.pack_into("<Q", normalized, USER_END, FACTORY_LAST - 33)
    if hashlib.sha256(normalized).hexdigest() != TEMPLATE_TABLE:
        raise ValueError("Other partition metadata differs from the released card")
    updated = bytearray(table)
    updated[TYPE_OFFSET:TYPE_OFFSET + 16] = LINUX_RESERVED
    head = update_header(primary[SECTOR:2 * SECTOR], updated, 1, last, 2)
    tail = update_header(backup[-SECTOR:], updated, last, 1, last - 32)
    return primary[:SECTOR] + head + updated, bytes(updated) + tail
