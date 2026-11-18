#!/usr/bin/env python3
"""Exercise the C FAT32 label reader with a synthetic, sparse volume."""
import pathlib
import struct
import subprocess
import tempfile

SOURCE = pathlib.Path(__file__).resolve().parent

WRAPPER = r'''
#define main diagnostic_pid1_not_called
#include "pixel2-init.c"
#undef main

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    int fd = open(argv[1], O_RDONLY);
    unsigned char boot[512];
    if (fd < 0 || !read_exact_at(fd, boot, sizeof(boot), 0)) return 2;
    int found = fat32_has_expected_label(fd, boot, EXPECTED_P1_SECTORS * 512ULL);
    close(fd);
    return found ? 0 : 1;
}
'''

TEST_HEADER = '''
#define EXPECTED_DISK_BYTES 0ULL
#define EXPECTED_P1_START 32768ULL
#define EXPECTED_P1_SECTORS 262144ULL
#define EXPECTED_METADATA_PARTITION 12
#define EXPECTED_USERDATA_PARTITION 15
#define EXPECTED_GUID_TEXT "00000000-0000-0000-0000-000000000000"
static const unsigned char expected_disk_guid[16] = {0};
'''


def main():
    with tempfile.TemporaryDirectory(prefix="pixel2-fat-check-") as directory:
        target = pathlib.Path(directory)
        (target / "diagnostic_expect.h").write_text(TEST_HEADER)
        wrapper = target / "reader.c"
        wrapper.write_text(WRAPPER)
        reader = target / "reader"
        subprocess.run(["gcc", "-O2", "-I", str(target), "-I", str(SOURCE),
                        "-o", str(reader), str(wrapper)], check=True)
        path = target / "partition.img"

        sector, spc, reserved, fats, fat_sectors, total = 512, 1, 32, 2, 2048, 262144
        cluster = 2
        cluster_size = sector * spc
        data_start = (reserved + fats * fat_sectors) * sector
        root_offset = data_start
        expected = b"PIXEL2BOOT "
        label_offset = root_offset
        root_entry = bytearray(cluster_size)
        root_entry[:11] = expected
        root_entry[11] = 8

        boot = bytearray(sector)
        struct.pack_into("<HBHB", boot, 11, sector, spc, reserved, fats)
        struct.pack_into("<II", boot, 32, total, fat_sectors)
        struct.pack_into("<I", boot, 44, cluster)
        boot[71:82] = b"NO NAME    "
        boot[82:90] = b"FAT32   "
        boot[510:512] = bytes((0x55, 0xAA))

        def reset():
            with path.open("wb") as volume:
                volume.truncate(total * sector)
                volume.write(boot)
                volume.seek(reserved * sector + cluster * 4)
                volume.write(struct.pack("<I", 0x0FFFFFFF))
                volume.seek(root_offset)
                volume.write(root_entry)

        def patch(offset, value):
            with path.open('r+b') as f:
                f.seek(offset)
                f.write(value)

        def check(name, found):
            result = subprocess.run([str(reader), str(path)])
            assert result.returncode == (0 if found else 1), (name, result.returncode)
            print(name + ': PASS')

        reset()
        check('NO NAME BPB + root volume label', True)
        patch(label_offset, b'WRONG LABEL')
        check('Wrong root label rejected', False)
        reset()
        patch(label_offset, b'\xe5')
        check('Deleted volume-label entry rejected', False)
        reset()
        patch(label_offset + 11, b'\x0f')
        check('Long filename entry cannot impersonate volume label', False)
        reset()
        cluster_count = (total - data_start // sector) // spc
        patch(44, struct.pack('<I', cluster_count + 2))
        check('Out-of-bounds root cluster rejected', False)
        reset()
        # Replace the first directory cluster with deleted entries, forcing a FAT lookup.
        deleted = (b'\xe5' + b'\0' * 31) * (cluster_size // 32)
        patch(root_offset, deleted)
        patch(reserved * sector + cluster * 4, struct.pack('<I', cluster))
        check('Cyclic FAT chain rejected within 32-cluster bound', False)
        reset()
        patch(root_offset, deleted)
        next_cluster = cluster + 1
        patch(reserved * sector + cluster * 4, struct.pack('<I', next_cluster))
        second = bytearray(cluster_size)
        second[:11] = expected
        second[11] = 8
        patch(data_start + (next_cluster - 2) * cluster_size, second)
        check('Valid root label in next FAT cluster accepted', True)
    print('All checks used a synthetic volume file.')


if __name__ == '__main__':
    main()
