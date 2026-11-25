# 安装 GammaOS

适用机型为 GKD Pixel 2。请准备读卡器和一张 16 GB 或更大的 TF 卡。**确认写入后，所选卡上的内容会被清空。**

## Windows 10 / 11 x64

1. 将安装助手保存到本机 NTFS 或 exFAT 文件夹，留出至少 8 GiB。可以直接放在 E 盘。双击后，助手会获取约 660 MiB 的公开固件、约 28 MB 的驱动文件和约 12 MB 的 AT4K 安装包，生成 7 GiB 的 `GKD-Pixel2-GammaOS-AT4K-Mali.img`。[下载安装助手](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/Pixel2-Setup.exe)
2. 助手完成整卡校验后会打开 Raspberry Pi Imager。首次运行时可同意安装官方刷卡器并完成 Windows 的安装提示。选择 **GKD Pixel 2 → GammaOS**，再选目标 TF 卡，核对容量后确认写入。保留写入校验。如果自行打开刷卡器，选择「使用自定义镜像」，选刚生成的 `.img`。[Imager 官方说明](https://www.raspberrypi.com/documentation/computers/imager.html)
3. 校验完成后安全弹出卡，插入已关机的掌机，按电源开机。首次初始化需要几分钟。Windows 若提示格式化卡上的其他分区，请点取消。

已生成的双驱动镜像可以留在电脑上重复刷卡。再次运行助手会校验已有镜像。同名文件内容不匹配时，换一个空文件夹即可。已有本版公开镜像、匹配的 `Pixel2-Mali.local.zip` 或原版 `AT4K-H700.apk` 时，可放在助手的输出目录内复用。

## Windows、macOS 和 Linux 通用刷法

下载公开整卡 `GKD-Pixel2-GammaOS.img.gz`，在 Etcher 或 Raspberry Pi Imager 中选择该压缩文件和目标 TF 卡，确认写入并等待校验。此镜像开机即可使用 Mesa/Panfrost。[直接下载](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/GKD-Pixel2-GammaOS.img.gz) · [Etcher 官方下载](https://etcher.balena.io/) · [Imager 安装清单](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/GKD-Pixel2.rpi-imager-manifest)

## 首次开机

- 系统自动扩展数据分区，初始语言为简体中文。Windows 助手生成的整卡默认进入 AT4K 并使用 H700 壁纸。直接刷入公共基础镜像会进入 Trebuchet。按功能键可退出默认锁屏。
- 双驱动镜像初次使用 Mesa。要试用 Mali，在「设置 → 系统 → 图形驱动」选择「重启试用 Mali」。[确认保留和恢复方法](gpu-drivers.md)
- 游戏由使用者导入。手柄导航、虚拟内存和吉里吉里兼容条件见[掌机功能说明](components.md)。
- 固件为 Android 12 工程构建，使用测试签名和 SELinux permissive。USB 调试需要在设备上授权。

## 核对下载

发行页的 `SHA256SUMS` 收录公开附件。助手在本机生成的双驱动镜像为 **7,516,192,768 字节**，SHA-256 为 `fc6bdd00578d110806937e0bb5ccfeccc67a2169e9513bdf6cbe9703694eaa8a`。[查看校验文件](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/SHA256SUMS)
