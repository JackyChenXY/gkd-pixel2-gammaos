# Android board display probe

The current GKD Pixel 2 system GPU package provides Mesa 24.3.4 Panfrost EGL and OpenGL ES for SurfaceFlinger and unmodified applications. Build instructions, the board-specific RGB buffer import and hardware validation are in the [system GPU driver directory](pixel2-system-gpu/README.md). The earlier SwiftShader board bring-up is described below.

This profile targets the pinned Rockchip Android 12 SDK after preparing the
GKD Pixel 2 product. It keeps the 32-bit Android ABI and the original Android
first-stage mount layout. It selects AOSP software Keymaster and Gatekeeper,
minigbm with linear Rockchip DRM buffers, DRM Hardware Composer, and
SwiftShader EGL. The graphics profile disables Widevine and the vendor Mali package.

Run the module build from a Linux or WSL environment with overlayfs support.
The working and upper directories use a Linux filesystem. The SDK's existing
source and build outputs form the lower layer. Compilation runs as the SDK's
non-root owner, and all changes go to a temporary mount namespace and the new
scratch directory.

    sudo bash port/open-variant/vendor/build-modules.sh /path/to/sdk /path/to/scratch-parent

Add the flag --images to continue from the module build into partition export
within the same mount. To resume a successful module build separately, pass
its printed scratch directory and --resume-images:

    sudo bash port/open-variant/vendor/build-modules.sh /path/to/sdk /path/to/module-scratch --resume-images

The export stage omits the vendor media codecs, onboard Wi-Fi and Bluetooth,
RkVideoPlayer, and the prebuilt zmodem tools. It also discards the unused
legacy motion-sensor HAL with its static calibration library, the inactive
microphone noise reduction prebuilt, and Rockchip factory recovery extras.
IncrementalFS is provided by the Android 5.10 kernel. Regular audio HALs
remain in the build.

The export directory contains the five raw ext4 partitions, the first-stage
gzip Android ramdisk, and checksums. It also includes the SDK boot/recovery
images with their SDK kernel and the engineering board DTBO for reference.
For the open boot path, use the matching rebuilt kernel and device tree
instead of the SDK boot material. The board image uses software-rendered
OpenGL ES 3.0. Treat it as a desktop diagnostic until cold boot, userdata
mounting, and graphics are verified on the real panel.

The engineering probe boots with permissive SELinux. Before testing enforcing
mode, label the minigbm allocator executable `hal_graphics_allocator_default_exec`
and the minigbm mapper library and its `libminigbm_gralloc.so` dependency
as `same_process_hal_file`. In headless QEMU the allocator ran but returned
`-EINVAL` when it could not open a supported DRM device, triggering the
service's normal SurfaceFlinger restart action.

The initial board build used these SDK revisions:

| Component | Git revision |
| --- | --- |
| external/drm_hwcomposer | `1d35f0d02a039ecbf1266b13d9ef76483e2cedc2` |
| external/minigbm | `ad7fcdb22ffb98dc08dbea1ac2b286a16ca45031` |
| external/libdrm | `56b0b2765344f0d229b459621e51a08a2a5c8864` |
| external/swiftshader | `e5cb061cd93aae4b6c6417bf8e11db760a7ce33c` |
| system/keymaster | `72feb64c50e24121a5d1765d0a7718ec744380c9` |
| system/gatekeeper | `6d141a300cd130398acedb15e6259864227bcc15` |
