# 构建和离线打包

参考环境为 x86-64 Ubuntu 22.04（WSL 2），Android 构建用 JDK 11。需要 Git LFS、Python 3、GNU 构建工具、`e2fsprogs`、`u-boot-tools`、`device-tree-compiler`，以及 Rockchip SDK 的 AArch64 工具链和 `lpmake`、`lpdump`、`lpunpack`。请把大体积源码和构建输出放到有充足空间的 Linux 文件系统中。下面的命令分阶段生成文件，完整流程尚未在全新的机器上做端到端复现。

## 1. GammaOS 系统分区

从仓库根目录开始，取 [GammaOSDistribution 固定版本](https://github.com/TheGammaSqueeze/GammaOSDistribution/tree/b2db9cfe308c8753e3385b8ab64bcb34c3177177)，并准备 [Rockchip Android 12 SDK 固定清单](https://github.com/TinkerBoard-Android/rockchip-android-manifest/tree/63216f0fbd65385b71cea3fb228c7cb2da28153d) 的 `default.xml` 所描述的源码树。

```bash
PORT_ROOT="$(pwd)/port"
export GAMMA_SOURCE="$HOME/android/gammaos-pixel2"
export PIXEL2_SDK="$HOME/android/rockchip-android12"
export PIXEL2_SWAP_OUTPUT="$HOME/android/pixel2-output"

git clone --no-checkout https://github.com/TheGammaSqueeze/GammaOSDistribution "$GAMMA_SOURCE"
git -C "$GAMMA_SOURCE" checkout --detach b2db9cfe308c8753e3385b8ab64bcb34c3177177
git -C "$GAMMA_SOURCE" lfs pull
python3 "$PORT_ROOT/prepare-pixel2-gamma-source.py" "$GAMMA_SOURCE" --apply
board="$GAMMA_SOURCE/device/phh/treble/pixel2"
install -d "$board"
for file in product.mk gkd_pixel2_joypad.kl pixel2-zram.rc fstab.pixel2.zram compatibility_matrix.pixel2.xml; do
    install -m 0644 "$PORT_ROOT/gamma-board/$file" "$board/$file"
done
(
    cd "$GAMMA_SOURCE"
    export OUT_DIR="$GAMMA_SOURCE/out-pixel2-gamma"
    source build/envsetup.sh
    lunch lineage_a64_bvN-userdebug
    m -j8 host_init_verifier
)
bash "$PORT_ROOT/build-pixel2-gamma-virtual-memory.sh"
```

目标为 `lineage_a64_bvN-userdebug`，设备为 `phhgsi_a64_ab`。准备脚本会移除供体设备专用的启动、OTA 和调试规则，并保留 USB 调试授权。虚拟内存脚本会在专用工作树中临时应用设置、关机清理和系统服务改动。请串行运行。产出为 `$PIXEL2_SWAP_OUTPUT/system.img`。

需要从上游取得与固定版本相符的 LFS 对象，例如 ARM WebView、GammaOS 的 Daijishō 和编译工具。先确认本地文件已实体化，缺失对象会让构建中止。这些对象的可获取性取决于相应上游。GammaOS 准备脚本会校验 Daijishō 的文件大小和 SHA-256。

## 2. 板级内核和面板设备树

参考内核是 [Rockchip BSP 5.10.226](https://github.com/bmdhacks/kernel_rk3562/tree/0c1ad27d20bb8d84a41cd8ac913829a7bd934329)。将其放在 `$PIXEL2_SDK/work/build/pixel2-kernel-5.10-bsp/source`。同级目录需准备下面三个输入，脚本会校验其 SHA-256。

| 本地文件 | 来源 |
| --- | --- |
| `pixel2-bsp.config` | [AURKNIX RK3326S 板级配置](https://github.com/AveyondFly/distribution_rocknix/blob/aadfbafc5273983b5e255d1dbe76634321739fe5/projects/ROCKNIX/devices/RK3326S/linux/linux.aarch64.conf) |
| `rk3326s-gkd-pixel2.dts` | [同一 AURKNIX 版本的 GKD Pixel 2 DTS](https://github.com/AveyondFly/distribution_rocknix/blob/aadfbafc5273983b5e255d1dbe76634321739fe5/projects/ROCKNIX/devices/RK3326S/linux/dts/rockchip/rk3326s-gkd-pixel2.dts) |
| `android12-5.10-base.config` | [AOSP 5.10 内核基础配置](https://android.googlesource.com/kernel/configs/+/d5ae8157dad45978607876c426640dd85a32f41e/android-5.10/android-base.config) |

```bash
export ANDROID_ROOT="$PIXEL2_SDK"
bash "$PORT_ROOT/build-pixel2-kernel-5.10.sh"
```

脚本应用主显示通道和 RK817 电量修复，合入 Android 配置，输出 `out/arch/arm64/boot/Image` 和参考 DTB。实机使用的是从本机原厂卡取得的面板 DTB。复制该 DTB 到临时目录，在副本中从 `/cpu0-opp-table` 与 `/px30s-cpu0-opp-table` 移除 `opp-1512000000`，核对两个表都保留 `opp-1416000000`，且 `/aliases` 下的 `mmc0` 指向 `/dwmmc@ff370000`。参考 DTB 和原厂面板 DTB 的面板描述不同。

## 3. 独立启动分区

准备由 Rockchip SDK 和 Pixel 2 板级配置生成的原始 `super.raw.img`。它应含 `system`、`vendor`、`vendor_dlkm`、`odm`、`odm_dlkm`、`product` 和 `system_ext`。打包器将两个元数据槽都写成新的 `system` 和原样保留的四个板级分区。`product` 与 `system_ext` 由 GammaOS 的 `system` 镜像内提供。

```bash
python3 "$PORT_ROOT/prepare-pixel2-gamma-direct-super.py"     --base-super "$HOME/pixel2-inputs/super.raw.img"     --system "$PIXEL2_SWAP_OUTPUT/system.img"     --tools "$PIXEL2_SDK/out/host/linux-x86/bin"     --output "$PIXEL2_SWAP_OUTPUT/super.raw.img"
```

首次启动需要独立的、空白的 `metadata` 和 `userdata`。实测数据卷为启用元数据加密的 F2FS。原来试用槽的密钥和数据不能用作新数据区。`make-pixel2-test-gpt.py` 接受测试卡的**准确字节数**和一个输出目录，离线生成主备 GPT 和布局 JSON。它只创建普通文件。集成时需保留匹配的 Rockchip 启动链，保证生成的磁盘 GUID、分区边界和诊断 ramdisk 使用的布局一致。

准备对应的 Rockchip Android legacy U-Boot ramdisk。它必须包含 `fstab.rk30board`。下面生成 ramdisk，并检查启动脚本的封装：

```bash
test_dir="$PIXEL2_SWAP_OUTPUT/card-files"
mkdir -p "$test_dir"
python3 "$PORT_ROOT/make-pixel2-test-gpt.py" "$TF_CARD_BYTES" "$test_dir/gpt"
python3 "$PORT_ROOT/diagnostics/build-diagnostic-init.py"     --android --capture-display --reinitialize-panel --pointer --storage-log     --standalone-gamma --layout "$test_dir/gpt/partition-layout.json"     --output-dir "$test_dir/boot"
cp "$PORT_ROOT/boot/boot-script.txt" "$test_dir/boot/boot-script.txt"
python3 "$PORT_ROOT/make-pixel2-uboot-script.py" "$test_dir/boot/boot-script.txt" "$test_dir/boot/boot.ini"
python3 "$PORT_ROOT/verify-pixel2-vendor-script.py" "$test_dir/boot"
```

实机 FAT 启动分区用 `boot.ini` 启动，脚本读取 `P2BFX.IMG`（内核 `Image`）、`P2PAD.DTB`（修正后的面板 DTB）和 `P2GDK.UIM`（生成的 `ramdisk.uimg`）。此处的产物是分别供启动和逻辑分区使用的构件。组装到 TF 卡还需要匹配的板级固件、分区映射和文件系统。

参见[验证记录](validation.md)。
