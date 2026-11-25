# Standard U-Boot bootstd script for the open Pixel 2 variant.
# bootstd supplies the selected device type, device number, and boot partition.
if test "${devtype}" != "mmc" || test "${distro_bootpart}" != "1"; then
    echo "Pixel 2: expected the first FAT partition on the boot card"
    exit
fi
setenv kernel_addr_r 0x02200000
setenv fdt_addr_r 0x01f00000
setenv ramdisk_addr_r 0x09000000

if load "${devtype}" "${devnum}:${distro_bootpart}" "${kernel_addr_r}" /Image &&
   load "${devtype}" "${devnum}:${distro_bootpart}" "${fdt_addr_r}" /pixel2.dtb &&
   load "${devtype}" "${devnum}:${distro_bootpart}" "${ramdisk_addr_r}" /initramfs.cpio.gz; then
    setenv ramdisk_size "${filesize}"
    setenv bootargs 'console=ttyFIQ0 firmware_class.path=/vendor/etc/firmware init=/init rootwait ro loop.max_part=7 androidboot.console=ttyFIQ0 androidboot.hardware=rk30board androidboot.boot_devices=ff370000.dwmmc androidboot.selinux=permissive buildvariant=userdebug console=tty0 consoleblank=0 fbcon=rotate:3 rdinit=/p2-init rockchipdrm.pixel2_primary_only=1 lsm=lockdown,yama,loadpin,safesetid,integrity,selinux,bpf'
    booti "${kernel_addr_r}" "${ramdisk_addr_r}:${ramdisk_size}" "${fdt_addr_r}"
fi
echo "Pixel 2: Android boot handoff failed"
