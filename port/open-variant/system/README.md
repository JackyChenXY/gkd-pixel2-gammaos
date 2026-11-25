# GammaOS 桌面试验镜像

这一步从已经编译过的 Pixel 2 GammaOS 构建输出重新打包 `system.img`。脚本使用同一 Android 构建的打包工具、SELinux 文件标签和根目录模板，在新目录生成 ext4 和 AVB 测试签名。原构建目录是只读输入。先按[构建指南](../../../docs/build.md)完成固定版本的 Pixel 2 Android 12 构建。

```bash
bash port/open-variant/system/build-desktop-probe.sh "$GAMMA_SOURCE" "$HOME/pixel2-system-probe"
```

目标目录应尚不存在。脚本默认读取 `$GAMMA_SOURCE/out-pixel2-gamma`，也可通过 `GAMMA_BUILD_OUT` 指定本机的独立构建目录。输出包含 `system.img`、`SHA256SUMS` 和验证日志。镜像是 `system` 单分区，适合与同一试验版的板级分区、内核和引导配合测试。

## 作为桌面试验的改动

- 省去 Daijishō、预编译 WebView 及依赖 WebView 的 Jelly 浏览器。Trebuchet 继续提供 Android HOME 入口。第三方应用内的网页功能也可能受影响。
- 保留 Pixel 2 手柄键位、交换程序、ZRAM 配置、SELinux 执行标签及 Android 许可声明。以 `ro.pixel2.open_system_probe=true` 标记试验系统，并把编译账号和主机名改为通用值。
- 在新镜像中重新验证 ext4、AVB 测试签名、桌面 HOME 声明、手柄键位、交换文件的字节内容和 `/product`、`/system_ext` 的链接。

## 组件来源和发布检查

- 原预装 WebView 来自 LineageOS 的 Chromium 构建。其构建配置含编解码选项，试验镜像省去了该 APK。若后续加入 WebView，需要核对所选构建的源代码对应关系与许可声明。 [LineageOS ARM WebView 源版本](https://github.com/LineageOS/android_external_chromium-webview_prebuilt_arm/tree/6d883cfe7f5f50470b29b21c26aa204205186a1a) · [Chromium 编解码配置](https://www.chromium.org/audio-video/)
- 原构建的 ART 和软件媒体编解码 APEX 可追溯到其 AOSP 编译中间产物。镜像仍保留这些组件和现有 `/system/etc/NOTICE.xml.gz`。公开镜像前需要对随镜像分发的二进制补齐对应的许可、源码和附带声明，尤其是静态链接到系统交换助手的运行库。
- 板级引导和 Android `vendor` 依赖由其他分区提供。桌面启动、读写加密数据的重启测试和实际游戏性能仍要在备用卡上验证。
