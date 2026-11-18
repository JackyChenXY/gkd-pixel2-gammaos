/* Static diagnostic init for the Pixel 2 test card. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/reboot.h>
#include <sys/resource.h>
#include <linux/fb.h>
#include <linux/fs.h>
#include <sys/stat.h>
#include <sys/klog.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "diagnostic_expect.h"

#ifndef PIXEL2_ANDROID_LOG_DELAY
#define PIXEL2_ANDROID_LOG_DELAY 55
#endif

static int screen = -1;
static int serial_console = -1;
static int logfile = -1;

#ifdef PIXEL2_POINTER
int start_pixel2_pointer(int report, int console);
#endif

static unsigned le16(const unsigned char *p)
{
    return (unsigned)p[0] | (unsigned)p[1] << 8;
}

static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static int read_exact_at(int fd, void *data, size_t count, uint64_t offset)
{
    unsigned char *p = data;
    while (count) {
        ssize_t n = pread(fd, p, count, (off_t)offset);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return 0;
        p += n;
        count -= (size_t)n;
        offset += (size_t)n;
    }
    return 1;
}

/* Windows may keep "NO NAME    " in the BPB while its real volume label is a
 * root-directory entry. Follow at most 32 FAT32 directory clusters, read only. */
static int fat32_has_expected_label(int fd, const unsigned char *boot, uint64_t partition_bytes)
{
    static const char label[11] = "PIXEL2BOOT ";
    if (boot[510] != 0x55 || boot[511] != 0xaa || memcmp(boot + 82, "FAT32   ", 8)) return 0;
    unsigned sector_bytes = le16(boot + 11), sectors_per_cluster = boot[13];
    uint64_t reserved = le16(boot + 14), fats = boot[16], fat_sectors = le32(boot + 36);
    uint64_t total_sectors = le32(boot + 32);
    unsigned flags = le16(boot + 40);
    if (sector_bytes != 512 || !sectors_per_cluster || sectors_per_cluster > 128 ||
        (sectors_per_cluster & (sectors_per_cluster - 1)) || !reserved || !fats || fats > 4 ||
        !fat_sectors || !total_sectors || total_sectors > partition_bytes / sector_bytes ||
        le16(boot + 17) || le16(boot + 22) || le16(boot + 42)) return 0;
    if (reserved >= total_sectors || fat_sectors > (total_sectors - reserved) / fats) return 0;
    uint64_t data_sector = reserved + fats * fat_sectors;
    if (data_sector >= total_sectors) return 0;
    uint64_t cluster_count = (total_sectors - data_sector) / sectors_per_cluster;
    if (cluster_count < 65525 || cluster_count > 0x0fffffee || fat_sectors * sector_bytes / 4 < cluster_count + 2) return 0;
    unsigned active_fat = (flags & 0x80) ? flags & 0x0f : 0;
    if (active_fat >= fats) return 0;
    uint64_t fat_offset = (reserved + active_fat * fat_sectors) * sector_bytes;
    uint32_t cluster = le32(boot + 44) & 0x0fffffff;
    if (!memcmp(boot + 71, label, sizeof(label))) return 1;
    unsigned char buffer[65536];
    size_t cluster_bytes = (size_t)sector_bytes * sectors_per_cluster;
    for (unsigned hops = 0; hops < 32; ++hops) {
        if (cluster < 2 || cluster >= cluster_count + 2) return 0;
        uint64_t offset = (data_sector + (uint64_t)(cluster - 2) * sectors_per_cluster) * sector_bytes;
        if (offset > partition_bytes || cluster_bytes > partition_bytes - offset ||
            !read_exact_at(fd, buffer, cluster_bytes, offset)) return 0;
        for (size_t entry = 0; entry < cluster_bytes; entry += 32) {
            if (!buffer[entry]) return 0;
            if (buffer[entry] == 0xe5 || buffer[entry + 11] == 0x0f) continue;
            unsigned attr = buffer[entry + 11];
            if ((attr & 0x08) && !(attr & 0x10) && !memcmp(buffer + entry, label, sizeof(label))) return 1;
        }
        unsigned char next[4];
        uint64_t fat_entry = (uint64_t)cluster * 4;
        if (fat_entry + 4 > fat_sectors * sector_bytes ||
            !read_exact_at(fd, next, sizeof(next), fat_offset + fat_entry)) return 0;
        cluster = le32(next) & 0x0fffffff;
        if (cluster >= 0x0ffffff8 || cluster == 0x0ffffff7) return 0;
    }
    return 0;
}

static void write_all(int fd, const char *data, size_t length)
{
    if (fd < 0) return;
    while (length) {
        ssize_t n = write(fd, data, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return;
        data += n;
        length -= (size_t)n;
    }
}

static void message(const char *text)
{
    write_all(screen, text, strlen(text));
    if (serial_console != screen) write_all(serial_console, text, strlen(text));
}

static int read_small(const char *path, char *buffer, size_t size)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buffer, size - 1);
    int saved = errno;
    close(fd);
    errno = saved;
    if (n < 0) return -1;
    buffer[n] = 0;
    return 0;
}

static void copy_text(const char *path, size_t maximum)
{
    dprintf(logfile, "\n--- %s ---\n", path);
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { dprintf(logfile, "unavailable: %s\n", strerror(errno)); return; }
    char buffer[4096];
    while (maximum) {
        size_t want = maximum < sizeof(buffer) ? maximum : sizeof(buffer);
        ssize_t n = read(fd, buffer, want);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        write_all(logfile, buffer, (size_t)n);
        maximum -= (size_t)n;
    }
    close(fd);
}

static void list_directory(const char *path)
{
    dprintf(logfile, "\n--- directory %s ---\n", path);
    DIR *dir = opendir(path);
    if (!dir) { dprintf(logfile, "unavailable: %s\n", strerror(errno)); return; }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        if (entry->d_name[0] != '.') dprintf(logfile, "%s\n", entry->d_name);
    }
    closedir(dir);
}

static void capture_dmesg(void)
{
    dprintf(logfile, "\n--- kernel ring buffer (read only) ---\n");
    int capacity = klogctl(10, NULL, 0);
    if (capacity < 4096) capacity = 262144;
    if (capacity > 2097152) capacity = 2097152;
    char *buffer = malloc((size_t)capacity);
    if (!buffer) { dprintf(logfile, "allocation failed\n"); return; }
    int n = klogctl(3, buffer, capacity);
    if (n < 0) dprintf(logfile, "klogctl: %s\n", strerror(errno));
    else write_all(logfile, buffer, (size_t)n);
    free(buffer);
}

static int matching_card(unsigned unit, char *partition, size_t partition_size)
{
    char disk[64], path[160], value[64];
    unsigned char sector[512];
    snprintf(path, sizeof(path), "/sys/class/block/mmcblk%up1/start", unit);
    if (read_small(path, value, sizeof(value)) || strtoull(value, NULL, 10) != EXPECTED_P1_START) return 0;
    snprintf(path, sizeof(path), "/sys/class/block/mmcblk%up1/size", unit);
    if (read_small(path, value, sizeof(value)) || strtoull(value, NULL, 10) != EXPECTED_P1_SECTORS) return 0;
    snprintf(disk, sizeof(disk), "/dev/mmcblk%u", unit);
    int fd = open(disk, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    unsigned long long bytes = 0;
    int ok = ioctl(fd, BLKGETSIZE64, &bytes) == 0 && bytes == EXPECTED_DISK_BYTES;
    if (ok) ok = pread(fd, sector, sizeof(sector), 512) == (ssize_t)sizeof(sector);
    if (ok) ok = !memcmp(sector, "EFI PART", 8) && !memcmp(sector + 56, expected_disk_guid, 16);
    close(fd);
    if (!ok) return 0;
    snprintf(partition, partition_size, "/dev/mmcblk%up1", unit);
    fd = open(partition, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    struct stat st;
    ok = fstat(fd, &st) == 0 && S_ISBLK(st.st_mode);
    if (ok) ok = pread(fd, sector, sizeof(sector), 0) == (ssize_t)sizeof(sector);
    if (ok) ok = fat32_has_expected_label(fd, sector, EXPECTED_P1_SECTORS * 512ULL);
    close(fd);
    return ok;
}

static int mount_confirmed_card(unsigned *unit_out, unsigned attempts)
{
    /* Only a partition with the exact recorded GPT identity, size and FAT label is writable. */
    for (unsigned attempt = 0; attempt < attempts; ++attempt) {
        DIR *dir = opendir("/sys/class/block");
        if (dir) {
            struct dirent *entry;
            while ((entry = readdir(dir))) {
                unsigned unit, number;
                char extra;
                if (sscanf(entry->d_name, "mmcblk%up%u%c", &unit, &number, &extra) != 2 || number != 1 || unit > 31) continue;
                char partition[64];
                if (!matching_card(unit, partition, sizeof(partition))) continue;
                if (mount(partition, "/bootlog", "vfat", MS_NOSUID | MS_NODEV | MS_NOEXEC,
                          "utf8=1,shortname=mixed,errors=remount-ro") == 0) {
                    closedir(dir);
                    *unit_out = unit;
                    return 0;
                }
                char error[160];
                snprintf(error, sizeof(error), "Confirmed card found, but FAT mount failed: %s\n", strerror(errno));
                message(error);
            }
            closedir(dir);
        }
        sleep(1);
    }
    return -1;
}

static void header_bytes(unsigned unit, unsigned partition)
{
    char path[64];
    snprintf(path, sizeof(path), "/dev/mmcblk%up%u", unit, partition);
    unsigned char bytes[64];
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    dprintf(logfile, "\n--- read-only filesystem header %s offset 1024 ---\n", path);
    if (fd < 0) { dprintf(logfile, "unavailable: %s\n", strerror(errno)); return; }
    ssize_t n = pread(fd, bytes, sizeof(bytes), 1024);
    close(fd);
    if (n < 0) { dprintf(logfile, "read error: %s\n", strerror(errno)); return; }
    for (ssize_t i = 0; i < n; ++i) dprintf(logfile, "%02x%s", bytes[i], i % 16 == 15 ? "\n" : " ");
}

static void capture_state(unsigned unit, unsigned snapshot)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    dprintf(logfile, "\n========== snapshot %u at %ld.%03ld seconds ==========\n", snapshot, now.tv_sec, now.tv_nsec / 1000000);
    const char *paths[] = {"/proc/version", "/proc/cmdline", "/proc/meminfo", "/proc/partitions",
                           "/proc/mounts", "/proc/interrupts", "/proc/devices", "/proc/consoles", NULL};
    for (unsigned i = 0; paths[i]; ++i) copy_text(paths[i], 65536);
    list_directory("/sys/class/block");
    list_directory("/sys/class/udc");
    list_directory("/sys/class/drm");
    list_directory("/sys/class/graphics");
    list_directory("/sys/class/backlight");
    copy_text("/sys/class/graphics/fb0/name", 4096);
    copy_text("/sys/class/graphics/fb0/modes", 4096);
    header_bytes(unit, EXPECTED_METADATA_PARTITION);
    header_bytes(unit, EXPECTED_USERDATA_PARTITION);
    capture_dmesg();
    fsync(logfile);
    sync();
}

static void prepare_diagnostic_mounts(void)
{
    umask(077);
    mkdir("/dev", 0755); mkdir("/proc", 0755); mkdir("/sys", 0755); mkdir("/bootlog", 0755);
    mount("devtmpfs", "/dev", "devtmpfs", MS_NOSUID, "mode=0755");
    mount("proc", "/proc", "proc", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL);
    mount("sysfs", "/sys", "sysfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL);
}

#ifdef PIXEL2_CAPTURE_DISPLAY
static const unsigned vop_offsets[] = {
    0x010, 0x014, 0x018, 0x020, 0x028,
    0x050, 0x054, 0x05c, 0x060, 0x068, 0x06c, 0x070,
    0x090, 0x094, 0x098, 0x09c, 0x0a4, 0x0a8,
    0x100, 0x104, 0x108, 0x10c,
    0x190, 0x194, 0x198, 0x1a0, 0x1a4, 0x1a8,
};
static const unsigned dsi_offsets[] = {
    0x000, 0x004, 0x008, 0x00c, 0x010, 0x014, 0x018, 0x02c,
    0x034, 0x038, 0x03c, 0x040, 0x044, 0x048, 0x04c, 0x050,
    0x054, 0x058, 0x05c, 0x060, 0x064, 0x068,
    0x078, 0x08c, 0x094, 0x098, 0x09c, 0x0a0, 0x0a4, 0x0b0,
};
static const unsigned phy_offsets[] = {
    0x000, 0x004, 0x00c, 0x010, 0x014, 0x018, 0x01c, 0x020, 0x02c, 0x078,
    0x080, 0x084,
    // LP and HS timings for the clock lane and the two active data lanes.
    0x114, 0x118, 0x11c, 0x120, 0x124, 0x128, 0x130, 0x134, 0x138, 0x140, 0x144, 0x148,
    0x194, 0x198, 0x19c, 0x1a0, 0x1a4, 0x1a8, 0x1b0, 0x1b4, 0x1b8, 0x1c0, 0x1c4, 0x1c8,
    0x214, 0x218, 0x21c, 0x220, 0x224, 0x228, 0x230, 0x234, 0x238, 0x240, 0x244, 0x248,
};
static const unsigned cru_offsets[] = {
    0x040, 0x044, 0x048, 0x04c, 0x060, 0x064, 0x068, 0x06c, 0x0a0,
    0x114, 0x118, 0x120, 0x124, 0x208, 0x20c,
};
static const unsigned grf_offsets[] = {0x438};

static void capture_registers(int mem, const char *name, off_t address, const unsigned *offsets, size_t count)
{
    dprintf(logfile, "\n--- %s read-only registers at 0x%08llx ---\n", name, (unsigned long long)address);
    pid_t reader = fork();
    if (reader < 0) {
        dprintf(logfile, "Cannot start register reader: %s\n", strerror(errno));
        return;
    }
    if (reader == 0) {
        void *mapped = mmap(NULL, 4096, PROT_READ, MAP_SHARED, mem, address);
        if (mapped == MAP_FAILED) {
            dprintf(logfile, "Cannot map registers read-only: %s\n", strerror(errno));
            _exit(1);
        }
        const volatile uint32_t *registers = mapped;
        for (size_t i = 0; i < count; ++i)
            dprintf(logfile, "%03x=%08x\n", offsets[i], registers[offsets[i] / 4]);
        munmap(mapped, 4096);
        _exit(0);
    }
    int status;
    for (unsigned attempt = 0; attempt < 40; ++attempt) {
        pid_t result = waitpid(reader, &status, WNOHANG);
        if (result == reader) {
            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
                dprintf(logfile, "Register reader stopped with status 0x%x\n", status);
            return;
        }
        if (result < 0 && errno != EINTR) return;
        usleep(100000);
    }
    kill(reader, SIGKILL);
    dprintf(logfile, "Register reader timed out\n");
}

static int is_pixel2_board(void)
{
    char model[64];
    return read_small("/proc/device-tree/model", model, sizeof(model)) == 0 &&
           strcmp(model, "GameKiddy GKD Pixel2") == 0;
}

static void capture_display_parameters(int mount_debugfs, int mem)
{
    if (!is_pixel2_board()) {
        dprintf(logfile, "Display capture requires the Pixel 2 board.\n");
        return;
    }
    dprintf(logfile, "\n--- Pixel 2 display comparison ---\n");
    int fb = open("/dev/fb0", O_RDONLY | O_CLOEXEC);
    if (fb < 0) fb = open("/dev/graphics/fb0", O_RDONLY | O_CLOEXEC);
    struct fb_var_screeninfo mode;
    struct fb_fix_screeninfo info;
    int active = fb >= 0 && ioctl(fb, FBIOGET_VSCREENINFO, &mode) == 0 &&
                 ioctl(fb, FBIOGET_FSCREENINFO, &info) == 0;
    if (fb >= 0) close(fb);
    if (active)
        dprintf(logfile, "fb0: %ux%u, virtual %ux%u, %u bpp, pitch %u, rgb shifts %u/%u/%u\n",
                mode.xres, mode.yres, mode.xres_virtual, mode.yres_virtual, mode.bits_per_pixel,
                info.line_length, mode.red.offset, mode.green.offset, mode.blue.offset);

    const char *debugfs = "/sys/kernel/debug";
    int mounted = mount_debugfs &&
                  mount("debugfs", debugfs, "debugfs", MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC, NULL) == 0;
    copy_text("/sys/kernel/debug/dri/0/summary", 8192);
    copy_text("/sys/kernel/debug/dri/0/state", 16384);
    FILE *clocks = fopen("/sys/kernel/debug/clk/clk_summary", "r");
    if (clocks) {
        char line[512];
        dprintf(logfile, "\n--- display clocks ---\n");
        while (fgets(line, sizeof(line), clocks)) {
            if (strstr(line, "vop") || strstr(line, "dsi") || strstr(line, "dphy") || strstr(line, "pll_npll"))
                write_all(logfile, line, strlen(line));
        }
        fclose(clocks);
    }
    if (mounted) umount(debugfs);

    // Read only documented registers on the powered display path. Skip FIFOs and IRQ status.
    char enabled[32];
    char dpms[32];
    if (!active || mode.xres != 480 || mode.yres != 640 ||
        read_small("/sys/class/drm/card0-DSI-1/enabled", enabled, sizeof(enabled)) != 0 ||
        strcmp(enabled, "enabled\n") != 0 ||
        (read_small("/sys/class/drm/card0-DSI-1/dpms", dpms, sizeof(dpms)) == 0 && strcmp(dpms, "On\n") != 0)) {
        dprintf(logfile, "Panel scanout is unavailable for the register capture.\n");
        return;
    }
    if (mem < 0) {
        dprintf(logfile, "Read-only /dev/mem is unavailable.\n");
        return;
    }
    capture_registers(mem, "VOP", 0xff460000, vop_offsets, sizeof(vop_offsets) / sizeof(*vop_offsets));
    capture_registers(mem, "DSI host", 0xff450000, dsi_offsets, sizeof(dsi_offsets) / sizeof(*dsi_offsets));
    capture_registers(mem, "DSI PHY", 0xff2e0000, phy_offsets, sizeof(phy_offsets) / sizeof(*phy_offsets));
    capture_registers(mem, "Display clocks (CRU)", 0xff2b0000, cru_offsets, sizeof(cru_offsets) / sizeof(*cru_offsets));
    capture_registers(mem, "DSI routing (GRF)", 0xff140000, grf_offsets, sizeof(grf_offsets) / sizeof(*grf_offsets));
}
#endif

#ifdef PIXEL2_REINITIALIZE_PANEL
static void reinitialize_panel(void)
{
    if (!is_pixel2_board()) {
        dprintf(logfile, "Panel restart skipped outside the Pixel 2 board.\n");
        return;
    }

    int fb = open("/dev/fb0", O_RDWR | O_CLOEXEC);
    struct fb_var_screeninfo mode;
    if (fb < 0 || ioctl(fb, FBIOGET_VSCREENINFO, &mode) != 0 ||
        mode.xres != 480 || mode.yres != 640) {
        dprintf(logfile, "Panel restart skipped because the expected framebuffer was unavailable.\n");
        if (fb >= 0) close(fb);
        return;
    }

    if (ioctl(fb, FBIOBLANK, FB_BLANK_POWERDOWN) == 0) {
        dprintf(logfile, "Panel restart requested display powerdown.\n");
        usleep(500000);
    } else {
        dprintf(logfile, "Display powerdown error: %s\n", strerror(errno));
    }

    if (ioctl(fb, FBIOBLANK, FB_BLANK_UNBLANK) == 0)
        dprintf(logfile, "Panel restart requested display unblank.\n");
    else
        dprintf(logfile, "Display unblank error: %s\n", strerror(errno));

    close(fb);
}
#endif

#ifdef PIXEL2_ANDROID_BOOT
#ifdef PIXEL2_CAPTURE_DISPLAY
static void wait_for_android_boot(int events, int report)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    const time_t deadline = now.tv_sec + 50;
    struct pollfd reader = {.fd = events, .events = POLLIN};
    do {
        if (poll(&reader, 1, 500) > 0 && (reader.revents & (POLLIN | POLLERR))) {
            char record[8192];
            ssize_t length = read(events, record, sizeof(record) - 1);
            if (length > 0) {
                record[length] = '\0';
                if (strstr(record, "init: processing action (sys.boot_completed=1)")) {
                    dprintf(report, "Display capture triggered by Android boot completion.\n");
                    return;
                }
            } else if (length < 0 && errno != EAGAIN && errno != EINTR && errno != EPIPE) {
                reader.fd = -1;
            }
        }
        clock_gettime(CLOCK_MONOTONIC, &now);
    } while (now.tv_sec < deadline);
    dprintf(report, "Display capture triggered by the pre-suspend deadline.\n");
}
#endif

static void run_android_tool(int root, int out, int errors, char *const argv[], rlim_t max_bytes)
{
    pid_t child = fork();
    if (child < 0) {
        dprintf(errors, "Cannot start %s: %s\n", argv[0], strerror(errno));
        return;
    }
    if (child == 0) {
        struct rlimit limit = {.rlim_cur = max_bytes, .rlim_max = max_bytes};
        int output_fd = fcntl(out, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
        int error_fd = fcntl(errors, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
        if (fchdir(root) != 0 || chroot(".") != 0 || chdir("/") != 0 ||
            output_fd < 0 || error_fd < 0 || dup2(output_fd, STDOUT_FILENO) < 0 || dup2(error_fd, STDERR_FILENO) < 0 ||
            setrlimit(RLIMIT_FSIZE, &limit) != 0) {
            dprintf(errors, "Cannot prepare %s: %s\n", argv[0], strerror(errno));
            _exit(126);
        }
        execv(argv[0], argv);
        dprintf(errors, "Cannot run %s: %s\n", argv[0], strerror(errno));
        _exit(127);
    }

    int status;
    for (unsigned attempt = 0; attempt < 60; ++attempt) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) {
            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
                dprintf(errors, "%s ended with status 0x%x\n", argv[0], status);
            return;
        }
        if (result < 0 && errno != EINTR) return;
        usleep(250000);
    }
    dprintf(errors, "%s timed out\n", argv[0]);
    kill(child, SIGKILL);
    waitpid(child, &status, 0);
}

static int open_android_log_root(int proc)
{
    int root = -1;
    for (unsigned attempt = 0; attempt < 15; ++attempt) {
        root = openat(proc, "1/root", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
        if (root >= 0) {
            struct stat reader;
            if (fstatat(root, "dev/socket/logdr", &reader, 0) == 0 && S_ISSOCK(reader.st_mode)) break;
            close(root);
            root = -1;
        }
        sleep(2);
    }
    return root;
}

#ifdef PIXEL2_STORAGE_LOG
static void capture_android_storage(int proc, int events, int report)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    const time_t deadline = now.tv_sec + 28;
    struct pollfd reader = {.fd = events, .events = POLLIN};

    // Capture the first mount result before other services fill logd's buffers.
    while (now.tv_sec < deadline) {
        if (poll(&reader, 1, 250) > 0 && (reader.revents & (POLLIN | POLLERR))) {
            char record[8192];
            ssize_t length = read(events, record, sizeof(record) - 1);
            if (length > 0) {
                record[length] = '\0';
                if (strstr(record, "vdc: Command: cryptfs encryptFstab ") ||
                    strstr(record, "init: Userdata mounted using ")) break;
            } else if (length < 0 && errno != EAGAIN && errno != EINTR && errno != EPIPE) {
                reader.fd = -1;
            }
        }
        clock_gettime(CLOCK_MONOTONIC, &now);
    }

    clock_gettime(CLOCK_MONOTONIC, &now);
    dprintf(report, "Storage snapshot at %ld.%03ld seconds\n", now.tv_sec, now.tv_nsec / 1000000);
    int root = open_android_log_root(proc);
    if (root < 0) {
        dprintf(report, "Android log service was unavailable.\n");
    } else {
        char *const read_logs[] = {"/system/bin/logcat", "-d", "-b", "system", "-b", "main",
                                   "-b", "crash", "-v", "threadtime", "vold:V",
                                   "VoldNativeService:V", "vdc:V", "KeyStorage:V",
                                   "Keymaster:V", "keymaster:V", "keystore2:V",
                                   "wait_for_keymaster:V", "init:I", "*:S", NULL};
        run_android_tool(root, report, report, read_logs, 128 * 1024);
        close(root);
    }
    fsync(report);
}
#endif

static void capture_android_userspace(int proc, int logcat, int screenshot, int display_mem)
{
    int root = open_android_log_root(proc);
    if (root < 0) {
        dprintf(logcat, "Android log service was unavailable.\n");
        fsync(logcat);
        return;
    }

#ifdef PIXEL2_CAPTURE_DISPLAY
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    dprintf(logcat, "\n--- Display registers with Android running at %ld.%03ld seconds ---\n",
            now.tv_sec, now.tv_nsec / 1000000);
    pid_t display_reader = fork();
    if (display_reader == 0) {
        logfile = logcat;
        if (fchdir(root) != 0 || chroot(".") != 0 || chdir("/") != 0) {
            dprintf(logfile, "Cannot access Android display state: %s\n", strerror(errno));
            _exit(1);
        }
        capture_display_parameters(0, display_mem);
        _exit(0);
    }
    if (display_reader < 0) dprintf(logcat, "Cannot start the display snapshot: %s\n", strerror(errno));
    if (display_reader > 0) {
        while (waitpid(display_reader, NULL, 0) < 0 && errno == EINTR) {}
    }
    fsync(logcat);
#else
    (void)display_mem;
#endif

    char *const boot_status[] = {"/system/bin/getprop", "sys.boot_completed", NULL};
    char *const netd_status[] = {"/system/bin/getprop", "init.svc.netd", NULL};
    char *const zygote_status[] = {"/system/bin/getprop", "init.svc.zygote", NULL};
    char *const read_logs[] = {"/system/bin/logcat", "-d", "-b", "main", "-b", "system", "-b", "crash", "-v", "threadtime",
                               "-t", "800", "Zygote:V", "AndroidRuntime:V", "libc:V", "DEBUG:V", "netd:V",
                               "SurfaceFlinger:I", "hwcomposer:I", "BootAnimation:I", "*:W", NULL};
    char *const display_state[] = {"/system/bin/cat", "/sys/kernel/debug/dri/0/summary", NULL};
    dprintf(logcat, "sys.boot_completed:\n");
    run_android_tool(root, logcat, logcat, boot_status, 384 * 1024);
    dprintf(logcat, "init.svc.netd:\n");
    run_android_tool(root, logcat, logcat, netd_status, 384 * 1024);
    dprintf(logcat, "init.svc.zygote:\n");
    run_android_tool(root, logcat, logcat, zygote_status, 384 * 1024);
    dprintf(logcat, "\n--- Android boot and crash logs ---\n");
    run_android_tool(root, logcat, logcat, read_logs, 384 * 1024);
    dprintf(logcat, "\n--- Rockchip DRM output state ---\n");
    run_android_tool(root, logcat, logcat, display_state, 384 * 1024);
    fsync(logcat);
    if (screenshot >= 0) {
        char *const read_screen[] = {"/system/bin/screencap", "-p", NULL};
        run_android_tool(root, screenshot, logcat, read_screen, 512 * 1024);
        fsync(screenshot);
        fsync(logcat);
    }
    close(root);
}

static void record_android_tail(int kmsg)
{
    struct pollfd reader = {.fd = kmsg, .events = POLLIN};
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    const time_t deadline = now.tv_sec + 150;
    size_t remaining = 512 * 1024;
    time_t last_flush = now.tv_sec;
    while (remaining && now.tv_sec < deadline) {
        if (poll(&reader, 1, 1000) > 0 && (reader.revents & (POLLIN | POLLERR))) {
            char record[8192];
            ssize_t count = read(kmsg, record, sizeof(record));
            if (count > 0) {
                size_t length = (size_t)count < remaining ? (size_t)count : remaining;
                write_all(logfile, record, length);
                remaining -= length;
            } else if (count < 0 && errno != EAGAIN && errno != EINTR && errno != EPIPE) {
                break;
            }
        }
        clock_gettime(CLOCK_MONOTONIC, &now);
        if (now.tv_sec - last_flush >= 2) {
            fsync(logfile);
            last_flush = now.tv_sec;
        }
    }
    close(kmsg);
    dprintf(logfile, "\n--- boot log collection ended ---\n");
    fsync(logfile);
    close(logfile);
}

int main(void)
{
    prepare_diagnostic_mounts();
    serial_console = open("/dev/console", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    unsigned unit = 0;
    if (mount_confirmed_card(&unit, 15) == 0) {
        logfile = open("/bootlog/pixel2-android-boot.log", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (logfile >= 0) {
            int display_mem = -1;
            dprintf(logfile, "Kernel and diagnostic init reached before Android. Confirmed GPT: %s\n", EXPECTED_GUID_TEXT);
#ifdef PIXEL2_REINITIALIZE_PANEL
            reinitialize_panel();
#endif
#ifdef PIXEL2_POINTER
            if (is_pixel2_board()) {
                if (start_pixel2_pointer(logfile, serial_console) == 0)
                    dprintf(logfile, "Pixel 2 virtual gamepad and pointer initialized.\n");
                else
                    dprintf(logfile, "Pixel 2 virtual pointer unavailable; physical controls active: %s\n",
                            strerror(errno));
            }
#endif
            capture_state(unit, 0);
#ifdef PIXEL2_CAPTURE_DISPLAY
            display_mem = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
            capture_display_parameters(1, display_mem);
            int boot_events = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (boot_events >= 0) lseek(boot_events, 0, SEEK_END);
#endif
            dprintf(logfile, "\n--- launching Android /init ---\n");
            fsync(logfile);

            int kmsg = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (kmsg >= 0) {
                lseek(kmsg, 0, SEEK_END);
                if (fork() == 0) {
                    // Inherited file descriptors remain usable after PID 1 detaches the mounts.
                    record_android_tail(kmsg);
                    _exit(0);
                }
                close(kmsg);
            }

            int proc = open("/proc", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
#ifdef PIXEL2_STORAGE_LOG
            if (proc >= 0) {
                int events = open("/dev/kmsg", O_RDONLY | O_NONBLOCK | O_CLOEXEC);
                if (events >= 0) lseek(events, 0, SEEK_END);
                int report = open("/bootlog/pixel2-storage.log",
                                  O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
                if (report >= 0 && fork() == 0) {
                    capture_android_storage(proc, events, report);
                    _exit(0);
                }
                if (report >= 0) close(report);
                if (events >= 0) close(events);
            }
#endif
            int logcat = open("/bootlog/pixel2-logcat.log", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
            int screenshot = open("/bootlog/pixel2-screen.png", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
            if (proc >= 0 && logcat >= 0 && fork() == 0) {
                close(logfile);
#ifdef PIXEL2_CAPTURE_DISPLAY
                wait_for_android_boot(boot_events, logcat);
                if (boot_events >= 0) close(boot_events);
#else
                // Let the framework start before collecting its recent errors.
                sleep(PIXEL2_ANDROID_LOG_DELAY);
#endif
                capture_android_userspace(proc, logcat, screenshot, display_mem);
                _exit(0);
            }
#ifdef PIXEL2_CAPTURE_DISPLAY
            if (boot_events >= 0) close(boot_events);
            if (display_mem >= 0) close(display_mem);
#endif
            if (proc >= 0) close(proc);
            if (logcat >= 0) close(logcat);
            if (screenshot >= 0) close(screenshot);
            close(logfile);
        }
        umount2("/bootlog", MNT_DETACH);
    }
    int report = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
    umount2("/sys", MNT_DETACH);
    umount2("/proc", MNT_DETACH);
    umount2("/dev", MNT_DETACH);
    char *const argv[] = {"/init", NULL};
    execv(argv[0], argv);
    if (report >= 0) dprintf(report, "<3>p2-init: Android /init exec failed: %s\n", strerror(errno));
    message("Could not start Android /init.\n");
    for (;;) sleep(60);
}
#elif defined(PIXEL2_CAPTURE_DISPLAY)
int main(void)
{
    prepare_diagnostic_mounts();
    serial_console = open("/dev/console", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    screen = open("/dev/tty0", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    message("\033[2J\033[HGKD PIXEL 2\n\nSTOCK DISPLAY CHECK\nThe device will restart into Android.\n");
    unsigned unit = 0;
    if (mount_confirmed_card(&unit, 15) == 0) {
        logfile = open("/bootlog/pixel2-display-stock.log", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (logfile >= 0) {
            capture_state(unit, 0);
            int mem = open("/dev/mem", O_RDONLY | O_SYNC | O_CLOEXEC);
            capture_display_parameters(1, mem);
            if (mem >= 0) close(mem);
            int saved = fsync(logfile) == 0;
            close(logfile);
            if (saved) {
                int marker = open("/bootlog/P2DISP.OK", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
                if (marker >= 0) {
                    static const char tag[] = "P2DSP1\r\n";
                    saved = write(marker, tag, sizeof(tag) - 1) == (ssize_t)(sizeof(tag) - 1) && fsync(marker) == 0;
                    close(marker);
                    if (saved) {
                        sync();
                        if (umount("/bootlog") == 0) {
                            message("\nStock display record saved. Restarting into Android.\n");
                            sleep(4);
                            reboot(RB_AUTOBOOT);
                        }
                    }
                }
            }
        }
    }
    message("\nDisplay check stopped. Power off and return the card.\n");
    for (;;) sleep(60);
}
#else
int main(void)
{
    umask(077);
    prepare_diagnostic_mounts();
    serial_console = open("/dev/console", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    screen = open("/dev/tty0", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    message("\033[2J\033[HGKD PIXEL 2 DIAGNOSTIC\n\nKERNEL + INIT REACHED\nAndroid services are not being started.\nSearching for the confirmed PIXEL2BOOT card...\n");
    unsigned unit = 0;
    if (mount_confirmed_card(&unit, 60) == 0) {
        logfile = open("/bootlog/pixel2-diagnostic.log", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (logfile >= 0) {
            dprintf(logfile, "GKD Pixel 2 standalone diagnostic init reached; no Android services started.\nExpected GPT GUID: %s\nWritable target: /dev/mmcblk%up1, PIXEL2BOOT only.\n", EXPECTED_GUID_TEXT, unit);
            capture_state(unit, 0);
            message("\nLOG SAVED: PIXEL2BOOT/pixel2-diagnostic.log\nCollecting final kernel messages for 30 seconds...\n");
            sleep(5); capture_state(unit, 1);
            sleep(25); capture_state(unit, 2);
            close(logfile); logfile = -1;
            sync();
            if (umount("/bootlog") == 0)
                message("\nDIAGNOSTIC COMPLETE. Log saved and card unmounted.\nYou may power off and return the card to the computer.\n");
            else message("\nDIAGNOSTIC COMPLETE. Log synced; FAT unmount failed.\nWait before powering off.\n");
        } else message("\nERROR: cannot create diagnostic log.\n");
    } else message("\nNo exact matching PIXEL2BOOT card found. No storage was written.\n");
    for (;;) sleep(60); /* PID 1 must never exit. */
}
#endif
