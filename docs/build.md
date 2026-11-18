# 构建和离线打包

参考环境为 x86-64 Ubuntu 22.04（WSL 2），Android 构建用 JDK 11。需要 Git LFS、Python 3、GNU 构建工具、`e2fsprogs`、`u-boot-tools`、`device-tree-compiler`，以及 Rockchip SDK 的 AArch64 工具链和 `lpmake`、`lpdump`、`lpunpack`。请把大体积源码和构建输出放到有充足空间的 Linux 文件系统中。下面的命令分阶段生成文件，完整流程尚未在全新的机器上做端到端复现。

## 1. GammaOS 系统分区

从仓库根目录开始，取 [GammaOSDistribution 固定版本](https://github.com/TheGammaSqueeze/GammaOSDistribution/tree/b2db9cfe308c8753e3385b8ab64bcb34c3177177)，并按[Rockchip 板级构建说明](rockchip-sdk.md)准备所需 SDK。

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

## 2. 从源码编译 5.10 内核

安装流程可以使用 [Releases](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases) 的 `P2BFX.IMG`，也可以用下面的步骤编译。仓库已包含按 SHA-256 核对的 AURKNIX 板级配置与参考设备树，以及 AOSP 5.10 基础配置。内核源自 [Rockchip BSP 5.10.226 的固定提交](https://github.com/bmdhacks/kernel_rk3562/tree/0c1ad27d20bb8d84a41cd8ac913829a7bd934329)。

```bash
export ANDROID_ROOT="$PIXEL2_SDK"
export PIXEL2_KERNEL_BUILD="$HOME/android/pixel2-kernel-5.10"
mkdir -p "$PIXEL2_KERNEL_BUILD/source"
kernel_tar="$PIXEL2_KERNEL_BUILD/linux-upstream.tar.gz"
curl -fL 'https://codeload.github.com/bmdhacks/kernel_rk3562/tar.gz/0c1ad27d20bb8d84a41cd8ac913829a7bd934329' -o "$kernel_tar"
printf '%s  %s\n' 94858bac5877d8bae01a87b98a7e3568d74a4f852c345fb8ce15e607c531166f "$kernel_tar" | sha256sum --check
tar -xf "$kernel_tar" -C "$PIXEL2_KERNEL_BUILD/source" --strip-components=1
cp "$PORT_ROOT/kernel-inputs/"* "$PIXEL2_KERNEL_BUILD/"
bash "$PORT_ROOT/build-pixel2-kernel-5.10.sh"
```

该脚本需要 SDK 内的 Clang r416183b1 和 Linaro AArch64 交叉工具链。它应用主显示通道和 RK817 电量补丁，检查内核选项，并输出 `$PIXEL2_KERNEL_BUILD/out/arch/arm64/boot/Image` 和社区参考 DTB。实机安装用的面板和手柄 DTB 由原装卡设备树经 [本地转换](install.md)生成。

从这里继续[组装离线卡镜像和写入备用 TF 卡](install.md)。
