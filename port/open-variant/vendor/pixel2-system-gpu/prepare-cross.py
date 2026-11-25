#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Reuse the Pixel 2 Android platform's ARM32 headers and linked vendor ABI."""
import argparse
import ast
import configparser
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", type=Path)
    parser.add_argument("aosp_cross", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("--upper", type=Path, action="append", default=[])
    args = parser.parse_args()
    sdk, cross, work = (p.resolve() for p in (args.sdk, args.aosp_cross, args.work))
    config = configparser.ConfigParser(interpolation=None)
    config.read(cross)
    if ast.literal_eval(config["host_machine"]["cpu_family"]) != "arm":
        parser.error("An ARM32 vendor cross file is required")

    # The Android build can be split between the SDK and earlier build overlays.
    def locate(option):
        prefix = next((p for p in ("-isystem", "-I", "-B") if option.startswith(p)), "")
        value = option[len(prefix):]
        if value.startswith("prebuilts/"):
            value = str(sdk / value)
        path = Path(value)
        if path.is_relative_to(sdk) and not path.exists():
            relative = path.relative_to(sdk)
            for upper in args.upper:
                candidate = upper.resolve() / relative
                if candidate.exists():
                    return prefix + str(candidate)
            if prefix:  # Generated includes for the Android makefile's dummy module.
                return None
            if path.suffix in (".a", ".so", ".o"):
                raise FileNotFoundError(path)
        return prefix + value

    pkg = work / "pkgconfig"
    pkg.mkdir(exist_ok=True)
    for pc in cross.parent.glob("*.pc"):
        if pc.name != "libdrm.pc":
            shutil.copyfile(pc, pkg / pc.name)
    (pkg / "log.pc").write_text("Name: log\nDescription: Android liblog from vendor link inputs\nVersion: 1\n")
    if not config.has_section("built-in options"):
        config.add_section("built-in options")
    for key in ("c_args", "cpp_args", "c_link_args", "cpp_link_args"):
        flags = []
        source = config["built-in options"] if key in config["built-in options"] else config["properties"]
        for raw in ast.literal_eval(source.pop(key)):
            if not raw or raw == "-Wl,-e,main" or "/external/libdrm" in raw or raw.endswith("/libdrm.vendor.so"):
                continue
            flag = locate(raw)
            if flag:
                flags.append(flag)
        if key.endswith("link_args"):
            # Panfrost keys its persistent shader cache by the 20-byte ELF build ID.
            flags.append("-Wl,--build-id=sha1")
            flags.append("-Wl,--exclude-libs,libdrm.a")
        config["built-in options"][key] = repr(flags)
    for key in ("c", "cpp"):
        config["binaries"][key] = repr([v for v in ast.literal_eval(config["binaries"][key]) if v])
    compiler = Path(ast.literal_eval(config["binaries"]["c"])[0])
    config["binaries"]["strip"] = repr(str(compiler.with_name("llvm-strip")))
    pkgtool = shutil.which("pkg-config")
    if not pkgtool:
        raise RuntimeError("pkg-config is required on PATH")
    config["binaries"].pop("pkgconfig", None)
    config["binaries"]["pkg-config"] = repr(["env", "PKG_CONFIG_PATH=",
        f"PKG_CONFIG_LIBDIR={work}/drm-install/lib/pkgconfig:{pkg}", pkgtool])
    config["host_machine"]["system"] = "'android'"
    with (work / "android-arm.ini").open("w") as out:
        config.write(out)


if __name__ == "__main__":
    main()
