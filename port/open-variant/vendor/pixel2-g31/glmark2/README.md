# Pixel 2 的 glmark2 图形跑分

**GLMark2** 使用 F-Droid 发布的原版，适合比较同一台掌机在不同系统或 Mesa 版本下的表现。**glmark2 显示对照** 则在同一应用内切换安卓普通输出和本项目的 G31 旋转输出，游戏场景和 3D 渲染都交给 Mesa。两个应用可以同时安装。[F-Droid 原版](https://f-droid.org/en/packages/org.linaro.glmark2/) · [glmark2 上游源码](https://github.com/glmark2/glmark2/tree/2023.01)

## 在掌机上运行

- 打开 **GLMark2**，保留默认列表，按 **Run**。完整测试包含 33 项，跑完后可在结果末尾看到总分。
- 打开 **glmark2 显示对照**，按 **Run**，选择 **五项快测 · 普通显示** 或 **五项快测 · G31 显示**。快测依次运行顶点缓冲、线性纹理、Phong 着色、地形和折射，每项计时 6 秒。场景加载另需时间。
- 对照版的 **当前项目** 选项使用界面里的测试列表，适合逐项排查。两种显示方式使用相同的 RGBA8888 缓冲区、16 位深度和全屏尺寸。
- 测驱动更新时，沿用同一版 glmark2、相同设置和供电状态。先后各跑两次并记录测试顺序，可以看出同一版本自身的波动。

glmark2 尝试关闭垂直同步，分项 FPS 表示程序运行测试循环的速度，总分取各有效场景 FPS 的整数平均。安卓显示服务记录缓冲区实际呈现的时间。比较显示路径时，这两项指标分别反映绘制和上屏表现。[计分代码](https://github.com/glmark2/glmark2/blob/2023.01/src/main-loop.cpp) · [安卓交换设置](https://github.com/glmark2/glmark2/blob/2023.01/src/canvas-android.cpp)

原版 2023.01 会先创建 100×100 的临时画布并打印尺寸，稍后才从安卓获取实际宽高。此次原版的安卓显示缓冲区是 592×480、RGB565。对照版全屏运行，两种模式都在 640×480、RGBA8888 下绘制，并额外记录安卓回调报告的尺寸。[上游安卓初始化代码](https://github.com/glmark2/glmark2/blob/2023.01/src/android.cpp)

## Pixel 2 实测

这台 GKD Pixel 2 运行 GammaOS（Android 12，ARMv7），使用 Mali-G31、Mesa 22.3.7 Panfrost 和 400–520 MHz 按需调频。六轮正式采样均接 USB 供电。原版 33 项跑分两轮分别为 **220、224 分**，均值 **222 分**。其中地形两轮都是 10 FPS，折射都是 6 FPS。

全屏五项快测按 G31、普通、普通、G31 的顺序各跑两轮。下表的上屏帧率按两轮有效时长合并计算，包含中途切换场景的时间。

| 全屏显示方式 | 五项总分（两轮） | 实际上屏帧率 | 上屏帧间隔第 95 百分位 |
| --- | --- | ---: | ---: |
| 安卓普通输出 | 119、118 | 13.38 FPS | 99.89 毫秒 |
| G31 旋转输出 | 109、110 | 18.98 FPS | 99.87 毫秒 |

这组场景中，G31 输出的上屏帧率提高约 42%，两种输出较慢的那部分帧仍接近 100 毫秒。五项内部绘制分数在普通输出时更高。地形与折射在两种输出下分别为 11 和 10 FPS。原版 33 项与全屏五项的项目、尺寸和颜色格式各异，升级驱动前后应使用同一套测试比较。

## 在电脑上重复采样

解锁掌机并连上 USB 数据线后，`run-glmark2.py` 通过已授权的 USB 调试运行测试，并把总分、分项、运行日志和测试前后的温度与频率写入新的目录。下面两条命令在 Windows 和 Linux 上均可使用。用本机的 `adb.exe` 或 `adb` 路径替换 `ADB`，输出目录每轮取一个新名字。

```sh
python run-glmark2.py ADB default-1
python run-glmark2.py ADB display-g31-1 --activity org.linaro.glmark2.pixel2compare/org.linaro.glmark2.Glmark2Activity --quick --screen-times --expect-g31
```

测普通输出时，去掉 `--expect-g31` 并更换输出目录。`--screen-times` 采样当前 SurfaceView 的安卓实际呈现时间，去重并裁掉首尾各一秒，中间的场景切换计入统计。脚本会检查 G31 模式确实提交了图像。实际时间戳保存在 `screen-times.json`。

## 构建对照版

在 Linux 或 WSL 中准备 JDK 17、Android SDK Platform 36、Build Tools 36.0.0、本地安卓调试签名文件，以及按 PPSSPP 显示测试说明构建的 APK。脚本核对 F-Droid 原包与对应源码归档的 SHA-256，复用 ARMv7 跑分核心、自带的 136 个资源和 PPSSPP 测试版的 3 个驱动库。构建完成后逐项比对内容。对照版使用独立包名 `org.linaro.glmark2.pixel2compare`，适用于这套 Android 12 移植。[F-Droid 发行包与源码归档](https://f-droid.org/en/packages/org.linaro.glmark2/) · [PPSSPP 驱动构建说明](../ppsspp/README.md)

```sh
python3 build-compare.py glmark2-2023.01-fdroid.apk org.linaro.glmark2_2_src.tar.gz ppsspp-pixel2-g31-test.apk "$ANDROID_HOME" "$HOME/.android/debug.keystore" ./builds
```

输出路径由脚本打印。`quick.args` 为掌机菜单和电脑采样共用的五项快测配置。原版 APK 的 SHA-256 为 `45bb2451be0db777cb5e5ac1cadcc7a09333e59a0912d6536108d2b66857d6ae`。
