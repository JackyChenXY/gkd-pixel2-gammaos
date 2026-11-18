/* Route the built-in Pixel 2 controller to Android's gamepad and mouse inputs. */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

enum {
    SELECT_HOLD_MS = 700,
    POINTER_HOLD_MS = 650,
    POINTER_SHOW_DELAY_MS = 250,
    POINTER_STEP_MS = 16,
    POINTER_STEP = 6,
};

static const char joypad_name[] = "gkd_pixel2_joypad";
static const unsigned joypad_keys[] = {
    BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT,
    BTN_EAST, BTN_SOUTH, BTN_NORTH, BTN_WEST,
    BTN_TL, BTN_TR, BTN_TL2, BTN_TR2, BTN_SELECT, BTN_START, BTN_TRIGGER_HAPPY1,
};

struct pointer_state {
    int dev_dir;
    int pad;
    int mouse;
    bool held[KEY_MAX + 1];
    bool forwarded[KEY_MAX + 1];
    bool left_down;
    bool select_down;
    bool select_toggled;
    int64_t select_deadline;
    int64_t hold_until;
    int64_t next_move;
    int64_t show_at;
};

static int64_t monotonic_ms(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static bool emit(int fd, const struct input_event *events, size_t size)
{
    ssize_t sent;
    do {
        sent = write(fd, events, size);
    } while (sent < 0 && errno == EINTR);
    return sent == (ssize_t)size;
}

static bool emit_key(int fd, unsigned code, int value)
{
    const struct input_event events[] = {
        {.type = EV_KEY, .code = code, .value = value},
        {.type = EV_SYN, .code = SYN_REPORT},
    };
    return emit(fd, events, sizeof(events));
}

static bool move_pointer(int mouse, int x, int y)
{
    const struct input_event events[] = {
        {.type = EV_REL, .code = REL_X, .value = x},
        {.type = EV_REL, .code = REL_Y, .value = y},
        {.type = EV_SYN, .code = SYN_REPORT},
    };
    return emit(mouse, events, sizeof(events));
}

static int create_virtual_input(int dev_dir, bool mouse);

static bool toggle_pointer(struct pointer_state *state, int64_t now)
{
    for (size_t i = 0; i < sizeof(joypad_keys) / sizeof(*joypad_keys); ++i) {
        unsigned key = joypad_keys[i];
        if (state->forwarded[key] && !emit_key(state->pad, key, 0)) return false;
    }
    memset(state->forwarded, 0, sizeof(state->forwarded));
    memset(state->held, 0, sizeof(state->held));
    state->hold_until = 0;
    state->next_move = 0;
    if (state->mouse >= 0) {
        if (state->left_down && !emit_key(state->mouse, BTN_LEFT, 0)) return false;
        close(state->mouse);
        state->mouse = -1;
        state->left_down = false;
        state->show_at = 0;
    } else {
        state->mouse = create_virtual_input(state->dev_dir, true);
        // Give InputReader time to open the hot-plugged mouse before showing its cursor.
        if (state->mouse >= 0) state->show_at = now + POINTER_SHOW_DELAY_MS;
    }
    return true;
}

static bool update_pointer(struct pointer_state *state, int64_t now)
{
    if (state->select_down && !state->select_toggled && now >= state->select_deadline) {
        state->select_toggled = true;
        if (!toggle_pointer(state, now)) return false;
    }
    if (state->mouse < 0) return true;
    if (state->show_at && now >= state->show_at) {
        if (!move_pointer(state->mouse, 1, 0)) return false;
        state->show_at = 0;
    }

    // The stock GPIO map reports the physical A as BTN_EAST and B as BTN_SOUTH.
    bool left_down = state->held[BTN_EAST] || state->held[BTN_SOUTH] || now < state->hold_until;
    if (left_down != state->left_down) {
        if (!emit_key(state->mouse, BTN_LEFT, left_down)) return false;
        state->left_down = left_down;
    }
    if (now >= state->next_move) {
        int x = state->held[BTN_DPAD_RIGHT] - state->held[BTN_DPAD_LEFT];
        int y = state->held[BTN_DPAD_DOWN] - state->held[BTN_DPAD_UP];
        if ((x || y) && !move_pointer(state->mouse, x * POINTER_STEP, y * POINTER_STEP)) return false;
        state->next_move = now + POINTER_STEP_MS;
    }
    return true;
}

static bool handle_key(struct pointer_state *state, unsigned key, int value, int64_t now)
{
    if (key == BTN_SELECT) {
        if (value == 1) {
            state->select_down = true;
            state->select_toggled = false;
            state->select_deadline = now + SELECT_HOLD_MS;
        } else if (value == 0) {
            bool tap = state->select_down && !state->select_toggled && state->mouse < 0;
            state->select_down = false;
            if (tap) return emit_key(state->pad, key, 1) && emit_key(state->pad, key, 0);
        }
        return true;
    }

    if (state->mouse < 0 || key == BTN_TRIGGER_HAPPY1) {
        // Ignore releases for buttons already released when switching modes.
        if (value != 1 && !state->forwarded[key]) return true;
        state->forwarded[key] = value != 0;
        return emit_key(state->pad, key, value);
    }

    if (value == 2) return true;
    state->held[key] = value != 0;
    if (key == BTN_SOUTH && value == 1) state->hold_until = now + POINTER_HOLD_MS;
    return update_pointer(state, now);
}

static int next_timeout(const struct pointer_state *state, int64_t now)
{
    int64_t wake_at = 0;
    if (state->select_down && !state->select_toggled) wake_at = state->select_deadline;
    if (state->show_at && (!wake_at || state->show_at < wake_at)) wake_at = state->show_at;
    if (state->mouse >= 0 && (state->held[BTN_DPAD_RIGHT] != state->held[BTN_DPAD_LEFT] ||
                              state->held[BTN_DPAD_DOWN] != state->held[BTN_DPAD_UP]) &&
        (!wake_at || state->next_move < wake_at))
        wake_at = state->next_move;
    if (state->mouse >= 0 && !state->held[BTN_EAST] && !state->held[BTN_SOUTH] && state->hold_until > now &&
        (!wake_at || state->hold_until < wake_at))
        wake_at = state->hold_until;
    return wake_at ? (int)(wake_at - now) : -1;
}

static void route_buttons(int physical, struct pointer_state *state)
{
    struct pollfd source = {.fd = physical, .events = POLLIN};
    for (;;) {
        int64_t now = monotonic_ms();
        if (!update_pointer(state, now)) return;
        int ready = poll(&source, 1, next_timeout(state, now));
        if (ready < 0 && errno == EINTR) continue;
        if (ready < 0 || (source.revents & (POLLERR | POLLHUP | POLLNVAL))) return;
        if (!ready) continue;

        struct input_event event;
        ssize_t length = read(physical, &event, sizeof(event));
        if (length < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (length != sizeof(event) || (event.type == EV_SYN && event.code == SYN_DROPPED)) return;
        now = monotonic_ms();
        if (!update_pointer(state, now)) return;
        if (event.type == EV_KEY && event.code <= KEY_MAX && event.value >= 0 && event.value <= 2 &&
            !handle_key(state, event.code, event.value, now))
            return;
    }
}

static int open_builtin_joypad(void)
{
    for (unsigned i = 0; i < 32; ++i) {
        char path[32];
        snprintf(path, sizeof(path), "/dev/input/event%u", i);
        int fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd < 0) continue;
        char name[64] = {0};
        unsigned char keys[KEY_MAX / 8 + 1] = {0};
        if (ioctl(fd, EVIOCGNAME(sizeof(name) - 1), name) >= 0 && strcmp(name, joypad_name) == 0 &&
            ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keys)), keys) > 0) {
            size_t i;
            for (i = 0; i < sizeof(joypad_keys) / sizeof(*joypad_keys); ++i) {
                unsigned key = joypad_keys[i];
                if (!(keys[key / 8] & (1u << (key % 8)))) break;
            }
            if (i == sizeof(joypad_keys) / sizeof(*joypad_keys)) return fd;
        }
        close(fd);
    }
    errno = ENODEV;
    return -1;
}

static int create_virtual_input(int dev_dir, bool mouse)
{
    int fd = openat(dev_dir, "uinput", O_WRONLY | O_CLOEXEC);
    if (fd < 0) return -1;

    if (ioctl(fd, UI_SET_EVBIT, EV_KEY) != 0) goto fail;
    if (mouse) {
        if (ioctl(fd, UI_SET_EVBIT, EV_REL) != 0 ||
            ioctl(fd, UI_SET_RELBIT, REL_X) != 0 ||
            ioctl(fd, UI_SET_RELBIT, REL_Y) != 0 ||
            ioctl(fd, UI_SET_KEYBIT, BTN_LEFT) != 0)
            goto fail;
    } else {
        for (size_t i = 0; i < sizeof(joypad_keys) / sizeof(*joypad_keys); ++i) {
            if (ioctl(fd, UI_SET_KEYBIT, joypad_keys[i]) != 0) goto fail;
        }
    }

    struct uinput_user_dev device = {
        .id = {.bustype = BUS_VIRTUAL, .vendor = 1, .product = mouse ? 0x2103 : 0x2102, .version = 0x100},
    };
    snprintf(device.name, sizeof(device.name), "%s", mouse ? "Pixel 2 pointer" : joypad_name);
    if (write(fd, &device, sizeof(device)) == sizeof(device) && ioctl(fd, UI_DEV_CREATE) == 0) return fd;

fail:
    {
        int saved = errno;
        close(fd);
        errno = saved;
    }
    return -1;
}

int start_pixel2_pointer(int report, int console)
{
    int physical = open_builtin_joypad();
    if (physical < 0) return -1;

    // Keep the device directory accessible when Android moves /dev to its system root.
    int dev_dir = open("/dev", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    struct pointer_state state = {.dev_dir = dev_dir, .pad = -1, .mouse = -1};
    pid_t child = -1;
    if (dev_dir >= 0) state.pad = create_virtual_input(dev_dir, false);
    if (state.pad >= 0 && ioctl(physical, EVIOCGRAB, 1) == 0) child = fork();
    if (child == 0) {
        close(report);
        if (console >= 0) close(console);
        route_buttons(physical, &state);
        _exit(0);
    }

    int saved = errno;
    // The child owns the grab and virtual devices. Closing them restores the physical pad.
    if (state.pad >= 0) close(state.pad);
    if (dev_dir >= 0) close(dev_dir);
    close(physical);
    errno = saved;
    return child > 0 ? 0 : -1;
}
