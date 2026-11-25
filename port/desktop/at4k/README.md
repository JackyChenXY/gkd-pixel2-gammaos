# AT4K 与 H700 系统壁纸

Windows 助手使用 H700Android 提交 `a8f95e13a91b7f8bd40f2fcb2bc246e3d1c13dc5` 的原签名 AT4K 1.2。APK 的包名是 `com.overdevs.at4k`，SHA-256 为 `b2fa0343e903ad01c3854999dba70335ba4df5f5522dd931ed9d7189cf841a7d`。系统壁纸来自 APK 内的 `res/raw/rgsp_wallpaper.jpg`，SHA-256 为 `0d99ad08346620e240fa6eb7e765bb55996d4a311c8141a209626e08cad88997`。[固定上游](https://github.com/LPF970915/H700Android/tree/a8f95e13a91b7f8bd40f2fcb2bc246e3d1c13dc5/tools/at4k)

双驱动镜像在此前空置的 recovery 分区存放只读 OEM 文件系统。安卓在扫描应用前将它挂到 `/oem`，原签名应用位于 `/oem/app/AT4K`，并使用 ARM32 原生库。`/oem/etc/preferred-apps/at4k-home.xml` 提供新用户的首选主屏，`ro.config.wallpaper` 指定系统默认壁纸。后续自行更换桌面或壁纸时沿用安卓的用户设置。两种驱动共用这些文件，最近任务由原有 Quickstep 提供。

## 从 v0.3.0 构建

在 Linux 的普通文件目录中执行以下命令。准备 v0.3.0 系统分区、公开基础镜像、已整合双驱动的 v0.3.0 镜像、用于系统签名的同版 GammaOS 构建树，以及从上游取得的指定 APK。输出需使用新文件名。

```bash
python3 build-oem.py --apk "$AT4K" --empty "$WORK/oem-empty.img" \
  --full "$WORK/oem-full.img" --map "$WORK/oem.json"
cp "$WORK/oem.json" ../../gpu-selector/backend/card/oem.json
python3 build-system.py --baseline "$OLD_SYSTEM" --gamma "$GAMMA" --output "$WORK/system.img"
python3 build-card.py --kind public --base "$OLD_PUBLIC_GZ" --oem "$WORK/oem-empty.img" \
  --system "$WORK/system.img" --output "$WORK/public.img"
python3 build-card.py --kind desktop --base "$OLD_DUAL_IMG" --oem "$WORK/oem-full.img" \
  --system "$WORK/system.img" --output "$WORK/desktop.img"
```

基础镜像的 OEM 文件占位区为零，安卓只会扫描个人镜像上已激活的应用目录。制作新的发布版时，用该次构建得到的区段清单、压缩镜像和整卡校验值编译 Windows 助手。助手在用户电脑上补入 APK、壁纸和原生库，并在输出前核对整卡。生成的个人镜像可以直接用 Raspberry Pi Imager 刷入 TF 卡。
