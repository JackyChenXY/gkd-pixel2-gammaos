#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/f2fs.h>
#include <linux/fscrypt.h>
#include <linux/fs.h>
#include <sys/syscall.h>
#include <linux/magic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/swap.h>
#include <sys/sysmacros.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <unistd.h>

#define SWAP_DIR "pixel2-swap"
#define SWAP_FILE "swapfile"
#define PENDING_FILE ".swapfile.new"
#define SWAP_PATH "/data/" SWAP_DIR "/" SWAP_FILE
#define PENDING_PATH "/data/" SWAP_DIR "/" PENDING_FILE
#define STATUS_PROPERTY "sys.pixel2.extra_swap.status"
#define PRIORITY_PROPERTY "sys.pixel2.extra_swap.priority"
#define GIB (1024LL * 1024 * 1024)
#define SWAP_BYTES (2 * GIB)
#define RESERVE_BYTES GIB
#define ZRAM_FIRST_PRIORITY 10
#define SHARED_PRIORITY 100  /* Matches this board's fstab.pixel2.zram. */

static int fail(const char *operation)
{
    int error = errno;
    fprintf(stderr, "pixel2-extra-swap: %s: %s\n", operation, strerror(error));
    errno = error;
    return -1;
}

static int reject(const char *operation, int error)
{
    errno = error;
    return fail(operation);
}

/* Match the encrypted /data mapper to this board's direct userdata partition. */
static bool is_direct_userdata(dev_t mounted_device)
{
    struct stat userdata;
    if (stat("/dev/block/by-name/userdata", &userdata) < 0 || !S_ISBLK(userdata.st_mode))
        return false;

    char path[512];
    int base = snprintf(path, sizeof(path), "/sys/dev/block/%u:%u",
                        major(mounted_device), minor(mounted_device));
    snprintf(path + base, sizeof(path) - (size_t)base, "/dm/name");
    FILE *name_file = fopen(path, "re");
    if (name_file == NULL)
        return false;

    char name[96];
    bool is_userdata = fgets(name, sizeof(name), name_file) != NULL &&
                       strcmp(name, "userdata\n") == 0;
    fclose(name_file);
    if (!is_userdata)
        return false;

    int slaves_end = base + snprintf(path + base, sizeof(path) - (size_t)base, "/slaves");
    DIR *slaves = opendir(path);
    if (slaves == NULL)
        return false;

    unsigned int count = 0;
    bool matches = false;
    struct dirent *entry;
    while ((entry = readdir(slaves)) != NULL) {
        if (entry->d_name[0] == '.')
            continue;
        if (++count > 1)
            break;

        int length = snprintf(path + slaves_end, sizeof(path) - (size_t)slaves_end,
                              "/%s/dev", entry->d_name);
        if (length < 0 || (size_t)length >= sizeof(path) - (size_t)slaves_end)
            break;

        FILE *device_file = fopen(path, "re");
        if (device_file == NULL)
            break;

        unsigned int slave_major;
        unsigned int slave_minor;
        matches = fscanf(device_file, "%u:%u", &slave_major, &slave_minor) == 2 &&
                  slave_major == major(userdata.st_rdev) && slave_minor == minor(userdata.st_rdev);
        fclose(device_file);
        // A directory read error must not turn a matching first entry into a success.
        errno = 0;
    }
    matches = matches && count == 1 && errno == 0;
    closedir(slaves);
    return matches;
}

static bool is_unencrypted(int fd)
{
    struct fscrypt_policy_v1 policy;
    return ioctl(fd, FS_IOC_GET_ENCRYPTION_POLICY, &policy) < 0 && errno == ENODATA;
}

static bool is_private_regular(const struct stat *info)
{
    return S_ISREG(info->st_mode) && (info->st_mode & 07777) == 0600 &&
           info->st_uid == 0 && info->st_gid == 0 && info->st_nlink == 1;
}

static int validate_swapfile(int fd)
{
    struct stat info;
    if (fstat(fd, &info) < 0)
        return fail("stat swapfile");
    if (!is_private_regular(&info) || info.st_size != SWAP_BYTES ||
        info.st_blocks < SWAP_BYTES / 512)
        return reject("swapfile must be private and fully allocated at 2 GiB", EINVAL);
    if (!is_unencrypted(fd))
        return reject("swapfile has an fscrypt policy or its policy cannot be read", EPERM);

    off_t first_hole = lseek(fd, 0, SEEK_HOLE);
    if (first_hole < 0)
        return fail("check swapfile extents");
    if (first_hole != SWAP_BYTES)
        return reject("swapfile contains a hole", EINVAL);
    return 0;
}

static int check_free_space(int dir_fd, uint64_t allocation)
{
    struct statvfs free_space;
    if (fstatvfs(dir_fd, &free_space) < 0)
        return fail("measure free space on userdata");
    if (free_space.f_frsize == 0)
        return reject("userdata reported an invalid block size", EINVAL);

    uint64_t space_needed = allocation + RESERVE_BYTES;
    uint64_t needed_blocks = (space_needed + free_space.f_frsize - 1) / free_space.f_frsize;
    if (free_space.f_bavail < needed_blocks)
        return reject("need 1 GiB free after allocating swap", ENOSPC);
    return 0;
}

/* Remove only known private files after checking that neither is in /proc/swaps. */
static int remove_private_file(int dir_fd, const char *name)
{
    int fd = openat(dir_fd, name, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0)
        return errno == ENOENT ? 0 : fail("open inactive swap path");

    struct stat info;
    int result = fstat(fd, &info);
    int saved_errno = errno;
    close(fd);
    if (result < 0)
        return reject("inspect inactive swap path", saved_errno);
    if (!is_private_regular(&info))
        return reject("refuse to remove an unexpected swap path", EPERM);
    if (unlinkat(dir_fd, name, 0) < 0)
        return fail("remove inactive swap file");
    return 0;
}

static int publish_swapfile(int dir_fd)
{
    if (check_free_space(dir_fd, SWAP_BYTES) < 0)
        return -1;

    int fd = openat(dir_fd, PENDING_FILE,
                    O_WRONLY | O_CREAT | O_NOFOLLOW | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0)
        return fail("create private swapfile");

    unsigned int pin = 1;
    int result = -1;
    if (ioctl(fd, F2FS_IOC_SET_PIN_FILE, &pin) < 0)
        fail("pin swapfile before allocation");
    else if (fallocate(fd, 0, 0, SWAP_BYTES) < 0)
        fail("allocate 2 GiB on F2FS");
    else if (validate_swapfile(fd) == 0 && check_free_space(dir_fd, 0) == 0) {
        if (fsync(fd) < 0)
            fail("sync new swapfile");
        else if (syscall(SYS_renameat2, dir_fd, PENDING_FILE, dir_fd, SWAP_FILE, RENAME_NOREPLACE) < 0)
            fail("publish new swapfile");
        else if (fsync(dir_fd) < 0)
            fail("sync swapfile directory");
        else
            result = 0;
    }

    int saved_errno = errno;
    close(fd);
    if (result < 0)
        unlinkat(dir_fd, PENDING_FILE, 0);
    errno = saved_errno;
    return result;
}

static bool matches_swap_path(const char *line, const char *path)
{
    size_t length = strlen(path);
    return strncmp(line, path, length) == 0 && (line[length] == ' ' || line[length] == '\t');
}

static int find_active_swap(bool *found, int *priority)
{
    FILE *swaps = fopen("/proc/swaps", "re");
    if (swaps == NULL)
        return fail("open /proc/swaps");

    char line[1024];
    int result = 0;
    *found = false;
    while (fgets(line, sizeof(line), swaps) != NULL) {
        if (matches_swap_path(line, PENDING_PATH)) {
            result = reject("unpublished swapfile is active", EBUSY);
            break;
        }
        if (matches_swap_path(line, SWAP_PATH)) {
            *found = true;
            if (priority != NULL &&
                sscanf(line + strlen(SWAP_PATH), "%*s %*s %*s %d", priority) != 1) {
                result = reject("read active swap priority", EIO);
                break;
            }
        }
    }
    if (ferror(swaps))
        result = reject("read /proc/swaps", EIO);

    int saved_errno = errno;
    fclose(swaps);
    errno = saved_errno;
    return result;
}

static int run_tool(const char *path, char *const argv[])
{
    pid_t child = fork();
    if (child < 0)
        return fail("start system tool");
    if (child == 0) {
        execv(path, argv);
        fail(path);
        _exit(1);
    }

    int status;
    pid_t finished;
    do {
        finished = waitpid(child, &status, 0);
    } while (finished < 0 && errno == EINTR);
    if (finished < 0)
        return fail("wait for system tool");
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
        return reject(path, EIO);
    return 0;
}

static int activate_swap(int fd, int priority)
{
    unsigned int pin = 1;
    if (ioctl(fd, F2FS_IOC_SET_PIN_FILE, &pin) < 0)
        return fail("pin existing swapfile");

    char *const mkswap[] = {"mkswap", SWAP_PATH, NULL};
    if (run_tool("/system/bin/mkswap", mkswap) < 0)
        return -1;
    if (swapon(SWAP_PATH, SWAP_FLAG_PREFER | priority) < 0)
        return fail("activate swapfile");
    return 0;
}

static int open_swap_directory(void)
{
    int data_fd = open("/data", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (data_fd < 0)
        return fail("open /data");

    struct stat data_info;
    struct statfs data_fs;
    if (fstat(data_fd, &data_info) < 0 || fstatfs(data_fd, &data_fs) < 0)
        return fail("inspect /data");
    if (data_fs.f_type != F2FS_SUPER_MAGIC || !is_direct_userdata(data_info.st_dev))
        return reject("/data is not the Pixel 2 standalone encrypted F2FS volume", EPERM);

    int dir_fd = openat(data_fd, SWAP_DIR, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dir_fd < 0)
        return fail("open private swap directory");
    struct stat dir_info;
    if (fstat(dir_fd, &dir_info) < 0)
        return fail("stat private swap directory");
    if (dir_info.st_dev != data_info.st_dev || dir_info.st_uid != 0 || dir_info.st_gid != 0 ||
        (dir_info.st_mode & 07777) != 0700 || !is_unencrypted(dir_fd))
        return reject("swap directory must be private and outside fscrypt", EPERM);
    if (flock(dir_fd, LOCK_EX | LOCK_NB) < 0)
        return fail("lock private swap directory");
    return dir_fd;
}

static int apply_swap(bool enabled, int requested_priority, bool *active, int *actual_priority)
{
    int dir_fd = open_swap_directory();
    if (dir_fd < 0)
        return -1;

    if (find_active_swap(active, actual_priority) < 0)
        return -1;
    if (*active)
        return 0;
    if (remove_private_file(dir_fd, PENDING_FILE) < 0)
        return -1;
    if (!enabled) {
        if (remove_private_file(dir_fd, SWAP_FILE) < 0)
            return -1;
        return fsync(dir_fd) < 0 ? fail("sync disabled swap state") : 0;
    }

    int fd = openat(dir_fd, SWAP_FILE, O_RDWR | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0 && errno == ENOENT) {
        if (publish_swapfile(dir_fd) < 0)
            return -1;
        fd = openat(dir_fd, SWAP_FILE, O_RDWR | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    }
    if (fd < 0)
        return fail("open swapfile");
    if (validate_swapfile(fd) < 0 || check_free_space(dir_fd, 0) < 0 ||
        activate_swap(fd, requested_priority) < 0)
        return -1;

    if (find_active_swap(active, actual_priority) < 0)
        return -1;
    if (!*active)
        return reject("activated swapfile missing from /proc/swaps", EIO);
    fprintf(stderr, "pixel2-extra-swap: 2 GiB attached at priority %d\n", *actual_priority);
    return 0;
}

/* Android calls this after stopping services and before unmounting userdata. */
static int deactivate_for_shutdown(void)
{
    bool active;
    if (find_active_swap(&active, NULL) < 0)
        return -1;
    if (!active)
        return 0;

    int dir_fd = open_swap_directory();
    if (dir_fd < 0)
        return -1;
    if (find_active_swap(&active, NULL) < 0)
        return -1;
    if (!active)
        return 0;

    int fd = openat(dir_fd, SWAP_FILE, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0)
        return fail("open active swapfile before shutdown");
    struct stat file_info, dir_info;
    if (fstat(fd, &file_info) < 0 || fstat(dir_fd, &dir_info) < 0)
        return fail("inspect active swapfile before shutdown");
    if (!is_private_regular(&file_info) || file_info.st_dev != dir_info.st_dev ||
        file_info.st_size != SWAP_BYTES)
        return reject("active swapfile does not match the private 2 GiB file", EPERM);

    if (swapoff(SWAP_PATH) < 0)
        return fail("release swapfile before shutdown");
    fprintf(stderr, "pixel2-extra-swap: released disk swap before userdata unmount\n");
    return 0;
}

int main(int argc, char *argv[])
{
    if (argc == 2 && strcmp(argv[1], "shutdown") == 0)
        return deactivate_for_shutdown() == 0 ? 0 : 1;

    char *state = "failed";
    int result = -1;
    bool active = false;
    int actual_priority = 0;
    if ((argc == 2 || argc == 3) &&
        (argc == 2 || strcmp(argv[2], "zram_first") == 0 || strcmp(argv[2], "shared") == 0)) {
        int priority = argc == 3 && strcmp(argv[2], "shared") == 0 ?
                SHARED_PRIORITY : ZRAM_FIRST_PRIORITY;
        if (strcmp(argv[1], "true") == 0 || strcmp(argv[1], "1") == 0)
            result = apply_swap(true, priority, &active, &actual_priority);
        else if (strcmp(argv[1], "false") == 0 || strcmp(argv[1], "0") == 0)
            result = apply_swap(false, priority, &active, &actual_priority);
        else
            reject("invalid enable flag", EINVAL);
    } else {
        reject("invalid boot request", EINVAL);
    }

    if (result == 0 && active) {
        char priority[16];
        snprintf(priority, sizeof(priority), "%d", actual_priority);
        char *const set_priority[] = {"setprop", PRIORITY_PROPERTY, priority, NULL};
        if (run_tool("/system/bin/setprop", set_priority) < 0)
            return 1;
    }
    if (result == 0)
        state = active ? "active" : "disabled";
    else if (errno == ENOSPC || errno == EDQUOT)
        state = "insufficient_space";

    char *const setprop[] = {"setprop", STATUS_PROPERTY, state, NULL};
    if (run_tool("/system/bin/setprop", setprop) < 0)
        return 1;
    return result == 0 ? 0 : 1;
}
