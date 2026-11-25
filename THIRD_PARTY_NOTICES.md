# 上游项目与许可证

- Android 系统基于 [GammaOSDistribution](https://github.com/TheGammaSqueeze/GammaOSDistribution/tree/b2db9cfe308c8753e3385b8ab64bcb34c3177177)，沿用 LineageOS、AOSP 和 PHH Treble 的相应源码。Settings、frameworks/base 和 init 补丁保留涉及文件的上游许可；相关 [Apache 2.0 文本](LICENSES/Apache-2.0.txt)及上游 NOTICE 在 [LICENSES](LICENSES/)。
- 主显示通道和 RK817 电量修复适用于 [Rockchip Linux 5.10 BSP](https://github.com/bmdhacks/kernel_rk3562/tree/0c1ad27d20bb8d84a41cd8ac913829a7bd934329) 相应的 GPL 代码。见 [GPL 版本 2](LICENSES/GPL-2.0.txt)及各被修改文件的许可证标记。
- 仓库中的板级内核配置和设备树来自 [AURKNIX](https://github.com/AveyondFly/distribution_rocknix/tree/aadfbafc5273983b5e255d1dbe76634321739fe5)。保留设备树的 GPL-2.0-or-later 或 MIT 双许可证声明。5.10 基础配置来自 [AOSP kernel/configs](https://android.googlesource.com/kernel/configs/+/d5ae8157dad45978607876c426640dd85a32f41e) 的同一固定版本。
- 板级 Android 输入来自 [Rockchip SDK](https://github.com/TinkerBoard-Android/rockchip-android-manifest/tree/63216f0fbd65385b71cea3fb228c7cb2da28153d) 和本机板级文件。GammaOS 的 [Daijishō](https://github.com/TapiocaFox/Daijishou) 和 WebView 需分别从上游获取。各 Android 分区和引导组件的声明随整卡附带。

各第三方文件和上游项目继续适用各自的许可证。

## 桌面和图形组件

- Trebuchet / Quickstep 继承 GammaOS、LineageOS 和 AOSP 的 Launcher3。发布附件随附对应构建的 [NOTICE](LICENSES/NOTICE-TrebuchetQuickStep.txt)。针对该版本的四个桌面补丁在 [desktop/trebuchet](port/desktop/trebuchet/)。
- 开源 GPU 包包含 Mesa 24.3.4、libdrm 2.4.123 的上游源码、补丁和许可证。minigbm 头文件保留 Chromium OS 版权声明。许可按具体文件执行。[Mesa](https://archive.mesa3d.org/) · [libdrm](https://dri.freedesktop.org/libdrm/)
- Pegasus 主题基于 Blood_roc 的 PegasusG by ROC v1.09。适配目录保留上游许可、商标条款和署名。[主题声明](port/desktop/pegasus-theme/NOTICE.zh-CN.md) · [上游](https://github.com/LPF970915/PegasusG-by-ROC/tree/91ed046e0b062f687636c93ed79e6cd8a673c7ff)
- AT4K、H700 壁纸、官方 PPSSPP 和官方吉里吉里 APK 从各自上游获取。[H700Android](https://github.com/LPF970915/H700Android) · [PPSSPP](https://www.ppsspp.org/download/) · [吉里吉里发布页](https://github.com/2468785842/krkr2/releases)

## 整卡引导和 Android 用户空间

引导采用 Rockchip 授权的 RK3326 DDR 初始化和 miniloader，原始文件来自 rkbin 固定提交。Plastron 板级脚本、U-Boot v2025.10、TF-A 的 PX30 BL31 及移植内核均有对应源码。源码附件内保留 Rockchip 原始分发声明、U-Boot 配置和 Linux 源码。固件载有 Android 各分区自己的 NOTICE；同版附件另提供这些声明及固定的 Android/SDK 源码坐标。静态早期初始化、交换助手与 getSPL 使用 musl 1.2.5，附对应源码和版权声明。启动进度动画由本仓库代码直接生成。[Rockchip 原始授权](https://github.com/rockchip-linux/rkbin/blob/74213af1e952c4683d2e35952507133b61394862/LICENSE) · [引导构建输入](https://github.com/ericreinsmidt/plastron/tree/b897f7c55ac0aa96601365467e34de3e422122f1) · [Android VNDK 版本与声明](https://source.android.com/docs/core/architecture/vndk/snapshot-generate) · [发行附件](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/tag/v0.3.0)

## 图形配置和 Windows 安装助手

Mali 内核接口来自 GPL Linux 5.10.226 的 Bifrost 驱动。对应源码包随附实际使用的 kbase 配置、Mesa/Panfrost 配置、板级补丁、U-Boot、TF-A、Android 源码信息及第三方声明。新增的驱动选择器、服务和 Windows 安装助手采用 Apache-2.0，Go 1.27.4 的标准库和运行库适用随附的 Go 许可。[整卡对应源码和声明](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/download/v0.3.0/GKD-Pixel2-sources-and-notices.tar.gz) · [Go 许可](https://go.dev/LICENSE)

Windows 助手附带八个单独核实来源的 ARM32 配套组件，对应 Arm gralloc、Android 图形服务和 libsync、Rockchip 合成器和 librga。公开配套包中的 SOURCES.json 记录逐项来源及固定版本，NOTICE.txt 保留相应声明。运行安装助手加上 --licenses 可读这些声明。[配套组件](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/download/v0.3.0/Pixel2-Mali-Support.zip)

Mali EGL 主库与两个 Android 启动配置由用户电脑从上游取得。这份 Android 主库的固定提交未附可核实的镜像再分发授权，其他平台的 Mali 发行条款并不能确认适用于它。公开基础镜像中，对应的 11 个文件区间均为零。[主库来源](https://github.com/TinkerBoard-Android/rockchip-android-vendor-rockchip-common/tree/5aeb28df3d0275ccd579ef99e3c164dabde744e9/gpu/MaliTDVx) · [内存分配配置](https://github.com/TinkerBoard-Android/rockchip-android-hardware-libgralloc-bifrost/blob/840796ba9508eab479f2086597cfb8c942e8b1e8/service/4.x/android.hardware.graphics.allocator%404.0-service.rc) · [显示合成配置](https://github.com/TinkerBoard-Android/rockchip-android-hardware-interfaces/blob/9a59bb6a44422046ba17b01ceb2e1b95af0fc074/graphics/composer/2.1/default/android.hardware.graphics.composer%402.1-service.rc)

Raspberry Pi Imager 由 Raspberry Pi 提供。用户选择安装时，助手会从官方发行页取得并检查安装文件，刷卡器保留自己的设备选择和写入确认界面。[官方发行版](https://github.com/raspberrypi/rpi-imager/releases/tag/v2.0.12)
