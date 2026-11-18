#!/usr/bin/env python3
"""Render the Rockchip SDK DTS using panel commands from a local stock DTB."""
import argparse
from pathlib import Path
import re
import subprocess

PANEL = "/dsi@ff450000/panel@0"


def get_property(dtb, kind, node, name):
    return subprocess.check_output(
        ["fdtget", "-t", kind, str(dtb), node, name], text=True,
    ).split()


def render(dtb):
    compatible = get_property(dtb, "s", "/", "compatible")
    if "gamekiddy,gkd-pixel2" not in [name.lower() for name in compatible]:
        raise ValueError("expected a stock GameKiddy GKD Pixel 2 DTB")
    if get_property(dtb, "s", PANEL, "compatible") != ["sitronix,st7703", "simple-panel-dsi"]:
        raise ValueError("unsupported panel in stock DTB")

    template = Path(__file__).with_name("rk3326-gkd-pixel2.dts.in").read_text()
    marker = "@PANEL_INIT_SEQUENCE@"
    if template.count(marker) != 1:
        raise ValueError(f"invalid DTS template marker {marker}")
    sequence = get_property(dtb, "bx", PANEL, "panel-init-sequence")
    if not sequence or any(re.fullmatch(r"[0-9a-fA-F]{1,2}", byte) is None for byte in sequence):
        raise ValueError("invalid panel-init-sequence")
    sequence = [byte.zfill(2).lower() for byte in sequence]
    rows = ("\t\t\t" + " ".join(sequence[i:i + 16]) for i in range(0, len(sequence), 16))
    return template.replace(marker, "\n".join(rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dtb", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = render(args.stock_dtb)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(result)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")


if __name__ == "__main__":
    main()
