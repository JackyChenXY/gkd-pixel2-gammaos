# Pixel 2 的 Mali‑G31 二维旋转驱动

`libpixel2_g31.so` 在 Pixel 2 的 Mali‑G31 上执行整幅 RGBA8888 图像的复制和直角旋转。程序通过 Panfrost 内核接口分配显存、导入图像并提交计算作业。GPU 执行的三个程序由本目录的着色器源码生成。核心库在本机编译后只动态依赖 Android 的 `libc.so`。安卓缓冲区适配库单独链接 `libnativewindow.so`。

适用场景是把模拟器或显示组件已经画好的一张图复制到另一张缓冲区，并按面板方向旋转。GammaOS 桌面与模拟器的 3D 渲染仍由 Mesa 负责。PPSSPP 的实机接入、安装方法和游戏帧时间见 [PPSSPP 显示测试](ppsspp/README.md)。其他调用方可以通过下面的接口显式提交画面。

系统跑分与 G31 输出对照可在掌机上直接运行。[glmark2 安装、快测和实机数据](glmark2/README.md)

## 图像与同步

- 支持单平面、线性、32 位 RGBA 图像。顺时针旋转角度为 0°、90°、180° 或 270°。宽高范围为 1 到 4096，行跨度以像素为单位，最大 8192。90° 和 270° 要求目标的宽高互换。
- 对常见的对齐图像，90° 和 270° 使用 4×4 像素分块。逐像素程序负责其余尺寸、步幅和对齐方式。可导入现有 DMA-BUF，也可分配新表面并导出 DMA-BUF。
- `g31_import_android` 从本移植版本的 minigbm 获取平面、偏移和行跨度，并验证格式与线性布局。它可直接使用 `AHardwareBuffer` 原有存储。
- `g31_rotate` 等待 GPU 完成后返回。`g31_rotate_async` 接受一个可选的输入同步文件并返回输出同步文件。最多三次异步提交可同时占用命令缓冲区。调用方负责让输入信号覆盖上游写入及目标缓冲区的既有访问，并把输出信号交给下一位使用者。返回的文件描述符由调用方关闭。
- 在输出完成前持有两个表面与外部安卓缓冲区。源与目标使用不同的存储。处理完所有作业后调用 `g31_destroy`、`g31_close`。核心入口见 [g31.h](g31.h)，安卓入口见 [android_surface.h](android_surface.h)。

## 编译与实机验证

在 Linux 或 WSL 中，指定解压后的 Mesa 22.3.7 源码和输出目录。设置 `ANDROID_NDK_HOME` 可以编译核心库与自测。设置 `PIXEL2_ANDROID_SDK` 指向已经构建过的 Pixel 2 Android 12 SDK，还会生成 minigbm 适配库与比对程序。本机使用了 SDK 工具链。

```bash
export PIXEL2_ANDROID_SDK=/path/to/built-pixel2-android-sdk
bash build-android.sh /path/to/mesa-22.3.7 ./out
adb shell mkdir -p /data/local/tmp/pixel2-g31-test-run
adb push out/libpixel2_g31.so out/pixel2-g31-test /data/local/tmp/pixel2-g31-test-run/
adb shell 'cd /data/local/tmp/pixel2-g31-test-run && chmod 755 pixel2-g31-test && LD_LIBRARY_PATH=. ./pixel2-g31-test'
```

若使用了 SDK，可再运行安卓缓冲区对照。程序在后台绘制，桌面可以继续运行。

```bash
adb push out/libpixel2_g31_android.so out/pixel2-g31-bench /data/local/tmp/pixel2-g31-test-run/
adb shell 'cd /data/local/tmp/pixel2-g31-test-run && chmod 755 pixel2-g31-bench && LD_LIBRARY_PATH=. ./pixel2-g31-bench'
```

`compile_shader.c` 定义 GPU 像素处理程序。`g31_program.h` 是由 Mesa 22.3.7 的开源 Bifrost 编译器生成的对应指令和状态数据。可从原版归档独立重建并比对每个字节。脚本需要 Linux C/C++ 编译器、Meson、Ninja、Python/Mako、pkg-config、Bison、Flex、zlib、Expat 以及至少 2.4.109 的 libdrm 开发文件。脚本在新建的工作目录中构建。[Mesa 官方源码归档](https://archive.mesa3d.org/older-versions/22.x/) · [Linux Panfrost 用户态接口](https://github.com/torvalds/linux/blob/master/include/uapi/drm/panfrost_drm.h)

```bash
bash rebuild-shader.sh /path/to/mesa-22.3.7.tar.xz ./compiler-work
```

## Pixel 2 实测

在 GammaOS Android 12 ARM32、Panfrost 5.10.226 与 400 MHz GPU 最低档位下，自测通过 80 次图像旋转、一次非零偏移子图导入和七次串联的异步旋转。独立同步测试将输入信号延迟 60 毫秒，确认输出在释放后完成且每个像素正确。自测覆盖 1×1、单行、单列、奇数边长、不同步幅、PSP 尺寸和原生屏幕尺寸，并逐行检查填充区。

下面是亮屏状态下两次独立进程的合并结果。新驱动和 Mesa GLES 在每个尺寸下共用同一对安卓硬件缓冲区，执行相同的 270° 旋转。每条路径每个尺寸计时 256 次，包含提交及等待完成。每组完成后用 CPU 核对整张图。单位为毫秒。

| 输入尺寸 | Mesa 中位数 | 新驱动中位数 | Mesa 第 95 百分位 | 新驱动第 95 百分位 |
| --- | ---: | ---: | ---: | ---: |
| 480×272 | 0.958 | 0.823 | 1.142 | 0.958 |
| 640×480 | 1.938 | 1.915 | 2.201 | 2.141 |

PSP 尺寸单次旋转节省约 0.135 毫秒。全屏中位数相差约 0.023 毫秒。这里计时到目标图像可以读取。包含应用与安卓合成的实机结果见上面的 PPSSPP 显示测试。

本目录的独立二维驱动使用 Apache-2.0。PPSSPP 子目录按各文件的 SPDX 标识使用 GPL-2.0-or-later 或 Apache-2.0。外部 Mesa 生成工具、描述符、Linux UAPI 头文件及 minigbm 头文件沿用各自上游许可。[项目内的 Apache-2.0 文本](../../../../LICENSES/Apache-2.0.txt)
