# Mesa 和 Mali 图形驱动

Windows 安装助手会把 Mesa 和匹配的 Rockchip/Arm Mali-G31 用户态驱动放进同一张卡的镜像。刷好后可以离线切换，首次开机默认使用 Mesa。[下载 Windows 安装助手](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/latest/download/Pixel2-Setup.exe)

## 试用 Mali

1. 保存当前游戏，进入 **设置 → 系统 → 图形驱动**。双驱动整卡会显示「已校验 Mali 驱动，可以试用」。
2. 选择 **重启试用 Mali**。启动到桌面后，确认画面、按键和游戏运行正常，再回到这页点 **保留 Mali**。
3. 要返回 Mesa，点 **重启回到 Mesa**。两种模式使用同一份应用、设置和游戏存档。

试用时若黑屏，将掌机完全关机后再开机，会回到 Mesa。需要强制恢复时，在电脑可见的启动分区根目录新建空文件 `MESA.TXT`，再将卡插回掌机开机。进入设置将 Mesa 设为默认后，可以删除该文件。

## 驱动来源

公开整卡随附 Mesa 和 Mali 对应的内核。安装助手在用户电脑上，直接从固定的上游提交取得 Android ARM32 Mali 主库及两个启动配置，配合八个公开配套文件。全部 11 项、驱动分区和生成的整卡都必须通过 SHA-256 校验。这个固定版本的 SDK 主库未附可核实的镜像再分发授权，因此 GitHub 提供公开基础镜像、安装助手和配套组件。[上游主库与固定版本](https://github.com/TinkerBoard-Android/rockchip-android-vendor-rockchip-common/tree/5aeb28df3d0275ccd579ef99e3c164dabde744e9/gpu/MaliTDVx) · [11 项校验清单](../port/gpu-selector/reference.json) · [配套组件和声明](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases/download/v0.3.0/Pixel2-Mali-Support.zip)

已刷公开 Mesa 版且有匹配驱动 ZIP 的用户，可将 `Pixel2-Mali.local.zip` 复制到掌机的「下载」，在图形驱动设置中点「导入本地驱动」，然后重启试用。该 ZIP 为 28,716,111 字节，SHA-256 为 `9bb7a89a1d6875df1c1a25c74baed814f5b959099883c8beb5204dec5bbdc686`。使用 Windows 助手刷出的双驱动镜像可以直接从第一步试用。

系统同时选择对应的内核、EGL、图形缓冲分配和显示合成服务。针对吉里吉里 OpenGL 的 Mesa 修正仅在 Mesa 模式生效。[当前测试范围](validation.md)
