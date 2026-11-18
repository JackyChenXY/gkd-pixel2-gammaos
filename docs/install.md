# 从构建产物安装到备用 TF 卡

这份流程将 GammaOS 系统、Rockchip 板级分区和你自己原装卡的启动文件合并到一份普通镜像。镜像里的 `userdata` 是空白的，第一次开机会创建新的加密数据区。

写入会清空目标 TF 卡。准备一张空白备用卡，并记下容量，保留原装卡用于恢复。本地组装脚本只输出普通文件。最后一步由你在写盘工具中选择并确认备用卡。

## 1. 准备输入

在 Linux 或 Ubuntu 22.04 WSL 的仓库根目录执行。需要 `python3`、`dosfstools`、`mtools`、`e2fsprogs`、`u-boot-tools` 和 `device-tree-compiler`。在有足够空间的 Linux 文件系统里组装镜像。

| 文件 | 取得方法 |
| --- | --- |
| `system.img` | [构建 GammaOS 镜像](build.md#1-gammaos-系统分区)，取 `$PIXEL2_SWAP_OUTPUT/system.img` |
| `super.img`、`cache.img`、`boot.img`、`recovery.img`、`rebuild-dtbo.img`、`ramdisk.img` | [Rockchip SDK 板级构建](rockchip-sdk.md)，取 `$PIXEL2_SDK/out/target/product/gkd_pixel2` |
| `stock-boot-sectors.img` | 从自己的原装卡开头只读导出 16 MiB |
| `rk3326s-gkd-pixel2.dtb` | 从原装卡 `EMUELEC` 分区复制；屏幕批次请与自己的机器匹配 |
| `P2BFX.IMG` | [Releases](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases) 的公开构建，或[自行编译内核](build.md#2-从源码编译-510-内核)后将 `Image` 复制为该文件 |

从原装卡复制 DTB 后，在 Linux 用 `lsblk -b -o NAME,TYPE,SIZE,MODEL,TRAN` 核对读卡器。`STOCK_DISK` 设为原装 TF 卡的整盘设备路径，例如 `/dev/sdX`。下面的 `if` 是读入设备，`of` 是一个新的普通文件。Linux 识别不到 WSL 里的读卡器时，可以在原生 Linux 上完成导出，再把文件复制到 WSL。

```bash
export PORT_ROOT="$(pwd)/port"
export INPUTS="$HOME/pixel2-inputs"
mkdir -p "$INPUTS"
# 先按 lsblk 输出设定 STOCK_DISK，再执行只读导出。
sudo dd if="$STOCK_DISK" of="$INPUTS/stock-boot-sectors.img" \
    bs=1M count=16 iflag=fullblock conv=excl status=progress
```

原装卡也可以使用之前完整导出的首 64 MiB 文件。新镜像仅取前 16 MiB 中的引导内容，并从该区域提取原装 U-Boot 和 trust。导出后拔下原装卡。

## 2. 生成 GammaOS 启动文件和逻辑分区

先将 `TF_CARD_BYTES` 设置成备用卡的准确字节数。Linux 可从 `lsblk -b` 读取，Windows 可用 PowerShell 的 `Get-Disk | Select-Object Number,FriendlyName,Size` 查看。保留这一轮生成的 GPT 目录，启动 ramdisk 与它共享磁盘 GUID。

在以下命令中，`PIXEL2_SDK` 和 `PIXEL2_SWAP_OUTPUT` 使用构建时的绝对路径。把下载验证过的 `P2BFX.IMG` 放入 `$INPUTS`，或用本地编译的内核代替。

```bash
board="$PIXEL2_SDK/out/target/product/gkd_pixel2"
tools="$PIXEL2_SDK/out/host/linux-x86/bin"
test_dir="$HOME/pixel2-install"
mkdir -p "$test_dir/boot"

"$tools/simg2img" "$board/super.img" "$test_dir/base-super.raw.img"
"$tools/simg2img" "$board/cache.img" "$test_dir/cache.raw.img"
python3 "$PORT_ROOT/prepare-pixel2-gamma-direct-super.py" \
    --base-super "$test_dir/base-super.raw.img" \
    --system "$PIXEL2_SWAP_OUTPUT/system.img" --tools "$tools" \
    --output "$test_dir/super.raw.img"
mkimage -A arm64 -O linux -T ramdisk -C gzip -a 0 -e 0 \
    -n 'Pixel 2 Android ramdisk' -d "$board/ramdisk.img" "$test_dir/base-ramdisk.uimg"

python3 "$PORT_ROOT/make-pixel2-test-gpt.py" "$TF_CARD_BYTES" "$test_dir/gpt"
ANDROID_ROOT="$PIXEL2_SDK" python3 "$PORT_ROOT/diagnostics/build-diagnostic-init.py" \
    --android --capture-display --reinitialize-panel --pointer --storage-log \
    --standalone-gamma --base-ramdisk "$test_dir/base-ramdisk.uimg" \
    --layout "$test_dir/gpt/partition-layout.json" --output-dir "$test_dir/boot"

cp "$INPUTS/P2BFX.IMG" "$test_dir/boot/P2BFX.IMG"
bash "$PORT_ROOT/prepare-pixel2-stock-dtb.sh" \
    "$INPUTS/rk3326s-gkd-pixel2.dtb" "$test_dir/boot/P2PAD.DTB"
cp "$PORT_ROOT/boot/boot-script.txt" "$test_dir/boot/boot-script.txt"
python3 "$PORT_ROOT/make-pixel2-uboot-script.py" \
    "$test_dir/boot/boot-script.txt" "$test_dir/boot/boot.ini"
python3 "$PORT_ROOT/verify-pixel2-vendor-script.py" "$test_dir/boot"
```

发布附件同时提供封装好的 `boot.ini`。使用附件时，仍可用最后一条命令对照仓库里的 `boot-script.txt`。原厂 U-Boot 对脚本容器有特殊要求，请使用这份二进制封装。`P2PAD.DTB` 保留原面板参数，去掉两个 CPU 表里的 1.512 GHz 档位，并把手柄节点交给 `gpio-keys`。

## 3. 组装、校验和写卡

```bash
python3 "$PORT_ROOT/make-pixel2-card-image.py" \
    --gpt-dir "$test_dir/gpt" --boot-dir "$test_dir/boot" \
    --stock-boot-sectors "$INPUTS/stock-boot-sectors.img" \
    --stock-dtb "$INPUTS/rk3326s-gkd-pixel2.dtb" \
    --dtbo "$board/rebuild-dtbo.img" --boot-image "$board/boot.img" \
    --recovery-image "$board/recovery.img" --cache "$test_dir/cache.raw.img" \
    --super "$test_dir/super.raw.img" --output "$test_dir/pixel2-gammaos.img"
```

生成的 `pixel2-gammaos.img` 逻辑大小等于整张备用卡。在支持稀疏文件的文件系统上，实际占用更小。复制到其他文件系统可能实际占用完整容量。

1. 用支持原始磁盘镜像并带写后验证的工具打开 `pixel2-gammaos.img`，例如 [balenaEtcher](https://etcher.balena.io/)。
2. 核对目标确实是刚测量的备用卡。确认写入并等工具完成验证。若系统提示格式化安卓分区，选择取消。
3. 安全弹出，把备用卡插入掌机，从关机状态启动。首次启动预留约三分钟。进入桌面后再重启一次，按[实机验证清单](validation.md)检查手柄、电量和虚拟内存。

卡上 FAT 分区名为 `PIXEL2BOOT`。若卡在 Logo 或开机动画，可在关机后读出该分区的启动日志。若要回到原系统，关机后换回原装 TF 卡。
