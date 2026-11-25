# 公开整卡镜像

[用户刷卡说明](../../docs/flash-image.md) · [公开附件和对应源码](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/tag/v0.3.0)

使用 独立启动的 GammaOS 工厂分区和已验证的图形、桌面组件，全程在 Linux 普通镜像文件上工作。请用空的 Linux 工作目录，准备 Python 3、rsync、e2fsprogs、mtools、dosfstools、gdisk、u-boot-tools、设备树工具、内核 ARM64 UAPI 头文件及 SDK 的主机工具。组装器中的路径参数应使用绝对路径。

1. [构建引导、内核和板级分区](../open-variant/README.md)。构建包内附实际配置、U-Boot 和 TF-A 固定源码、对应的 Linux 源码和 Rockchip 首级二进制的分发声明。使用已验证的面板设备树。Android 12 的板级分区要求 VNDK 32，本版保留当前 VNDK 并剔除 GSI 中兼容更老 vendor 的 v28–31 快照。
2. 按 [桌面构建步骤](../desktop/README.md) 准备两个 APK。按图形组件的固定清单准备 Kirikiroid2 工厂 system 与 Mesa ES100 vendor 基线。用 Linux 5.10 的 `make ARCH=arm64 headers_install` 安装 UAPI 头文件。
3. 从附件中的 musl 1.2.5 源码，在独立目录用 AArch64 交叉 GCC 设置 `CC` 和 `CROSS_COMPILE` 并运行 `configure --target=aarch64-linux-musl --enable-wrapper=gcc --disable-shared --prefix=/absolute/path/to/musl`，然后执行 `make` 和 `make install`。用 `musl-gcc -std=gnu11 -Os -static -s -idirafter "$HEADERS" ...` 分别编译本仓库 `port/pixel2-device/extra-swap/pixel2-extra-swap.c` 与 GammaOS 的 `device/phh/treble/fixSPL/getSPL.c`，产物命名为 `pixel2-extra-swap` 和 `getSPL`，放入同一工具目录。保持交叉 GCC 在 PATH 中。
4. 在私有挂载命名空间组装新的系统和 vendor。两个程序会在输出前核对文件内容和标签。GammaOS 源码树须已有匹配的主机构建工具。

```sh
sudo unshare -m --propagation private python3 make-system.py \
    --baseline "$FACTORY_SYSTEM" --gamma "$GAMMA_SOURCE" --runtime "$TOOLS" \
    --desktop "$QUICKSTEP_APK" --navigation "$PAD_APK" --output "$WORK/system.img"
sudo unshare -m --propagation private python3 make-vendor.py "$ES100_VENDOR" "$WORK/vendor.img"
bash assemble-image.sh "$SDK" "$BOOT_PREFIX" "$KERNEL" "$PANEL_DTB" "$BOARD_IMAGES" \
    "$WORK/system.img" "$WORK/vendor.img" "$MUSL_CC" "$HEADERS" "$WORK/card"
python3 test-grow.py "$WORK/card/gpt"
xz -T2 -3 -c "$WORK/card/GKD-Pixel2-GammaOS.img" > "$WORK/GKD-Pixel2-GammaOS.img.xz"
```

`grow-card.c` 只在匹配的 SD 控制器、镜像 GUID、完整分区表校验值及空白数据区上扩展末尾的 userdata。写入顺序为备份表、主表、保护 MBR，再通知内核重新读取。测试程序只打开稀疏普通文件。刷写新构建生成的 GPT 标识和 ext4 元数据可能不同，发布文件以该版本的 SHA-256 为准。
