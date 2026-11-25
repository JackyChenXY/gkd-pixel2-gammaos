#!/usr/bin/env python3
"""Select the cached Mesa 20.3.4 GLES2 probe in a private Pixel 2 SDK overlay."""

import argparse
import subprocess
from pathlib import Path


def replace_once(text, old, replacement):
    if text.count(old) != 1:
        raise ValueError(f"expected one occurrence of {old.splitlines()[0]!r}")
    return text.replace(old, replacement, 1)


def append_unset(text, key, assignment):
    if assignment in text.splitlines():
        return text
    if any(line.strip().startswith(key) for line in text.splitlines()):
        raise ValueError(f"existing setting for {key}")
    return text.rstrip() + "\n\n" + assignment + "\n"


def patch_egl(text):
    text = replace_once(
        text,
        'property_get("drm.gpu.vendor_name", vendor_buf, NULL)',
        'property_get("vendor.drm.gpu.vendor_name", vendor_buf, NULL)',
    )
    return replace_once(
        text,
        "   dri2_setup_screen(disp);\n",
        """   dri2_setup_screen(disp);

   /* Android 12 SurfaceFlinger requests GLES3 for a configless context. */
   if (!(disp->ClientAPIs & EGL_OPENGL_ES3_BIT_KHR))
      disp->Extensions.KHR_no_config_context = EGL_FALSE;
""",
    )


def patch_graphics_packages(text):
    text = replace_once(
        text,
        "    libEGL_swiftshader \\\n"
        "    libGLESv1_CM_swiftshader \\\n"
        "    libGLESv2_swiftshader",
        "    libGLES_mesa \\\n"
        "    gralloc.minigbm",
    )
    return replace_once(
        text,
        "    ro.hardware.egl=swiftshader",
        "    ro.hardware.egl=mesa \\\n"
        "    ro.hardware.gralloc=minigbm \\\n"
        "    vendor.drm.gpu.vendor_name=panfrost",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path)
    args = parser.parse_args()
    sdk = args.sdk.resolve(strict=True)
    fstype = subprocess.check_output(
        ["findmnt", "-n", "-o", "FSTYPE", "--mountpoint", str(sdk)], text=True
    ).strip()
    if fstype != "overlay":
        parser.error("the SDK must be mounted in a private build overlay")
    mesa = sdk / "external/mesa3d"
    if (mesa / "VERSION").read_text(encoding="utf-8").strip() != "20.3.4":
        parser.error("expected cached Mesa version 20.3.4")
    if subprocess.check_output(
        ["git", "-C", str(mesa), "rev-parse", "HEAD"], text=True
    ).strip() != "4c3106c8246f77e78e80aad0d13095c496f5b4cf":
        parser.error("expected the pinned Rockchip SDK Mesa checkout")

    board = sdk / "device/gamekiddy/gkd_pixel2"
    config = board / "BoardConfig.mk"
    product = board / "gkd_pixel2.mk"
    graphics = sdk / "device/rockchip/common/device.mk"
    features = sdk / "device/rockchip/rk3326/device-common.mk"
    egl = mesa / "src/egl/drivers/dri2/platform_android.c"
    updates = {
        config: append_unset(
            config.read_text(encoding="utf-8"), "BOARD_GPU_DRIVERS",
            "BOARD_GPU_DRIVERS := panfrost kmsro",
        ),
        product: append_unset(
            product.read_text(encoding="utf-8"), "PRODUCT_SOONG_NAMESPACES",
            "PRODUCT_SOONG_NAMESPACES += external/mesa3d",
        ),
        graphics: patch_graphics_packages(graphics.read_text(encoding="utf-8")),
        features: replace_once(
            features.read_text(encoding="utf-8"), "ro.opengles.version=196608",
            "ro.opengles.version=131072",
        ),
        egl: patch_egl(egl.read_text(encoding="utf-8")),
    }
    for path, text in updates.items():
        path.write_text(text, encoding="utf-8")
        print(path.relative_to(sdk))


if __name__ == "__main__":
    main()
