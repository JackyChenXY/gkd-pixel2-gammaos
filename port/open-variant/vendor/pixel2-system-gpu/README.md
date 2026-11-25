# GKD Pixel 2 系统图形驱动

这个版本用 Mesa 24.3.4 Panfrost 从源码构建 Android 12 ARM32 的 EGL、OpenGL ES 1.x 和 OpenGL ES 2.x/3.x 系统库，并静态链接 libdrm 2.4.123。Android 按原有的 `ro.hardware.egl=mesa` 配置加载这些库。SurfaceFlinger、HWUI、启动器和普通 GLES 应用都走系统入口，应用可以保持官方原包。[Android 系统 EGL 接口](https://source.android.com/docs/core/graphics/implement-opengl-es) · [Mesa 24.3.4 发行记录](https://docs.mesa3d.org/relnotes/24.3.4.html)

Pixel 2 专用代码在 EGL 导入窗口图像时识别当前 minigbm 的单平面线性 RGB 缓冲区，核对格式、宽高、步幅和有效字节范围。其他格式和直接导入失败的图像继续交给 Mesa 的安卓分配器接口。归还窗口缓冲区时传递已有的读写同步信号。该版本使用板上的 Panfrost 内核接口、Rockchip 显示控制器、DRM Hardware Composer 和 minigbm。3D 绘制采用 Panfrost。本项目在 Mesa 着色器链接器中修复了下面记录的一个旧版游戏黑屏问题。当前构建面向 EGL/OpenGL ES，Vulkan 未启用。

## 生成分区

需要已构建的 GKD Pixel 2 Android 12 SDK、该 SDK 的 ARM32 Mesa `MESON_MESA3D_GEN/aosp_cross` 和同目录的 pkg-config 文件、Meson 1.5.2、Ninja、pkg-config、Mako、PyYAML、Bison、Flex、patch、GNU binutils 与 e2fsprogs。若之前通过私有 overlay 构建 Android，按顺序将提供链接库的 upper 目录传给脚本。Meson 的 Python 模块应能通过 `python3 -m mesonbuild.mesonmain --version` 调用。设置 `NINJA` 可以使用 SDK 的 Ninja。构建目录应位于 Linux 文件系统。

```sh
bash build.sh "$SDK" "$AOSP_CROSS" mesa-24.3.4.tar.xz libdrm-2.4.123.tar.xz ./pixel2-build "$SDK_UPPER"
python3 pack-vendor.py "$KNOWN_GOOD_VENDOR" ./pixel2-build/install/vendor/lib ./vendor-gkd-pixel2-mesa24.raw.img
```

脚本校验上游归档和板级分配器头文件，生成五个库，并保留 Panfrost 着色器缓存需要的 20 字节 ELF 构建标识。两个归档可从官方目录获取。[Mesa 源码归档](https://archive.mesa3d.org/mesa-24.3.4.tar.xz) · [libdrm 源码归档](https://dri.freedesktop.org/libdrm/libdrm-2.4.123.tar.xz)

`KNOWN_GOOD_VENDOR` 是此 116.5 GiB 实机测试卡已验证的 Mesa 22.3.7 分区，SHA-256 为 `3bde0866c8ad3bdd87356db208ff0605e5a80809de927e48ccdd32a869fa3047`。输出是 **54,906,880 字节的 vendor 逻辑分区**，用于现有测试卡上的分区替换。把它当作整卡镜像写到 TF 卡开头会破坏引导。打包器比较全部文件及符号链接，复核五个库的架构、依赖、构建标识、权限、标签和 ext4 一致性。镜像将 `ro.opengles.version` 从之前的 131072 调为 196609，供冷启动时的 Android 包管理器识别 GLES 3.1。

## 实机核验

先通过标准系统加载器运行未改动的程序，核对 `dumpsys SurfaceFlinger` 和应用报告的渲染器。此板对应 `Mali-G31 (Panfrost)`、`OpenGL ES 3.1 Mesa 24.3.4`。Android 12 的调试版可用已授权的 adb 查看 SurfaceFlinger、桌面和设置的 `/proc/PID/maps`，确认都映射 `/vendor/lib/libgallium_dri.so`。每个进程首次成功导入板级线性 RGB 图像时，Mesa 会留下一行 `Pixel 2 system EGL: imported linear RGB window buffer`。

`check-gles.c` 通过 Android 公共 EGL/GLES 库创建并保留三个上下文，然后反向切换，逐像素检查三幅独立颜色图，并核对 ES 3.1 计算着色器的 64 个输出。可以用 Linux Android NDK 编译。

```sh
"$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi31-clang" -std=gnu11 -O2 check-gles.c -lEGL -lGLESv3 -ldl -o check-gles
adb push check-gles /data/local/tmp/check-gles
adb shell chmod 755 /data/local/tmp/check-gles
adb shell /data/local/tmp/check-gles
```

复测系统性能用 F-Droid 原版 GLMark2 的 33 项默认场景，记录每轮实际渲染器、频率和温度。应用专用输出和标准系统驱动有不同的显示路径。[glmark2 复测说明](../pixel2-g31/glmark2/README.md)

### 旧版 GLES 着色器精度

KrKr2 1.4.4 的一组 GLSL ES 1.00 着色器在两个阶段声明同一个矩阵，只在其中一个阶段读取它。Mesa 原有的链接规则容许这种未使用声明的精度差异，但编译器先把其中一个矩阵转成半精度，让链接器误报类型冲突。系统驱动记录编译器所做的转换，仅在比较这类声明时还原其原始类型。实际参与绘制的变量沿用原来的精度。这个修复适用于使用同一系统驱动的 GLES 应用。

在 Pixel 2 的 Mali-G31 上，原 Mesa 24.3.4 分区有 6 组未达到预期。更新后的库通过了 `check-uniform-precision.c` 的全部 15 组用例，包括两个着色阶段互换、矩阵数组和高精度像素回读。矩阵形状、数组长度和两个阶段都在使用的精度冲突仍按预期被拒绝。GLSL ES 3.00 的严格校验也通过了对照测试。

```sh
"$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/armv7a-linux-androideabi31-clang" -std=c11 -O2 -Wall -Werror check-uniform-precision.c -lEGL -lGLESv3 -o check-uniform-precision
adb push check-uniform-precision /data/local/tmp/check-uniform-precision
adb shell chmod 755 /data/local/tmp/check-uniform-precision
adb shell /data/local/tmp/check-uniform-precision
```

### 同机测量

USB 试跑临时将候选驱动库只读挂载到测试卡系统的 `/vendor/lib`，随后重启 SurfaceFlinger 和安卓应用框架。SurfaceFlinger、SystemUI、Trebuchet 和设置均映射新版 Gallium 库。原版 GLMark2 报告 Mesa 24.3.4 并记录了板级 RGB 导入成功。掌机能进入休眠，再唤醒并返回设置。

| 系统驱动 | 原版 GLMark2 两轮总分 | 均值 | 地形 | 折射 |
| --- | --- | ---: | ---: | ---: |
| Mesa 22.3.7 | 220、224 | 222 | 10 FPS | 6 FPS |
| Pixel 2 Mesa 24.3.4 | 255、251 | 253 | 11 FPS | 7 FPS |

两版都在原生分辨率、USB 供电、400–520 MHz 按需调频下完成全部 33 项，综合分均值提高约 14%。各轮起始温度有差异。这些数据度量这套图形负载。GLES 1、2、3 三个同时存在的上下文分别通过 256 像素读回，ES 3.1 计算着色器的 64 个输出也全部匹配。另一个纹理复制与滤镜程序分别得到与旧驱动相同的校验值 `291cd01a`、`6b357fba`。

### 初版 Mesa 24.3.4 测试卡安装

116.5 GiB 测试卡已写入带 GLES 3.1 能力声明的 vendor 镜像。全部 54,906,880 字节读回后，SHA-256 为 `559f62b87053de815acd2076c3bf7b172cef114938bea201cfcb0758ccab264b`，逻辑分区表也通过校验。写入范围仅为 vendor。

写卡后，用户确认掌机从关机状态开机，已进入 GammaOS 桌面。

这次冷启动后，SurfaceFlinger 报告 `Mali-G31 (Panfrost)` 和 `OpenGL ES 3.1 Mesa 24.3.4`，Trebuchet 桌面位于前台。系统直接从测试卡的 vendor 逻辑分区加载驱动，五个图形库的 SHA-256 均与构建产物一致。Android 包管理器报告 `reqGlEsVersion=0x30001`（OpenGL ES 3.1）。通过标准 EGL 接口分别请求 GLES 1、2、3 后，每个上下文的 256 个像素读回结果均符合预期，ES 3.1 计算着色器的 64 个结果也全部匹配。
