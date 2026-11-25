# Pixel 2 graphics profiles and Windows setup

For the current desktop packaging see the [AT4K OEM image guide](../desktop/at4k/README.md). The public card boots Mesa/Panfrost. The Windows assistant verifies the gzip download and the base image, fills the alternate vendor partition with the 11 pinned components on the user's computer, and marks it ready for use. First boot stays on Mesa. U-Boot consumes a Mali trial before starting the alternate kernel. Keeping a trial schedules later Mali boots, and `MESA.TXT` on the boot partition forces Mesa.

## Build the firmware

Build the baseline system and card with the [public image tools](../public-image/). The matching BSP kernel source, Panfrost and kbase configurations, public board files, Android component sources and notices are provided with the [firmware release](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/tag/v0.3.0). `make-template.py` creates the empty public slot from a locally available matching SDK vendor and the Mesa vendor. Its profile pins the 11 file hashes. For a new baseline rebuild the template, record its actual hashes, and validate the partition geometry and filesystem before packaging.

```sh
bash build-tools.sh "$GAMMA" "$GOROOT" "$WORK/tools"
sudo unshare -m --propagation private python3 update-system.py \
  --baseline "$BASE_SYSTEM" --gamma "$GAMMA" --tools "$WORK/tools" --output "$WORK/system.img"
python3 assemble.py --base "$BASE_CARD" --system "$WORK/system.img" \
  --empty "$EMPTY_SLOT" --kernel "$KBASE_IMAGE" --output "$WORK/public.img"
gzip -n -3 -c "$WORK/public.img" > "$WORK/GKD-Pixel2-GammaOS.img.gz"
```

The assembler checks a specific base card and kernel. The pinned release uses the public factory card SHA-256 `08e3fbfb7189fe8b8a139a6f9dbf85fee0a2e81743694254e8bac0fe25f52f55`. Build products with different filesystem metadata require requalification. The released blank template can be read from offset 328204288, length 134217728, in the decompressed public image. Compare its SHA-256 to `backend/profile/profile.json` before using it.

## Build the Windows assistant

Use Go 1.23 or newer. This release used Go 1.27.4. The public support ZIP contains eight ARM32 redistributable components and their notices. The Mali EGL library is obtained at runtime from the pinned upstream.

```sh
python3 build-installer.py --support "$WORK/Pixel2-Mali-Support.zip" \
  --go "$GOROOT/bin/go" --output "$WORK/Pixel2-Setup.exe"
(cd backend && go test ./...)
python3 tests/boot-policy.py
```

`backend/card/release.json` records the released compressed, uncompressed and locally integrated image digests. Use `Pixel2-Setup.exe --prepare-only` for image-only production, optionally with `--out-dir`, `--base` and `--pack`. With no switches the assistant opens Raspberry Pi Imager's graphical device selector. The helper only writes regular files. The physical write and readback are performed by Imager after the user chooses a card and confirms.

The guest fixture exercises the shipping Android service at system UID. From a disposable preloaded image, run `tests/virtual-card.py` and then `tests/run-boots.py` with the steps `preloaded unconfirmed fallback confirm persistent return`. GPU rendering and display output need physical hardware.
