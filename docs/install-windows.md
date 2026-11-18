# Windows 图形化刷卡

拿到为你的 GKD Pixel 2 和备用 TF 卡准备的完整镜像后，可以全程用 Windows 刷卡，无需安装 Linux 或 WSL。

## 准备完整镜像

请让提供镜像的人按[离线组装指南](install.md)生成 `pixel2-gammaos.img`。组装时需使用与你的掌机匹配的原装启动文件和面板设备树，以及**备用卡的实际字节数**。同样标为 64 GB 的卡，实际字节数也可能不同。可在 Windows PowerShell 运行下面的只读命令，记录备用卡对应的 `Size` 值：

```powershell
Get-Disk | Select-Object Number, FriendlyName, BusType, Size
```

[当前 Release](https://github.com/JackyChenXY/gkd-pixel2-gammaos/releases)里的 `P2BFX.IMG` 是内核。Etcher 需要的是组装完成的整卡镜像 `pixel2-gammaos.img`。如果镜像提供者附有 SHA-256，请先核对。

## 用 Etcher 写入备用卡

写入会清空目标卡。先拔掉原装卡，再插入确认可清空的备用卡。

1. 打开 [balenaEtcher](https://etcher.balena.io/)，点 **Flash from file**，选择 `pixel2-gammaos.img`。
2. 点 **Select target**，核对读卡器和备用卡容量，选中那张卡。
3. 点 **Flash!**，等待写入和校验完成。若 Windows 弹出格式化提示，点「取消」。
4. 安全弹出备用卡，插进掌机开机，给首次启动约三分钟。进入桌面后正常重启一次，并按[验证记录](validation.md)检查显示、按键和电量。

如需恢复原系统，先把掌机关机，再换回原装 TF 卡。
