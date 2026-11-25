# 图形驱动对照实验

这些文件记录 Mesa 21.2.6、22.3.7 和合成器的实机实验。当前系统驱动在 [pixel2-system-gpu](../vendor/pixel2-system-gpu/)，可下载的组件及匹配基线在 [组件说明](../../../docs/components.md)。

- `mesa21` 和 `mesa22` 各自的 local.patch 在 Android 构建中使用两个变量。将 `PIXEL2_SDK` 设为 Rockchip Android 源码的绝对路径，将 `PIXEL2_MESA_TOOLS` 设为包含 `usr/bin/meson`、`usr/bin/pkg-config` 和 `usr/lib/python3/dist-packages` 的工具目录。各补丁应用到目录名指定的 Mesa 版本。
- `hwc` 是同步与异步合成的对照修改。`tests` 包含离屏渲染、帧耗时和不同系统设置的测量程序。
- `kernel/gpu-floor.patch` 和 `Set-Pixel2Performance.ps1` 配套使用。在已部署这项内核功能、已连接 USB 调试的本机上，使用 `Get-Help ./Set-Pixel2Performance.ps1` 查看参数。400 MHz 性能档属于实机试用设置，续航未做对照。
