# 验证记录

| 功能 | 验证结果 |
| --- | --- |
| GammaOS 独立启动 | GKD Pixel 2 实机连续两次进入桌面，使用仅有一套 Android 系统的备用 TF 卡 |
| 冷启动显示 | 实机确认开机可直接看到可读画面，无需休眠再唤醒 |
| 手柄鼠标 | 实机确认长按 Select 可反复打开和隐藏光标。退出后十字键恢复菜单导航 |
| 电量 | 实机确认电池百分比恢复为合理的读数 |
| 额外交换空间 | 实机开启后重启，`/proc/swaps` 同时报告 489,736 KiB ZRAM 和 2,097,148 KiB TF 卡交换空间 |
| 关闭交换空间 | 虚拟机验证关闭并重启后释放文件空间，以及开启时正常卸载数据分区 |

## 复核

设备启动完成、解锁并授权 USB 调试后，可从电脑检查：

```bash
adb shell getprop sys.boot_completed
adb shell getprop ro.lineage.version
adb shell getprop ro.gsid.image_running
adb shell getprop ro.crypto.metadata.enabled
adb shell cat /proc/swaps
adb shell cat /proc/meminfo
```

完成独立启动时，`sys.boot_completed` 应为 `1`，`ro.gsid.image_running` 应为 `0`。`MemTotal` 表示内核可用物理内存，`SwapTotal` 表示交换空间总量。两种交换设备可用 `/proc/swaps` 分辨。对离线的 `system.img` 可运行 `e2fsck -fn`，对打包后的 `super.raw.img` 可用 `lpdump --slot=0` 和 `lpdump --slot=1` 核对两个逻辑分区表。

参考构建的 `super.raw.img` 大小为 **2,516,582,400 字节**，SHA-256 为 `083b00726a8dc40662edde84c45fd7b5de57e7765ea3e9f5d8595deb1ea6422b`。

## 已知限制

- 当前为 `userdebug/test-keys` 构建，Android 安全补丁日期为 `2023-11-05`。SELinux 使用 permissive，尚未建立完整的 AVB 强制验证链。USB 调试使用设备端授权。
- 交换文件位于启用元数据加密的 F2FS 数据卷中。开启后会占用 TF 卡空间，尚未对不同卡速和模拟器负载做性能基准测试。
- 实机验证基于一台 GKD Pixel 2。不同屏幕批次和存储卡的兼容性待验证。
