# GKD Pixel 2 GammaOS 独立启动试验

这套试验使用从源码构建的 U-Boot 与 TF-A、Rockchip 官方授权分发的首级引导、基于 AURKNIX 的设备树，以及 Android 软件密钥服务和开源图形组件。桌面试验分支保留 Android 12 ARM32、Trebuchet、手柄键位和 2 GiB 交换空间配置。试验分区应使用空白数据区，避免将旧密钥和应用数据带入新构建。

## 构建独立组件

- `boot/build-open-boot.sh` 从固定 plastron 源码构建标准 U-Boot、PX30 TF-A BL31 和首级引导。需要可用的 AArch64 GNU 交叉编译器、可编译 U-Boot 的主机环境、SWIG、Python 开发头文件和 pyelftools。可使用 Ubuntu 的 `gcc-aarch64-linux-gnu`、`swig`、`python3-dev` 和 `python3-pyelftools`。产物 `open-boot-prefix.bin` 从 LBA 64 开始写入，原厂 U-Boot 与 DTB 无需输入。 [引导源码](https://github.com/ericreinsmidt/plastron/tree/b897f7c55ac0aa96601365467e34de3e422122f1)
- `kernel/build-panfrost-kernel.sh` 从所附 BSP 内核源码和当前 Android SDK 构建 `Image` 与 `rk3326s-gkd-pixel2-open.dtb`。设备树以许可明确的 AURKNIX 树为基础，并适配原有的面板时序、方向和 15 个实际 GPIO 按键。
- [系统分区试验构建](system/README.md)从[已完成的 GammaOS Android 12 构建](../../docs/build.md#1-gammaos-系统分区)导出新的 `system.img`，省去 Daijishō、预编译 WebView 和依赖它的 Jelly。首次显示测试走软件渲染，Panfrost 应用性能需要单独验证。
- [Android 板级分区](vendor/README.md)包含 DRM Hardware Composer、minigbm、SwiftShader、AOSP 软件 Keymaster 和 Gatekeeper。本次导出的板级分区省去了已识别的 Mali、Widevine、旧闭源媒体组件、无线固件、传感器校准和可选麦克风降噪预编译件。

```bash
port="$(pwd)/port"
bash "$port/open-variant/boot/build-open-boot.sh" "$HOME/pixel2-open-boot"
bash "$port/open-variant/kernel/build-panfrost-kernel.sh" "$PIXEL2_SDK" "$KERNEL_SOURCE_BUNDLE" "$HOME/pixel2-open-kernel"
bash "$port/open-variant/system/build-desktop-probe.sh" "$GAMMA_SOURCE" "$HOME/pixel2-open-system"
```

## 离线组装

`prepare-pixel2-gamma-direct-super.py --board-dir` 可用四个同版本的 `vendor`、`vendor_dlkm`、`odm`、`odm_dlkm` 镜像与新的 `system.img` 生成 `super.raw.img`。板级目录接受 Android sparse 的 `.img` 和 ext4 格式的 `.raw.img`。组装器会核对两个逻辑分区表与各逻辑分区的逐字节读回结果。

独立启动从第一个 FAT 分区读取标准 U-Boot 脚本、内核、设备树和 initramfs。组装器保留 GPT 布局，`dtbo`、`boot` 与 `recovery` 分区留空。试验版暂未提供恢复模式。写入后的启动文件和分区由组装器逐一读回校验。

使用 `build-desktop-card.sh` 完成上述组装。`BOARD_IMAGES` 是独立板级构建导出的目录，`DISK_BYTES` 使用备用卡的实际字节数。

```bash
bash "$port/open-variant/build-desktop-card.sh" "$PIXEL2_SDK" \
    "$HOME/pixel2-open-boot/open-boot-prefix.bin" "$HOME/pixel2-open-kernel" \
    "$HOME/pixel2-open-system/system.img" "$BOARD_IMAGES" "$DISK_BYTES" "$HOME/pixel2-open-card"
```

无 Wi-Fi 试验分支通过 system/apply-no-wifi-settings.py 修订并重编 Settings，涵盖 About Device 的 Wi-Fi 地址以及开发者选项的 Wi-Fi 日志和扫描节流控制。build-desktop-probe.sh 的可选 SETTINGS_INSTALL_DIR 与 SYSTEM_BYTES 参数用于按原逻辑分区大小打包 APK 和匹配的 ARM 预编译文件。

## 验证状态

- 新引导、设备树、Panfrost 内核和 Android 板级分区已独立编译。使用精简板级分区组装了 16 GiB 镜像，主备 GPT、FAT 文件和所有写入分区已逐一校验。另行读回确认旧启动和恢复分区为空。
- QEMU 使用单独的虚拟机内核和跳过模拟 TF 卡整区擦除的格式化工具。该测试确认软件 Keymaster 就绪、空白 F2FS 数据区格式化成功、加密数据区挂载，以及 Android 开始启动 Zygote。虚拟机缺少 Rockchip DRM 节点，图形分配服务退出并触发桌面重启。
- 116.5 GiB 实机测试卡已验证新引导、内核、480×640 屏幕和加密 F2FS 数据区。Android 已启动图形服务，但桌面未完成启动，后期内核日志记录到应用框架反复重启。后期日志确认，继承的 Rockchip 配置启用了无线投屏，Android 在缺少 Wi-Fi Direct 时启动该服务会崩溃。已重编板级分区关闭无线投屏，逐字节读回校验后，用户确认实机进入桌面。SwiftShader 桌面响应明显缓慢。可选 Panfrost 试验版已通过 ARM32 构建和实机卡读回校验，暂用 OpenGL ES 2.0。实机两次采样均报告 Mali-G31 (Panfrost)，系统完成启动，用户观察到桌面略有改善。已核验的 SwiftShader 板级镜像可用于回退。
- 另行试过放宽 Panfrost 200 和 300 MHz 档的共享电源请求范围。写入并读回校验后，软件重启及手动冷启动均黑屏。恢复原设备树后，实机冷启动进入桌面，USB 调试重新连通，运行中的设备树和 Panfrost 渲染器均已验证。
- 初次进入桌面的对照试验使用 SwiftShader。之后的实机版本已通过 Panfrost 硬件渲染冷启动到桌面，支持 OpenGL ES 3.1；详见 [Mesa 系统驱动及对照跑分](vendor/pixel2-system-gpu/) 和 [组件说明](../../docs/components.md)。系统省去 WebView、Jelly 和 Daijishō。依赖 WebView 的应用、无线适配器和硬件视频解码属于后续兼容性工作。
- Android 12 的框架兼容性可用下方命令检查。可选的 FCM 6 内核配置通过当前 Android 12 矩阵的 269／270 项内核要求。实际检查报告仍缺少 Panfrost 的 Android GPU 内存统计 tracepoint。16 GiB 试验镜像采用保留原有板级行为的默认内核配置。
- v0.3.0-rc.1 已从干净文件树生成公开整卡。固定板级使用当前 VNDK 32，启动动画从源码生成，三个静态工具改用 musl，旧 VNDK 快照和相机预编译工具已移除。发布附件附上引导、内核、Mesa、运行库源码及 Android NOTICE。[下载与刷卡](../../docs/flash-image.md)

```bash
bash "$port/open-variant/check-vintf.sh" "$PIXEL2_SDK" "$KERNEL_BUILD" "$SYSTEM_IMG" "$BOARD_IMAGES"
```
