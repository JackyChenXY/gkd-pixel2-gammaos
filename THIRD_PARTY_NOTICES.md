# 上游项目与许可证

- Android 系统基于 [GammaOSDistribution](https://github.com/TheGammaSqueeze/GammaOSDistribution/tree/b2db9cfe308c8753e3385b8ab64bcb34c3177177)，沿用 LineageOS、AOSP 和 PHH Treble 的相应源码。Settings、frameworks/base 和 init 补丁保留涉及文件的上游许可；相关 [Apache 2.0 文本](LICENSES/Apache-2.0.txt)及上游 NOTICE 在 [LICENSES](LICENSES/)。
- 主显示通道和 RK817 电量修复适用于 [Rockchip Linux 5.10 BSP](https://github.com/bmdhacks/kernel_rk3562/tree/0c1ad27d20bb8d84a41cd8ac913829a7bd934329) 相应的 GPL 代码。见 [GPL 版本 2](LICENSES/GPL-2.0.txt)及各被修改文件的许可证标记。
- 仓库中的板级内核配置和设备树来自 [AURKNIX](https://github.com/AveyondFly/distribution_rocknix/tree/aadfbafc5273983b5e255d1dbe76634321739fe5)。保留设备树的 GPL-2.0-or-later 或 MIT 双许可证声明。5.10 基础配置来自 [AOSP kernel/configs](https://android.googlesource.com/kernel/configs/+/d5ae8157dad45978607876c426640dd85a32f41e) 的同一固定版本。
- 板级 Android 输入来自 [Rockchip SDK](https://github.com/TinkerBoard-Android/rockchip-android-manifest/tree/63216f0fbd65385b71cea3fb228c7cb2da28153d) 和本机板级文件。GammaOS 的 [Daijishō](https://github.com/TapiocaFox/Daijishou) 和 WebView 需分别从上游获取。启动固件、第三方应用、完整镜像和游戏文件均为仓库外的独立输入。

各第三方文件和上游项目继续适用各自的许可证。
