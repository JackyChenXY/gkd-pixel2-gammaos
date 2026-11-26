# GammaOS for GKD Pixel 2

适用于 GameKiddy GKD Pixel 2（RK3326S / PX30S）。当前整卡版 **v0.3.2** 基于 GammaOS / Android 12，内置手柄桌面、按键鼠标、电量修正、最近任务内存显示和可选的 2 GiB TF 卡交换空间。

## Windows 一键准备并刷卡

**[下载 Windows 安装助手](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/Pixel2-Setup.exe)**

1. 把安装助手放到电脑上至少有 **8 GiB 可用空间**的文件夹，双击运行。它会取得公开固件、匹配的 Mali 驱动和原签名 AT4K 1.2，生成并校验完整镜像。AT4K 内置的 H700 原图也会成为系统默认壁纸。
2. 助手会打开 Raspberry Pi Imager。首次使用可按提示安装。在刷卡器里选择 **GKD Pixel 2 → GammaOS** 和目标 TF 卡，核对容量后确认写入。**刷写会清空所选卡。** 建议使用 16 GB 或更大的 TF 卡。
3. 刷卡器校验完成后，将卡装入已关机的掌机并开机。首次启动会扩展数据区，按功能键解锁。在首次出现的「选择主屏幕应用」里选 **AT4K → 始终**，即可进入带 H700 原壁纸的桌面。图形驱动默认使用 Mesa。要用已经装好的 Mali，打开 **设置 → 系统 → 图形驱动 → 关机试用 Mali**。掌机关机后，等电源灯熄灭、拔下 USB，约 10 秒后按电源键。进桌面后可点 **保留 Mali**。

**已知问题**　同一张实机卡的两次正式版 Mali 冷启动试用中，一次黑屏，一次正常进入 AT4K。若试用后黑屏超过约两分钟，拔掉 USB、长按电源直到灯灭，等约 10 秒再开机即可自动回到 Mesa。此回退已在掌机验证。

[刷卡步骤与首次使用](docs/flash-image.md) · [切换驱动和黑屏回退](docs/gpu-drivers.md)

## 直接下载公共镜像

Windows、macOS 和 Linux 都可以把公开的 `.img.gz` 原样刷入 TF 卡，刷好即可使用 Mesa/Panfrost。直接刷这个基础镜像会使用 Trebuchet 桌面。使用 Windows 助手可获得 AT4K、H700 壁纸以及可切换的 Mali 驱动。两种安装方式使用相同的系统、手柄功能和数据布局。

[下载公开整卡](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/GKD-Pixel2-GammaOS.img.gz) · [用 Etcher 打开公开镜像](https://efp.balena.io/open-image-url?imageUrl=https%3A%2F%2Fgithub.com%2FJackyChenXY%2Fgkd-pixel2-gammaos%2Freleases%2Fdownload%2Fv0.3.2%2FGKD-Pixel2-GammaOS.img.gz) · [版本、源码和校验值](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest)

## 掌机操作

- 按功能键退出默认锁屏。长按 Select 切换鼠标，十字键移动，A 点击，按住 B 长按。
- 最近任务里用左右选择，A 打开，X 关闭。面板会显示物理内存和 TF 卡交换空间的用量。
- 出厂已开启 Pixel 2 手柄导航，并隐藏屏幕右侧的三键栏。先按 R1，随即点功能键即可呼出返回、桌面和最近任务菜单。可以在「设置 → 无障碍」关闭或重新启用。
- 在「设置 → 系统 → 虚拟内存」可开启额外 2 GiB TF 卡交换空间，重启生效。

[实机记录与验证范围](docs/validation.md) · [PPSSPP 与吉里吉里推荐设置](docs/components.md#模拟器推荐设置) · [构建说明](docs/build.md) · [第三方许可](THIRD_PARTY_NOTICES.md)
