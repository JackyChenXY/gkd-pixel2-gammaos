# 官方版吉里吉里 1.4.4 · Pixel 2 OpenGL

[适用 UID、APK 版本、基线及实机结果](../../../docs/components.md#官方吉里吉里-opengl-兼容修复) · [下载驱动包](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/tag/v0.3.0)

- `android/` 是系统集成源码和设备检查。用与参考固件相匹配的 Rockchip Android 12 源码树设置 `PIXEL2_AOSP`，从该目录运行 `bash build.sh`；Java 代码依赖完整平台构建产物。编译和集成分别进行。系统只在相应机型、分区布局、库和应用身份全部匹配时启用这条路径。
- `mesa/` 提供完整纹理资源修改及像素正确性测试。先按 [系统 GPU 构建步骤](../vendor/pixel2-system-gpu/) 生成 Pixel 2 ES100 基线，然后将 `mesa24.3.4-panfrost-survival.patch` 应用到刚编译的 `mesa-24.3.4` 源码目录，再在原 `mesa-build` 目录下用 Ninja 重编。运行时把单独编译的库作为 `libpixel2_krkr_v7.so` 安装到清单列出的准确位置。[资源分配策略与参考散列](mesa/README.txt)
- `game-profile.xml` 记录实测使用的 OpenGL、纹理压缩和最大纹理尺寸。`experimental/` 保留早期模拟器源码实验。当前实机安装使用上游官方 APK。
- `build-system.py` 从已校验哈希的本地基线及 `manifest.json` 组装新镜像，`reference-build.json` 给出已在掌机上使用的构建记录。压缩包附有匹配的已编译组件和离线命令。在不同时间组装时，文件系统元数据时间可能改变整分区哈希，内容和标签由组装器逐项校验。
