# Pixel 2 rc.2. The default kernel, DTB and initramfs are always available.
if test "${devtype}" != "mmc" || test "${distro_bootpart}" != "1"; then
    exit
fi
setenv kernel_addr_r 0x02200000
setenv fdt_addr_r 0x01f00000
setenv ramdisk_addr_r 0x09000000
setenv p2args 'console=ttyFIQ0 firmware_class.path=/vendor/etc/firmware init=/init rootwait ro loop.max_part=7 androidboot.console=ttyFIQ0 androidboot.hardware=rk30board androidboot.boot_devices=ff370000.dwmmc androidboot.selinux=permissive buildvariant=userdebug console=tty0 consoleblank=0 fbcon=rotate:3 rdinit=/p2-init rockchipdrm.pixel2_primary_only=1 lsm=lockdown,yama,loadpin,safesetid,integrity,selinux,bpf'
setenv p2alt
setenv p2mesa mesa
if test -e mmc "${devnum}:1" /MESA.TXT; then
    setenv p2mesa forced
elif part start mmc "${devnum}" misc p2base && part size mmc "${devnum}" misc p2len &&
     itest.l "${p2base}" == 4e000 && itest.l "${p2len}" == 2000 &&
     mmc dev "${devnum}" && mmc read 01800000 4e010 1 &&
     itest.l *01800000 == 32473250 && itest.l *01800004 == 00030201; then
    if itest.l *01800008 == 22 && itest.l *0180000c == ffffffdd; then
        setenv p2alt trial
        setenv p2next 24
        setenv p2inv ffffffdb
    elif itest.l *01800008 == 23 && itest.l *0180000c == ffffffdc; then
        setenv p2alt kept
        setenv p2next 25
        setenv p2inv ffffffda
    fi
fi
if test -n "${p2alt}"; then
    # Consume the request before the alternative kernel ever runs. A failed card write stays on Mesa.
    if mw.l 01800008 "${p2next}" 1 && mw.l 0180000c "${p2inv}" 1 &&
       mmc write 01800000 4e010 1 && mmc read 01800200 4e010 1 &&
       cmp.b 01800000 01800200 200 &&
       load mmc "${devnum}:1" "${kernel_addr_r}" /mali.img &&
       load mmc "${devnum}:1" "${fdt_addr_r}" /pixel2.dtb &&
       load mmc "${devnum}:1" "${ramdisk_addr_r}" /mali.gz; then
        setenv ramdisk_size "${filesize}"
        setenv bootargs "${p2args} androidboot.pixel2gpu=${p2alt}"
        booti "${kernel_addr_r}" "${ramdisk_addr_r}:${ramdisk_size}" "${fdt_addr_r}"
    fi
fi
if load mmc "${devnum}:1" "${kernel_addr_r}" /Image &&
   load mmc "${devnum}:1" "${fdt_addr_r}" /pixel2.dtb &&
   load mmc "${devnum}:1" "${ramdisk_addr_r}" /initramfs.cpio.gz; then
    setenv ramdisk_size "${filesize}"
    setenv bootargs "${p2args} androidboot.pixel2gpu=${p2mesa}"
    booti "${kernel_addr_r}" "${ramdisk_addr_r}:${ramdisk_size}" "${fdt_addr_r}"
fi
echo "Pixel 2: Mesa boot files could not be loaded"
