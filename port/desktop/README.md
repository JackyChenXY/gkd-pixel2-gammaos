# Pixel 2 桌面组件

[下载、适用系统和手柄操作](../../docs/components.md)

## Trebuchet / Quickstep

从本项目的 [GammaOS 源码版本](../../docs/build.md) 开始。在完整 Android 源码根目录按此顺序应用四个补丁。先设置 `PORT` 为本移植仓库的绝对路径：

```sh
for name in app-sync overview-pad at4k-recents recents-memory; do
    patch --batch --fuzz=0 -p1 < "$PORT/port/desktop/trebuchet/trebuchet-$name.patch" || exit 1
done
```

按固件原有的 lunch 配置执行 `m TrebuchetQuickStep` 并使用该系统原有签名。要独立检查内存数字的解析规则，可在完成补丁后执行：

```sh
classes=$(mktemp -d)
javac -d "$classes" packages/apps/Trebuchet/quickstep/src/com/android/quickstep/views/OverviewMemoryStats.java "$PORT/port/desktop/trebuchet/tests/CheckMemoryCounters.java"
java -cp "$classes" com.android.quickstep.views.CheckMemoryCounters
```

## 全局手柄导航

`pad-navigation` 包含 Android 无障碍服务、菜单、简体中文和英文资源，以及处理组合按键的原生库。在 Android 12 源码树的产品目录加入此模块，用 `m Pixel2PadNavigation` 构建 ARM32 APK。在设置中启用服务后才会收到过滤按键事件。原生输入层匹配的是 Pixel 2 内置手柄。

## 可选游戏前端

`pegasus-theme` 包含适配 640 × 480 屏幕和手柄的 Pegasus 主题，目录内保留上游作者的署名、许可证和移植说明。[H700Android](https://github.com/LPF970915/H700Android) 提供 AT4K 主屏和原壁纸。
