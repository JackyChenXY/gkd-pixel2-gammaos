#!/usr/bin/env python3
"""Exercise the shipping service on a private QEMU test fixture (no emulated Mali-G31)."""
import argparse,importlib.util,os,re,subprocess,tempfile,time
from pathlib import Path
here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("policy",here/"boot-policy.py")
policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
p=argparse.ArgumentParser(description=__doc__)
for n in ("disk","kernel","logs"):p.add_argument("--"+n,type=Path,required=True)
p.add_argument("steps",nargs="*");a=p.parse_args()
steps={"seed":"mesa","unconfirmed":"trial","fallback":"mesa","confirm":"trial","persistent":"kept","return":"mesa"}
default_steps=list(steps)
steps["preloaded"]="mesa"
if not a.disk.is_file() or a.disk.is_symlink() or a.disk.stat().st_size!=7516192768:p.error("Use the private regular test disk")
a.logs.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(dir=a.logs) as d:
    t=Path(d);fat=str(a.disk)+"@@16777216"
    for name in ("initramfs.cpio.gz","mali.gz"):subprocess.run(["mcopy","-i",fat,"::/"+name,t/name],check=True)
    for step in a.steps or default_steps:
        mode=policy.select(a.disk)
        if steps[step]!=mode:raise ValueError("Boot script returned "+mode+" at "+step)
        serial=a.logs/(step+".log");err=a.logs/(step+"-qemu.log")
        if serial.exists() or err.exists():raise ValueError("Use fresh logs")
        args=["qemu-system-aarch64","-machine","virt,gic-version=2","-cpu","cortex-a53","-smp","4","-m","1024","-display","none","-nic","none","-no-reboot","-monitor","none","-serial","file:"+str(serial),
              "-kernel",str(a.kernel),"-initrd",str(t/("initramfs.cpio.gz" if mode=="mesa" else "mali.gz")),
              "-append","console=ttyAMA0 loglevel=7 initcall_blacklist=rockchip_drm_init,system_heap_create rdinit=/p2-init init=/init rootwait ro loop.max_part=7 firmware_class.path=/vendor/etc/firmware androidboot.hardware=rk30board androidboot.boot_devices=a000000.virtio_mmio androidboot.selinux=permissive buildvariant=userdebug lsm=lockdown,yama,loadpin,integrity,selinux,bpf androidboot.pixel2gpu="+mode+" androidboot.pixel2test="+step,
              "-drive","if=none,id=card,format=raw,file="+str(a.disk)+",cache=writeback,discard=unmap,detect-zeroes=unmap","-device","virtio-blk-device,drive=card,bus=virtio-mmio-bus.0"]
        with err.open("xb") as stream:
            proc=subprocess.Popen(args,stdout=stream,stderr=stream)
            try:
                deadline=time.monotonic()+230
                while time.monotonic()<deadline:
                    s=serial.read_text(errors="replace") if serial.exists() else ""
                    if "P2_GPUTEST FAIL" in s:raise RuntimeError(s[s.index("P2_GPUTEST FAIL"):].splitlines()[0])
                    if "P2_GPUTEST PASS "+step in s:
                        print(step,mode,"PASS",flush=True);break
                    if proc.poll() is not None:raise OSError("QEMU exited; see "+str(err))
                    time.sleep(1)
                else:raise TimeoutError(str(serial))
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=6)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
