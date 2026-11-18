# 生成 Rockchip Android 12 板级文件

独立版 GammaOS 使用 RK3326 的 Android 板级分区和首次挂载配置。这些文件由 Rockchip SDK 的 `gkd_pixel2-userdebug` 目标生成。运行 GammaOS 时使用的 5.10 内核见[构建说明](build.md)。本页的 4.19 内核用于满足 Rockchip SDK 打包 `boot.img` 和 `recovery.img` 的依赖。

## 1. 同步 SDK

参考系统为 x86-64 Ubuntu 22.04，Android 构建使用 JDK 11。准备 Git、Git LFS、[Repo](https://source.android.com/docs/setup/download)、GNU 构建工具、Python 3、`python-is-python3`、`device-tree-compiler`、`u-boot-tools`、`e2fsprogs`、`bc`、`bison`、`flex`、`libssl-dev`、`libelf-dev`、`cpio`、`rsync` 和 `lz4`。SDK 包含大量独立项目及大型 Git LFS 文件，源码和输出适合放在空间充足的 Linux 文件系统中。

```bash
# 在移植仓库根目录运行。将原装卡 DTB 的副本放到此路径。
PORT_ROOT="$(pwd)"
STOCK_DTB="$HOME/pixel2-inputs/rk3326s-gkd-pixel2.dtb"
export ANDROID_ROOT="$HOME/android/rockchip-android12"
test -s "$STOCK_DTB"
git lfs install
mkdir -p "$ANDROID_ROOT"
(
    cd "$ANDROID_ROOT"
    repo init -u https://github.com/JackyChenXY/gkd-pixel2-gammaos.git -b main -m manifests/rockchip-android12-pixel2.xml
    repo sync -j8
)
```

[固定提交清单](../manifests/rockchip-android12-pixel2.xml)来自实际测试的 [Rockchip Android 12 SDK 清单](https://github.com/TinkerBoard-Android/rockchip-android-manifest/tree/63216f0fbd65385b71cea3fb228c7cb2da28153d)，并把各项目锁定到测试时的提交。确保大型工具链和预编译文件已经下载为实体文件。若某个上游项目只有 LFS 指针，进入该项目目录运行 `git lfs pull`，再检查相应对象是否可用。参考构建用的 LFS 内容依赖上游提供，整个 SDK 尚未在另一台全新电脑上完整重建。

## 2. 构建板级资源

```bash
JOBS=8 bash "$PORT_ROOT/port/rockchip-sdk/build-board.sh" "$STOCK_DTB"
```

使用专用 SDK 工作树。脚本会在其中应用 4.19 补丁、安装 `device/gamekiddy/gkd_pixel2` 配置，并编译内核和 Android 板级文件。板级 DTS 的屏幕初始化数据通过 `fdtget` 从自己的原装卡 DTB 读取。脚本会拒绝改写不匹配的现有板级文件。改动前后都可以通过 `repo status` 查看 SDK 状态。

完成后可在 `$ANDROID_ROOT/out/target/product/gkd_pixel2/` 找到：

| 文件 | 用途 |
| --- | --- |
| `super.img` | Android sparse 格式。转为 raw 后供 GammaOS 离线打包器提取 `vendor`、`vendor_dlkm`、`odm`、`odm_dlkm` |
| `ramdisk.img` | gzip 压缩的 Android 初始根目录，包含 `fstab.rk30board` |
| `boot.img`、`recovery.img` | 对应 GPT 的 `boot`、`recovery` 分区输入 |
| `rebuild-dtbo.img` | 对应 GPT 的 `dtbo` 分区输入 |
| `cache.img` | Android sparse 格式。转换后供 GPT 的 `cache` 分区使用 |

工具位于 `$ANDROID_ROOT/out/host/linux-x86/bin/`。准备好这些输入后，继续[独立刷卡安装](install.md)。历史实机使用的 Rockchip 板级输入由同一套源码修订、设备配置和 SDK 流程生成。
