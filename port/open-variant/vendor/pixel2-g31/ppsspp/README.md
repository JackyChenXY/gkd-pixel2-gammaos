# PPSSPP 的 Pixel 2 显示测试版

这份测试版使用 PPSSPP 1.20.4 的 ARMv7 模拟核心。开启 G31 模式后，PPSSPP 将画好的游戏帧交给本机的二维驱动。驱动把 640×480 画面旋转到 480×640 的系统显示缓冲区。两种模式共用相同的 PPSSPP 图形设置和 Mesa GLES 游戏渲染器。

## 安装与切换

在开启 USB 调试的 Pixel 2 上安装本机构建的 APK。**PPSSPP G31** 打开新驱动，**PPSSPP Pixel 2 Test** 打开普通显示路径。两个入口共用游戏列表、设置和存档。切换前请先在 PPSSPP 中保存游戏并退出。包名为 `org.ppsspp.ppsspp.pixel2test`。测试环境是本项目的 GammaOS Android 12、ARMv7、minigbm 和 Mesa Panfrost 22.3.7。

```sh
adb -d install -r ppsspp-pixel2-g31-test.apk
```

打开测试版，选择存档位置，并通过「载入游戏」选取要运行的 ISO。应用通过安卓文件选择器获得这份游戏的读取权限。先保存游戏，再用以下命令启用 G31。停止操作会结束测试版当前运行的游戏。

```sh
adb -d shell am force-stop org.ppsspp.ppsspp.pixel2test
adb -d shell am start -n org.ppsspp.ppsspp.pixel2test/org.ppsspp.ppsspp.PpssppActivity --ez pixel2G31 true
```

把最后一个参数改为 `false` 可切回普通模式。首次通过 G31 提交成功时，以下日志含有 `Presented 1 game frames, errors=0`，之后每 600 帧记录一次。打开 GPU 或创建输出窗口失败会在日志中标明回退。

```sh
adb -d logcat -s Pixel2G31:I
```

## 从源码构建

准备 JDK 17、Android SDK Platform 36 基础版、Build Tools 36.0.0、已构建的 Pixel 2 Android 源码树以及上一级目录生成的两个 G31 动态库。准备 PPSSPP v1.20.4 源码仓库和该版本官方 Android APK。脚本会核验上游提交及 APK 的 SHA-256，在新目录内构建，并逐项比对官方 ARMv7 核心、C++ 运行库和模拟器自带的 190 个资源文件。

```sh
git clone --depth 1 --branch v1.20.4 https://github.com/hrydgard/ppsspp.git ppsspp-1.20.4
export ANDROID_HOME=/path/to/android-sdk
bash build-test.sh ./ppsspp-1.20.4 ./PPSSPP-1.20.4-Android.apk /path/to/built-pixel2-android /path/to/built-g31 ./builds
```

脚本最后打印 APK 路径和校验值。已有 Gradle 9.4.1 的环境可设置 `GRADLE_BIN` 指向它的可执行文件。[上游固定提交](https://github.com/hrydgard/ppsspp/tree/fa50bb1976065c4f8b1b47af227d367fe9771555) · [PPSSPP 官方下载](https://www.ppsspp.org/download/)

## 实机测量

从同一即时存档进入游戏，待启动和载入完成后在主机采样。此例将实际呈现时间、每秒呈现帧数和帧间隔保存到 JSON。采样器读取 SurfaceFlinger 为测试版游戏画面记录的显示时间。PPSSPP 自己的帧数和模拟速度可在图形设置内同时开启。

```sh
python3 measure.py /path/to/adb sample.json --seconds 25
```

### 《英雄传说 空之轨迹 FC》的序章

在 Pixel 2 实机上载入壁炉旁的人物对话存档，保持游戏画面持续运行。跳帧关闭，GPU 最低频率为 400 MHz，系统按负载调频。输出均为 640×480。分别测试 1 倍（480×272）与 2 倍（960×544）内部渲染分辨率。每档每种方式各两轮，每轮约 25 秒。1 倍按普通、G31、G31、普通排列，2 倍反向。表格汇总同组所有上屏帧间隔，慢帧指间隔超过 2.5 个屏幕刷新周期（约 41.6 毫秒）。

| 内部渲染 | 输出方式 | 上屏帧率 | 第 95 百分位帧间隔 | 慢帧 / 采样间隔 |
| --- | --- | ---: | ---: | ---: |
| 1 倍 | 普通 | 29.97 FPS | 49.96 ms | 268 / 1514（17.7%） |
| 1 倍 | G31 | 29.96 FPS | 49.93 ms | 253 / 1516（16.7%） |
| 2 倍 | 普通 | 29.11 FPS | 66.59 ms | 286 / 1471（19.4%） |
| 2 倍 | G31 | 29.98 FPS | 33.39 ms | 28 / 1512（1.9%） |

系统显示日志记录了 G31 模式的 480×640 输出缓冲区，游戏图层所需旋转变为 0°。普通模式显示的是 640×480 缓冲区和 270° 旋转。两个模式的游戏图层都经过安卓合成。1 倍截图中同一块 283×102 像素的静止背景完全一致，文字和布局方向一致。这些数据覆盖序章这一幕，战斗、其他游戏和电池续航还有待分别测量。

另用最终安装包的两个启动器入口测试剧情推进。每轮从同一即时存档开始，恢复后预热 9 秒，然后在 25 秒采样期间按相同节奏触发 7 次 PSP 的圆圈键。这样可以同时观察对话更替、角色和镜头移动时的表现。两个入口内的 5 个 ARMv7 库与静止对话测试包逐字节一致。

| 2 倍分辨率推进剧情 | 上屏帧率 | 第 95 百分位帧间隔 | 慢帧 / 采样间隔 |
| --- | ---: | ---: | ---: |
| 普通入口 | 27.89 FPS | 66.62 ms | 377 / 1407（26.8%） |
| G31 入口 | 29.88 FPS | 49.85 ms | 79 / 1498（5.3%） |

本目录的 Java 前端及 PPSSPP 构建整合采用 GPL-2.0-or-later。独立的 C 显示组件、其编译脚本和采样工具采用 Apache-2.0。各源码文件标有对应的 SPDX 标识。
