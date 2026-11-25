#!/usr/bin/env python3
"""Add the OEM mount and default wallpaper to a verified GammaOS v0.3.0 system."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile
from zipfile import ZipFile

BASE_SHA = "722647bc0ded58548435645c8d2cf740f0b712116a8871cd0d74719f37887560"
APEX = "/system/apex/com.android.permission.capex"
SETTINGS_APK = "/system/priv-app/SettingsProvider/SettingsProvider.apk"
OLD_SETTINGS_SHA = "e46d6a937def66e490b46b904337be16c3fbbe3287364bec06e2358ae5967b78"
PAD_SERVICE = b"org.gkdpixel2.padnavigation/org.gkdpixel2.padnavigation.PadNavigationService"
OLD_APEX_SHA = "4a7ee7e27b68d5bf83014709c51bfe79cf73c7dcb7b7418a7b6c7afd5def9ffd"
HERE = Path(__file__).resolve().parent
WALL = b"ro.config.wallpaper=/oem/app/AT4K/H700-wallpaper.jpg\n"

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(4 << 20), b""):
            h.update(buf)
    return h.hexdigest()

def verify_signer(gamma, env, package, certificate):
    expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(certificate.read_text())).hexdigest()
    signer = gamma / "prebuilts/sdk/tools/linux/lib/apksigner.jar"
    java = gamma / "prebuilts/jdk/jdk11/linux-x86/bin/java"
    certs = subprocess.check_output(
        [java, "-jar", signer, "verify", "--min-sdk-version", "30", "--print-certs", package],
        env=env, text=True)
    if f"Signer #1 certificate SHA-256 digest: {expected}" not in certs.splitlines():
        raise ValueError("Incorrect signing certificate for " + package.name)

def has_compiled_strings(apk, values):
    with ZipFile(apk) as app:
        for entry in app.namelist():
            if re.fullmatch(r"classes[0-9]*\.dex", entry):
                dex = app.read(entry)
                if all(value in dex for value in values):
                    return True
    return False

def navigation_settings(gamma, env):
    product = gamma / "out-pixel2-gamma/target/product/phhgsi_a64_ab"
    apk = product / SETTINGS_APK.removeprefix("/")
    verify_signer(gamma, env, apk, gamma / "build/make/target/product/security/platform.x509.pem")
    if not has_compiled_strings(apk, [b"ro.pixel2.handheld_navigation", PAD_SERVICE]):
        raise ValueError("Rebuild SettingsProvider with pixel2-navigation-defaults.patch first")
    return apk.read_bytes()

def checked_role_module(gamma, temp, env):
    """Verify the board's original module keys and the compiled HOME fallback."""
    apex_dir = gamma / "packages/modules/Permission"
    module = gamma / "out-pixel2-gamma/target/product/phhgsi_a64_ab" / APEX.removeprefix("/")
    if digest(module) == OLD_APEX_SHA:
        raise ValueError("Rebuild com.android.permission with pixel2-home-role.patch first")
    public_key = (apex_dir / "com.android.permission.avbpubkey").read_bytes()
    apex = temp / "permission.apex"
    payload = temp / "permission-payload.img"
    apk = temp / "PermissionController.apk"
    with ZipFile(module) as outer:
        if outer.read("apex_pubkey") != public_key:
            raise ValueError("Unexpected compressed APEX public key")
        apex.write_bytes(outer.read("original_apex"))
    for signed in (module, apex):
        verify_signer(gamma, env, signed, apex_dir / "com.android.permission.x509.pem")
    with ZipFile(apex) as inner:
        if inner.read("apex_pubkey") != public_key:
            raise ValueError("Unexpected APEX payload public key")
        payload.write_bytes(inner.read("apex_payload.img"))
    subprocess.run(["avbtool", "verify_image", "--image", payload, "--key",
                    apex_dir / "com.android.permission.pem"], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["debugfs", "-R", "dump /priv-app/PermissionController/PermissionController.apk " + str(apk),
                    payload], env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if has_compiled_strings(apk, [b"HomeRoleBehavior;", b"com.overdevs.at4k", b"/oem/app/AT4K/AT4K.apk"]):
        return module.read_bytes()
    raise ValueError("The compiled HOME role is missing the OEM desktop fallback")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","gamma","output"):
        p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    if os.path.lexists(a.output) or not a.baseline.is_file() or digest(a.baseline)!=BASE_SHA:
        p.error("Expected the released v0.3.0 system and a new output name")
    host=a.gamma/"out-pixel2-gamma/host/linux-x86/bin"
    key=a.gamma/"external/avb/test/data/testkey_rsa2048.pem"
    env={**os.environ,"LC_ALL":"C","PATH":str(host)+":"+os.environ["PATH"]}
    def avb(*args):
        return subprocess.check_output([host/"avbtool",*args],env=env,text=True)
    info=avb("info_image","--image",a.baseline)
    def field(name):
        return re.search(r"(?m)^\s*"+name+r":\s*(\S+)",info)[1]
    props=[]
    for name,v in re.findall(r"(?m)^\s*Prop: (.*?) -> '(.*?)'$",info):
        props.extend(["--prop",name+":"+v])
    with tempfile.TemporaryDirectory(dir=a.output.parent) as td:
        temp=Path(td); fs=temp/"system.img"; shutil.copyfile(a.baseline,fs)
        avb("verify_image","--image",fs,"--key",key)
        avb("erase_footer","--image",fs)
        def read(cmd):
            return subprocess.check_output(["debugfs","-R",cmd,fs],stderr=subprocess.DEVNULL)
        prop="/system/build.prop"
        marker="/system/etc/pixel2-release"
        rc="/system/etc/init/pixel2-oem.rc"
        original=read("cat "+prop)
        if not original or b"\nro.config.wallpaper=" in original or read("cat "+marker)!=b"GKD Pixel 2 community TF image 0.3.0\n" or read("stat "+rc):
            raise ValueError("Unexpected factory system")
        navbar = b"persist.sys.phh.mainkeys=0\n"
        if original.count(navbar) != 1 or b"ro.pixel2.handheld_navigation=" in original:
            raise ValueError("Unexpected navigation bar properties")
        handheld_props = original.replace(navbar, b"persist.sys.phh.mainkeys=1\n").rstrip(b"\n")
        handheld_props += b"\nro.pixel2.handheld_navigation=1\n" + WALL
        if hashlib.sha256(read("cat "+APEX)).hexdigest() != OLD_APEX_SHA:
            raise ValueError("Unexpected factory role module")
        if hashlib.sha256(read("cat "+SETTINGS_APK)).hexdigest() != OLD_SETTINGS_SHA:
            raise ValueError("Unexpected factory SettingsProvider")
        installed = {
            "/system/product/app/Pixel2PadNavigation/Pixel2PadNavigation.apk":
                "258fd01670dec837f4a886673e1d1479bfd46ed78e55fbf0036b2fb6bb8b9231",
            "/system/product/app/Pixel2PadNavigation/lib/arm/libpadchord.so":
                "288c24438bea5e2058da89cdb639f27cf3fcde892675b5876eb63d8a795e9ef9",
            "/system/system_ext/priv-app/TrebuchetQuickStep/TrebuchetQuickStep.apk":
                "91cecd339ed8a510af92e5d2af38a669525ac659fed3433d8be0004361b4b69a",
        }
        for name, expected in installed.items():
            if hashlib.sha256(read("cat " + name)).hexdigest() != expected:
                raise ValueError("Unexpected preinstalled controller or overview: " + name)
        entries = {
            prop: handheld_props, marker: b"GKD Pixel 2 community TF image 0.3.1\n",
            rc: (HERE / "pixel2-oem.rc").read_bytes(),
            APEX: checked_role_module(a.gamma, temp, env),
            SETTINGS_APK: navigation_settings(a.gamma, env),
        }
        label=temp/"context";label.write_bytes(b"u:object_r:system_file:s0\x00")
        cmds=[]
        for i,(dst,data) in enumerate(entries.items()):
            src=temp/str(i);src.write_bytes(data)
            if dst in (prop,marker,APEX,SETTINGS_APK):cmds.append("rm "+dst)
            cmds += ["write "+str(src)+" "+dst,"set_inode_field "+dst+" mode 0100644",
                     "set_inode_field "+dst+" uid 0","set_inode_field "+dst+" gid 0",
                     "ea_set -f "+str(label)+" "+dst+" security.selinux"]
        subprocess.run(["debugfs","-w","-f","-",fs],input="\n".join(cmds)+"\n",text=True,check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for dst,data in entries.items():
            if read("cat "+dst)!=data or b"u:object_r:system_file:s0" not in read("ea_list "+dst):
                raise ValueError("Incorrect content or SELinux label: "+dst)
        subprocess.run(["e2fsck","-fn",fs],check=True,stdout=subprocess.DEVNULL)
        avb("add_hashtree_footer","--image",fs,"--partition_name","system","--partition_size",str(a.baseline.stat().st_size),
            "--algorithm",field("Algorithm"),"--hash_algorithm",field("Hash Algorithm"),"--key",key,
            "--rollback_index",field("Rollback Index"),"--salt",field("Salt"),*props)
        avb("verify_image","--image",fs,"--key",key)
        os.link(fs,a.output)
        print("Verified signed system:",digest(a.output),flush=True)

if __name__=="__main__":
    main()
