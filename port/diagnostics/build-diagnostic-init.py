#!/usr/bin/env python3
"""Build and validate the standalone or Android diagnostic initramfs."""
import argparse
import gzip
import hashlib
import json
import os
import pathlib
import shutil
import stat
import struct
import subprocess
import uuid
import zlib

ROOT = pathlib.Path(os.environ.get('ANDROID_ROOT', pathlib.Path.home() / 'android/gkd-pixel2')).resolve()
WORKSPACE = pathlib.Path(__file__).resolve().parents[1]
SOURCE = WORKSPACE / 'diagnostics'
OUTPUT = WORKSPACE / 'build-output/boot-diagnostics'
BUILD = ROOT / 'work/build/pixel2-diagnostic-init'
GCC = ROOT / 'prebuilts/gcc/linux-x86/aarch64/gcc-linaro-6.3.1-2017.05-x86_64_aarch64-linux-gnu/bin/aarch64-linux-gnu-gcc'


def cpio_entry(name, mode, data=b'', major=0, minor=0, ino=1):
    encoded = name.encode() + b'\0'
    values = [ino, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, 0, len(data), 0, 0, major, minor, len(encoded), 0]
    header = b'070701' + b''.join(f'{v:08x}'.encode() for v in values)
    result = header + encoded
    result += b'\0' * (-len(result) % 4)
    result += data + b'\0' * (-len(data) % 4)
    return result


def standalone_fstab(data):
    embedded = {b'/system_ext', b'/product'}
    removed = set()
    lines = []
    for line in data.splitlines(keepends=True):
        fields = line.split()
        if len(fields) < 2 or fields[0].startswith(b'#') or fields[1] not in embedded:
            lines.append(line)
            continue
        mount = fields[1]
        if (len(fields) != 5 or fields[0] != mount[1:] or fields[2] != b'ext4'
                or not {b'logical', b'first_stage_mount'} <= set(fields[4].split(b','))
                or mount in removed):
            raise ValueError(f'Unexpected early fstab entry for {mount.decode()}')
        removed.add(mount)
    if removed != embedded:
        raise ValueError('Original ramdisk must declare both early system_ext and product mounts')
    return b''.join(lines)


def append_android_probe(binary, base_ramdisk, standalone=False):
    original = base_ramdisk.read_bytes()
    size, checksum = struct.unpack_from('>I8xI', original, 12)
    compressed = original[64:]
    if len(compressed) != size or zlib.crc32(compressed) & 0xffffffff != checksum:
        raise ValueError('Original Android ramdisk integrity check failed')
    archive = gzip.decompress(compressed)
    offset = 0
    max_ino = 0
    new_archive = bytearray()
    changed_fstab = False
    while offset + 110 <= len(archive):
        if archive[offset:offset + 6] != b'070701':
            break
        fields = [
            int(archive[field:field + 8], 16) for field in range(offset + 6, offset + 110, 8)
        ]
        name_end = offset + 110 + fields[11]
        name = archive[offset + 110:name_end]
        data_start = (name_end + 3) & ~3
        data_end = data_start + fields[6]
        next_offset = (data_end + 3) & ~3
        if name == b'TRAILER!!!\0' and not any(archive[data_end:]):
            if standalone and not changed_fstab:
                raise ValueError('Original Android ramdisk lacks fstab.rk30board')
            new_archive += cpio_entry('p2-init', stat.S_IFREG | 0o755, binary, ino=max_ino + 1)
            new_archive += cpio_entry('TRAILER!!!', 0, ino=max_ino + 2)
            return bytes(new_archive) + b'\0' * (-len(new_archive) % 512)
        if standalone and name == b'fstab.rk30board\0':
            if changed_fstab or not stat.S_ISREG(fields[1]) or fields[4] != 1:
                raise ValueError('Expected a single regular Android ramdisk fstab')
            fstab = standalone_fstab(archive[data_start:data_end])
            size_field = offset + 6 + 6 * 8
            new_archive += archive[offset:size_field] + f'{len(fstab):08x}'.encode()
            new_archive += archive[size_field + 8:data_start] + fstab
            new_archive += b'\0' * (-len(fstab) % 4)
            changed_fstab = True
        else:
            new_archive += archive[offset:next_offset]
        max_ino = max(max_ino, fields[0])
        offset = next_offset
    raise ValueError('Could not locate the original Android ramdisk archive end')


def legacy_ramdisk(archive, title):
    compressed = gzip.compress(archive, compresslevel=9, mtime=0)
    header = bytearray(64)
    struct.pack_into('>7I4B32s', header, 0, 0x27051956, 0, 0, len(compressed), 0, 0,
                     zlib.crc32(compressed) & 0xffffffff, 5, 22, 3, 1, title.ljust(32, b'\0'))
    struct.pack_into('>I', header, 4, zlib.crc32(header) & 0xffffffff)
    return header + compressed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--android', action='store_true', help='add a boot probe to the existing Android ramdisk')
    mode.add_argument('--factory-display', action='store_true', help='capture the factory display and restart')
    parser.add_argument('--capture-display', action='store_true', help='read display registers before Android starts')
    parser.add_argument('--reinitialize-panel', action='store_true', help='restart the Pixel 2 panel before Android starts')
    parser.add_argument('--userspace-delay', type=int, default=55, help='seconds before timed Android log capture')
    parser.add_argument('--standalone-gamma', action='store_true',
                        help='use the GammaOS system image embedded product and system_ext')
    parser.add_argument('--storage-log', action='store_true',
                        help='capture the first Android data mount result on the test card')
    parser.add_argument('--late-userspace-log', action='store_true',
                        help='save two late Android crash and framework snapshots on the test card')
    parser.add_argument('--pointer', action='store_true', help='enable Select-controlled mouse emulation')
    parser.add_argument('--layout', type=pathlib.Path, default=WORKSPACE / 'build-output/pixel2-android-test/gpt-layout/partition-layout.json',
                        help='expected GPT layout for the diagnostic log target')
    parser.add_argument('--base-ramdisk', type=pathlib.Path,
                        default=WORKSPACE / 'build-output/pixel2-android-test/ramdisk.uimg',
                        help='board ramdisk in U-Boot image format')
    parser.add_argument('--output-dir', type=pathlib.Path, help='destination for the generated ramdisk')
    args = parser.parse_args()
    if args.userspace_delay < 0:
        parser.error('--userspace-delay must be nonnegative')
    if args.userspace_delay != 55 and (not args.android or args.capture_display):
        parser.error('--userspace-delay applies to timed Android logging')
    if args.capture_display and not args.android:
        parser.error('--capture-display requires --android')
    if args.reinitialize_panel and not args.capture_display:
        parser.error('--reinitialize-panel requires --capture-display')
    if args.standalone_gamma and not args.android:
        parser.error('--standalone-gamma requires --android')
    if args.storage_log and not args.android:
        parser.error('--storage-log requires --android')
    if args.late_userspace_log and not args.android:
        parser.error('--late-userspace-log requires --android')
    if args.pointer and not args.capture_display:
        parser.error('--pointer requires --capture-display')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    build = BUILD
    build.mkdir(parents=True, exist_ok=True)
    layout = json.loads(args.layout.read_text())
    parts = {p['name']: p for p in layout['partitions']}
    guid = uuid.UUID(layout['disk_guid'])
    (build / 'diagnostic_expect.h').write_text(
        '#define EXPECTED_DISK_BYTES ' + str(layout['disk_bytes']) + 'ULL\n'
        '#define EXPECTED_P1_START ' + str(parts['bootfiles']['start_lba']) + 'ULL\n'
        '#define EXPECTED_P1_SECTORS ' + str(parts['bootfiles']['size_sectors']) + 'ULL\n'
        '#define EXPECTED_METADATA_PARTITION ' + str(parts['metadata']['number']) + '\n'
        '#define EXPECTED_USERDATA_PARTITION ' + str(parts['userdata']['number']) + '\n'
        '#define EXPECTED_GUID_TEXT "' + str(guid) + '"\n'
        'static const unsigned char expected_disk_guid[16] = {' + ','.join(hex(b) for b in guid.bytes_le) + '};\n'
    )
    binary = build / ('p2-init' if args.android else 'init')
    compiler_flags = ['-DPIXEL2_ANDROID_BOOT'] if args.android else []
    if args.factory_display or args.capture_display:
        compiler_flags.append('-DPIXEL2_CAPTURE_DISPLAY')
    if args.storage_log:
        compiler_flags.append('-DPIXEL2_STORAGE_LOG')
    if args.reinitialize_panel:
        compiler_flags.append('-DPIXEL2_REINITIALIZE_PANEL')
    if args.late_userspace_log:
        compiler_flags.append('-DPIXEL2_LATE_USERSPACE_LOG')
    if args.userspace_delay != 55:
        compiler_flags.append(f'-DPIXEL2_ANDROID_LOG_DELAY={args.userspace_delay}')
    sources = [SOURCE / 'pixel2-init.c']
    if args.pointer:
        compiler_flags.append('-DPIXEL2_POINTER')
        sources.append(SOURCE / 'pixel2-pointer.c')
    subprocess.run([str(GCC), '-std=gnu11', '-static', '-Os', '-Wall', '-Wextra', '-Werror', '-I', str(build),
                    *compiler_flags, '-o', str(binary), *map(str, sources)], check=True)
    subprocess.run([str(GCC.with_name('aarch64-linux-gnu-strip')), str(binary)], check=True)
    elf = binary.read_bytes()
    assert elf[:5] == b'\x7fELF\x02' and struct.unpack_from('<H', elf, 18)[0] == 183
    phoff = struct.unpack_from('<Q', elf, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', elf, 54)
    assert all(struct.unpack_from('<I', elf, phoff + i * phsize)[0] != 3 for i in range(phnum)), 'Dynamic interpreter found'
    if args.android:
        target = args.output_dir or OUTPUT / 'android-5.10/network-fix'
        target.mkdir(parents=True, exist_ok=True)
        archive = append_android_probe(elf, args.base_ramdisk, standalone=args.standalone_gamma)
        image = legacy_ramdisk(archive, b'Pixel2 Android test ramdisk')
        assert gzip.decompress(image[64:]) == archive
        destination = target / 'ramdisk.uimg'
        destination.write_bytes(image)
        subprocess.run(['mkimage', '-l', str(destination)], check=True)
        return
    archive = bytearray()
    for index, name in enumerate(['.', 'dev', 'proc', 'sys', 'bootlog'], 1):
        archive += cpio_entry(name, stat.S_IFDIR | 0o755, ino=index)
    archive += cpio_entry('dev/console', stat.S_IFCHR | 0o600, major=5, minor=1, ino=6)
    archive += cpio_entry('init', stat.S_IFREG | 0o755, elf, ino=7)
    archive += cpio_entry('TRAILER!!!', 0, ino=8)
    archive += b'\0' * (-len(archive) % 512)
    if args.factory_display:
        target = args.output_dir or OUTPUT / 'display-compare'
        target.mkdir(parents=True, exist_ok=True)
        destination = target / 'stock-ramdisk.uimg'
        image = legacy_ramdisk(archive, b'Pixel2 factory display check')
        destination.write_bytes(image)
        assert gzip.decompress(image[64:]) == archive
        subprocess.run(['mkimage', '-l', str(destination)], check=True)
        return
    image = legacy_ramdisk(archive, b'Pixel2 diagnostic init')
    (OUTPUT / 'diag-initramfs.cpio.gz').write_bytes(image[64:])
    (OUTPUT / 'diag-init').write_bytes(elf)
    shutil.copyfile(BUILD / 'diagnostic_expect.h', OUTPUT / 'diagnostic_expect.h')
    destination = OUTPUT / 'diag-ramdisk.uimg'
    destination.write_bytes(image)
    assert gzip.decompress(image[64:]) == archive
    subprocess.run(['mkimage', '-l', str(destination)], check=True)
    subprocess.run(['file', str(OUTPUT / 'diag-init')], check=True)
    manifest = ['diag-init', 'diag-initramfs.cpio.gz', 'diag-ramdisk.uimg', 'diagnostic_expect.h']
    (OUTPUT / 'diagnostic-init-SHA256SUMS').write_text(''.join(
        hashlib.sha256((OUTPUT / name).read_bytes()).hexdigest() + '  ' + name + '\n' for name in manifest))
    print('Diagnostic initramfs built and checked. Writable mount requires exact saved GPT, size and FAT label.')


if __name__ == '__main__':
    main()
