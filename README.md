# GammaOS for GKD Pixel 2

GKD Pixel 2（RK3326S / PX30S）的非官方 GammaOS 移植。系统基于 GammaOS v1.5（Android 12 / LineageOS 19），使用 32 位 ARM 用户空间、64 位 Binder 和 64 位 Linux 5.10 内核。GammaOS 已在备用 TF 卡上独立启动，卡上只保留这一套 Android 系统。

## 实机功能

- 冷启动可正常显示。功能键可退出默认锁屏。
- 长按 Select 打开或隐藏鼠标。十字键移动光标，A 点击，B 按住。退出鼠标模式后，十字键恢复菜单导航。
- 修正 RK817 电池百分比显示。
- 在「设置 → 系统 → 虚拟内存」可选择额外启用 **2 GiB** TF 卡交换空间。开关默认关闭，重启生效。系统原有的 ZRAM 单独运行。交换空间会占用卡内存储，可用内存和模拟器表现仍取决于具体负载。

## 构建和安装

- [Release 下载](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases)提供公开内核、对应源码、启动脚本和 SHA-256。
- [准备文件、组装镜像和写卡](docs/install.md)列出所有输入，并说明如何从自己的原装卡导出匹配的启动文件。
- [GammaOS 构建](docs/build.md)与 [Rockchip 板级构建](docs/rockchip-sdk.md)提供对应源码、固定版本和编译步骤。
- [实机与虚拟机验证](docs/validation.md)记录已测功能和已知限制。
- [上游项目与许可证](THIRD_PARTY_NOTICES.md)列出移植依赖和许可来源。
