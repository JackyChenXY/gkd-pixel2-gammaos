#!/usr/bin/env python3
"""Apply the Pixel 2 software-rendered board profile to an isolated SDK."""

import argparse
from pathlib import Path


NO_RADIO_FEATURES = Path("device/gamekiddy/gkd_pixel2/pixel2_no_radio.xml")


def replace_once(text, old, replacement):
    if text.count(old) != 1:
        raise ValueError(f"expected one occurrence of {old.splitlines()[0]!r}")
    return text.replace(old, replacement, 1)


def replace_section(text, first, end, replacement):
    start = text.index(first)
    stop = text.index(end, start)
    return text[:start] + replacement + text[stop:]


def device_profile(text):
    text = replace_section(text, "# define MPP_BUF_TYPE_DRM", "# iep", """# GKD Pixel 2 diagnostic graphics profile.
PRODUCT_PACKAGES += \\
    android.hardware.graphics.allocator@4.0-service.minigbm \\
    android.hardware.graphics.mapper@4.0-impl.minigbm \\
    android.hardware.graphics.composer@2.4-service \\
    hwcomposer.drm_minigbm \\
    libEGL_swiftshader \\
    libGLESv1_CM_swiftshader \\
    libGLESv2_swiftshader

PRODUCT_VENDOR_PROPERTIES += \\
    ro.hardware.hwcomposer=drm_minigbm \\
    ro.hardware.egl=swiftshader

""")
    return text


def platform_profile(text):
    text = replace_once(text, "TARGET_BOARD_PLATFORM_GPU := mali-tDVx", "TARGET_BOARD_PLATFORM_GPU := software")
    return replace_once(text, "BOARD_WIDEVINE_OEMCRYPTO_LEVEL := 3", "BOARD_WIDEVINE_OEMCRYPTO_LEVEL :=")


def board_profile(text):
    return replace_once(
        text,
        "PRODUCT_BOOT_DEVICE := ff370000.dwmmc",
        "PRODUCT_BOOT_DEVICE := ff370000.dwmmc\n\n"
        "# Use the software Keymaster and Gatekeeper from the pinned SDK.\n"
        "PRODUCT_HAVE_OPTEE := false",
    )


def rk_device_profile(text):
    text = replace_section(
        text,
        "PRODUCT_COPY_FILES += \\\n"
        "    frameworks/native/data/etc/android.hardware.opengles.aep.xml:",
        "$(call inherit-product-if-exists, vendor/rockchip/rk3326/device-vendor.mk)",
        "",
    )
    return replace_once(
        text,
        "PRODUCT_PACKAGES += \\\n    displayd \\\n    libion",
        "PRODUCT_PACKAGES += libion",
    )


def manifest_profile(text):
    name = "<name>android.hardware.graphics.composer</name>"
    start = text.index(name)
    stop = text.index("</hal>", start)
    return text[:start] + replace_once(
        text[start:stop], "<version>2.1</version>", "<version>2.4</version>"
    ) + text[stop:]


def minigbm_profile(text):
    anchor = 'name: "libminigbm_gralloc",\n    defaults: ["minigbm_cros_gralloc_library_defaults"],'
    return replace_once(text, anchor, anchor + '\n    cflags: ["-DDRV_ROCKCHIP"],\n    include_dirs: ["external/libdrm/rockchip"],')


def linear_minigbm_profile(text):
    # This Rockchip kernel exposes linear scanout. Its DRM API does not
    # advertise the ChromeOS-specific AFBC modifier expected by minigbm.
    text = replace_section(text, "static int afbc_bo_from_format(", "static int rockchip_init(", "")
    text = replace_section(
        text,
        "} else if (width <= 2560 &&\n",
        "} else {\n",
        "",
    )
    guard = (
        '\tif (!drv_has_modifier(modifiers, count, DRM_FORMAT_MOD_LINEAR)) {\n'
        '\t\terrno = EINVAL;\n'
        '\t\tdrv_log("no usable modifier found\\n");\n'
        '\t\treturn -errno;\n'
        '\t}\n\n'
    )
    text = replace_once(text, "".join("\t" + line if line.strip() else line for line in guard.splitlines(keepends=True)), "")
    text = replace_once(text, "\tif (format == DRM_FORMAT_NV12) {\n", guard + "\tif (format == DRM_FORMAT_NV12) {\n")
    return replace_once(
        text,
        "\t/* We can only map buffers created with SW access flags, which should\n"
        "\t * have no modifiers (ie, not AFBC). */\n"
        "\tif (bo->meta.format_modifier == DRM_FORMAT_MOD_CHROMEOS_ROCKCHIP_AFBC)",
        "\t/* Only linear buffers are CPU-mappable in this profile. */\n"
        "\tif (bo->meta.format_modifier != DRM_FORMAT_MOD_LINEAR)",
    )


def swiftshader_profile(text):
    # ARM and AArch64 use their native instructions. Keep SSE2 on x86.
    text = replace_once(text, '        "-msse2",\n', "")
    anchor = '    cpp_std: "c++17",\n'
    return replace_once(text, anchor, anchor + '''
    arch: {
        x86: {
            cflags: ["-msse2"],
        },
        x86_64: {
            cflags: ["-msse2"],
        },
    },
''')



def prune_board_profile(text):
    anchor = "PRODUCT_HAVE_OPTEE := false"
    text = replace_once(text, anchor, anchor + """
# This desktop probe has no hardware media or onboard radio payload.
PRODUCT_HAVE_RKVPU := false
PRODUCT_HAVE_RKWIFI := false
BOARD_HAVE_BLUETOOTH := false
BOARD_BLUETOOTH_SUPPORT := false
BOARD_BLUETOOTH_LE_SUPPORT := false
BOARD_WIFI_SUPPORT := false""")
    return disable_recovery_pcba(text)


def prune_radio_packages(text):
    text = replace_section(
        text,
        "PRODUCT_COPY_FILES += \\\n"
        "    $(LOCAL_PATH)/wpa_config.txt:",
        "ifeq ($(PRODUCT_HAVE_DLNA),true)",
        "",
    )
    text = replace_section(
        text,
        "ifeq ($(filter MediaTek_mt7601 MediaTek RealTek Espressif, "
        "$(strip $(BOARD_CONNECTIVITY_VENDOR))), )\n",
        "ifeq ($(strip $(BOARD_SUPPORT_MULTIAUDIO)), true)\n",
        "",
    )
    return replace_once(
        text,
        "#bt config for ap bt\nPRODUCT_COPY_FILES += \\\n"
        "    $(TARGET_DEVICE_DIR)/bt_vendor.conf:/vendor/etc/bluetooth/bt_vendor.conf\n\n",
        "",
    )


def prune_product_radio_features(text):
    return text.rstrip() + (
        "\n\n# Disable unsupported features inherited from the system image.\n"
        f"PRODUCT_COPY_FILES += {NO_RADIO_FEATURES}:"
        "$(TARGET_COPY_OUT_VENDOR)/etc/permissions/pixel2_no_radio.xml\n"
    )


def prune_wifi_display(text):
    # Android's Wi-Fi display adapter requires Wi-Fi Direct, which the
    # radio-free probe deliberately leaves out.
    return replace_once(
        text,
        '<bool name="config_enableWifiDisplay">true</bool>',
        '<bool name="config_enableWifiDisplay">false</bool>',
    )


def prune_radio_config(text):
    text = replace_once(text, "BOARD_CONNECTIVITY_VENDOR := Rockchip", "BOARD_CONNECTIVITY_VENDOR := none")
    text = replace_once(text, "BOARD_CONNECTIVITY_MODULE := ap6xxx", "BOARD_CONNECTIVITY_MODULE := none")
    return replace_once(
        text,
        "BOARD_HAVE_BLUETOOTH_RTK := true\n\n",
        "BOARD_HAVE_BLUETOOTH_RTK := false\n\n",
    )


def swiftshader_features(text):
    text = replace_once(text, "ro.opengles.version=196610", "ro.opengles.version=196608")
    return replace_once(text, "persist.vendor.rk_vulkan=true", "persist.vendor.rk_vulkan=false")



def prune_factory_recovery(text):
    return replace_once(
        text,
        '    $(LOCAL_PATH)/init.recovery.rk30board.rc:recovery/root/init.recovery.rk30board.rc \\\n'
        '    vendor/rockchip/common/bin/$(TARGET_ARCH)/busybox:recovery/root/sbin/busybox \\\n',
        '    $(LOCAL_PATH)/init.recovery.rk30board.rc:recovery/root/init.recovery.rk30board.rc\n',
    )


def use_builtin_incremental_fs(text):
    return replace_once(
        text,
        "# incrementalfs config\n"
        "$(call inherit-product-if-exists, vendor/rockchip/common/modular_kernel/4.19/incrementalfs.mk)",
        "# IncrementalFS is built into the Pixel 2 Android 5.10 kernel.\n"
        "PRODUCT_PROPERTY_OVERRIDES += ro.incremental.enable=yes\n"
        "PRODUCT_COPY_FILES += \\\n"
        "    vendor/rockchip/common/gms/features/android.software.incremental_delivery.xml:"
        "$(TARGET_COPY_OUT_VENDOR)/etc/permissions/android.software.incremental_delivery.xml",
    )


def disable_recovery_pcba(text):
    return replace_once(
        text,
        "BOARD_WIFI_SUPPORT := false",
        "BOARD_WIFI_SUPPORT := false\nTARGET_ROCKCHIP_PCBATEST := false",
    )


def prune_rk_extras(text):
    return prune_factory_recovery(swiftshader_features(text))



def prune_sensor_and_anr(text):
    text = replace_section(
        text,
        "ifeq ($(filter atv box car, $(strip $(TARGET_BOARD_PLATFORM_PRODUCT))), )\n# Sensor HAL",
        "# Include thermal HAL module",
        "",
    )
    return replace_once(
        text,
        "    audio.usb.default\\\n    libanr\n",
        "    audio.usb.default\n",
    )


def prune_device_profile(text):
    text = prune_sensor_and_anr(text)
    text = use_builtin_incremental_fs(prune_radio_packages(text))
    text = replace_once(
        text,
        "# Media OMX/C2\n$(call inherit-product, device/rockchip/common/modules/mediacodec.mk)\n",
        "",
    )
    text = replace_section(text, "# iep\n", "# charge\n", "BUILD_IEP := false\n\n")
    text = replace_section(
        text,
        "# Bluetooth HAL\n",
        "ifeq ($(strip $(TARGET_BOARD_PLATFORM_PRODUCT)), box)\n",
        "",
    )
    return replace_once(
        text,
        "PRODUCT_COPY_FILES += \\\n"
        "    device/rockchip/common/zmodem/rz:$(TARGET_COPY_OUT_VENDOR)/bin/rz \\\n"
        "    device/rockchip/common/zmodem/sz:$(TARGET_COPY_OUT_VENDOR)/bin/sz\n",
        "",
    )


def remove_manifest_hal(text, name):
    name = f"<name>{name}</name>"
    index = text.index(name)
    start = text.rindex('    <hal format="hidl">\n', 0, index)
    stop = text.index("    </hal>\n", index) + len("    </hal>\n")
    return text[:start] + text[stop:]


def prune_manifest_profile(text):
    text = remove_manifest_hal(text, "android.hardware.bluetooth")
    return remove_manifest_hal(text, "android.hardware.sensors")



def prune_apps(text):
    return replace_once(text, "    RkVideoPlayer \\\n", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path, help="disposable SDK tree or private overlay")
    parser.add_argument("--apply", action="store_true", help="write changes to the disposable SDK")
    parser.add_argument("--prune", action="store_true", help="prune optional payloads after applying the graphics profile")
    args = parser.parse_args()
    changes = {
        "device/gamekiddy/gkd_pixel2/BoardConfig.mk": board_profile,
        "device/rockchip/rk3326/BoardConfig.mk": platform_profile,
        "device/rockchip/rk3326/device-common.mk": rk_device_profile,
        "device/rockchip/common/device.mk": device_profile,
        "device/rockchip/common/manifests/manifest_level_31.xml": manifest_profile,
        "external/minigbm/Android.bp": minigbm_profile,
        "external/minigbm/rockchip.c": linear_minigbm_profile,
        "external/swiftshader/Android.bp": swiftshader_profile,
    }
    if args.prune:
        changes = {
            "device/gamekiddy/gkd_pixel2/BoardConfig.mk": prune_board_profile,
            "device/gamekiddy/gkd_pixel2/gkd_pixel2.mk": prune_product_radio_features,
            "device/rockchip/common/device.mk": prune_device_profile,
            "device/rockchip/common/manifests/manifest_level_31.xml": prune_manifest_profile,
            "device/rockchip/common/modules/rockchip_apps.mk": prune_apps,
            "device/rockchip/common/overlay/frameworks/base/core/res/res/values/config.xml": prune_wifi_display,
            "device/rockchip/common/wifi_bt_common.mk": prune_radio_config,
            "device/rockchip/rk3326/device-common.mk": prune_rk_extras,
        }
    planned = {}
    for relative, transform in changes.items():
        source = args.sdk / relative
        try:
            planned[source] = transform(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            parser.exit(1, f"{relative}: {error}\n")
    if args.prune:
        planned[args.sdk / NO_RADIO_FEATURES] = (
            Path(__file__).with_name(NO_RADIO_FEATURES.name).read_text(encoding="utf-8")
        )
    for source, content in planned.items():
        if args.apply:
            source.write_text(content, encoding="utf-8")
        print(source.relative_to(args.sdk))


if __name__ == "__main__":
    main()
