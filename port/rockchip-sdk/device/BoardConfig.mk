# Start from Rockchip's Android 12 RK3326 Go configuration.
include device/rockchip/rk3326/BoardConfig.mk

# Pixel 2 boots Android from the ff370000 DW MMC controller.  The RK3326
# reference board's default points at a different controller and must not be
# inherited for the first-stage fstab lookup.
PRODUCT_BOOT_DEVICE := ff370000.dwmmc

BUILD_WITH_GO_OPT := true

TARGET_ARCH := arm
TARGET_ARCH_VARIANT := armv8-a
TARGET_CPU_ABI := armeabi-v7a
TARGET_CPU_ABI2 := armeabi
TARGET_CPU_VARIANT := cortex-a53
TARGET_CPU_SMP := true

BOARD_USES_AB_IMAGE := false
BOARD_ROCKCHIP_VIRTUAL_AB_ENABLE := false

# Pixel 2-specific Android kernel device tree.
PRODUCT_KERNEL_DTS := rk3326-gkd-pixel2
PRODUCT_KERNEL_CONFIG += gkd_pixel2.config

# The panel is mounted sideways in the chassis; 270 degrees is the tested
# orientation in the community hardware port.
SF_PRIMARY_DISPLAY_ORIENTATION := 270

# This handheld has no camera modules.
BOARD_CAMERA_SUPPORT := false
BOARD_CAMERA_SUPPORT_EXT := false
