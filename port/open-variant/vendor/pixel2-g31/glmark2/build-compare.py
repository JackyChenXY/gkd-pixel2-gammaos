#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Pixel 2 comparison frontend for the F-Droid glmark2 2023.01 engine."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
import zipfile

PACKAGE = "org.linaro.glmark2.pixel2compare"
ORIGINAL = "org.linaro.glmark2"
APK_HASH = "45bb2451be0db777cb5e5ac1cadcc7a09333e59a0912d6536108d2b66857d6ae"
SOURCE_HASH = "b3a9498482debc4e7edadd6f7e0eb62796cef37babd4a0e42e3eb1a3df26ef16"
DRIVER_LIBS = ("libpixel2_g31.so", "libpixel2_g31_android.so", "libpixel2_ppsspp.so")
HERE = Path(__file__).resolve().parent


def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"Unexpected upstream contents in {path.name}: {old}")
    path.write_text(text.replace(old, new))


def verify(path, digest):
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"Incorrect glmark2 2023.01 input: {path}")


def extract_sources(archive, work):
    with tarfile.open(archive) as bundle:
        for item in bundle:
            parts = Path(item.name).parts
            if not item.isfile() or len(parts) < 3 or parts[1] != "android":
                continue
            relative = Path(*parts[2:])
            if relative.parts[0] not in ("src", "res", "AndroidManifest.xml"):
                continue
            if ".." in relative.parts or relative.is_absolute():
                raise ValueError(item.name)
            dest = work / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(item) as source, dest.open("wb") as output:
                shutil.copyfileobj(source, output)


def prepare_frontend(work):
    java = work / "src/org/linaro/glmark2"
    replace(java/"Glmark2SurfaceView.java", "setEGLConfigChooser(getConfigChooser());",
            "org.ppsspp.ppsspp.Glmark2Output.configure(this, activity);")
    replace(java/"Glmark2SurfaceView.java", "Glmark2Native.resize(width, height);",
            'Log.i("GLMark2", "Active render surface " + width + "x" + height);\n        Glmark2Native.resize(width, height);')
    replace(java/"Glmark2Activity.java", "mGLView = new Glmark2SurfaceView(this);",
            """getWindow().getDecorView().setSystemUiVisibility(
                android.view.View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                android.view.View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | android.view.View.SYSTEM_UI_FLAG_FULLSCREEN);
        mGLView = new Glmark2SurfaceView(this);""")
    replace(java/"MainActivity.java", '''if (prefs.getBoolean("show_results", true))
                    startActivityForResult(intent, ACTIVITY_GLMARK2_REQUEST_CODE);
                else
                    startActivity(intent);''', '''new AlertDialog.Builder(MainActivity.this)
                    .setTitle("选择跑分方式")
                    .setItems(new String[] {"五项快测 · 普通显示", "五项快测 · G31 显示",
                                            "当前项目 · 普通显示", "当前项目 · G31 显示"}, new DialogInterface.OnClickListener() {
                        @Override public void onClick(DialogInterface dialog, int mode) {
                            intent.putExtra("pixel2G31", mode == 1 || mode == 3);
                            if (mode < 2) intent.putExtra("args", QUICK_PROFILE_FROM_SOURCE);
                            if (prefs.getBoolean("show_results", true))
                                startActivityForResult(intent, ACTIVITY_GLMARK2_REQUEST_CODE);
                            else
                                startActivity(intent);
                        }
                    }).show();''')
    replace(java/"MainActivity.java", "QUICK_PROFILE_FROM_SOURCE", json.dumps((HERE/"quick.args").read_text().strip()))
    replace(work/"res/values/strings.xml", 'name="title_activity_main">GLMark2<',
            'name="title_activity_main">glmark2 显示对照<')
    manifest = work/"AndroidManifest.xml"
    xml = ET.parse(manifest)
    android_ns = "http://schemas.android.com/apk/res/android"
    ET.register_namespace("android", android_ns)
    attr = "{" + android_ns + "}"
    root = xml.getroot()
    for declaration in root.findall("uses-sdk"):
        root.remove(declaration)
    root.insert(0, ET.Element("uses-sdk", {attr+"minSdkVersion":"31", attr+"targetSdkVersion":"32"}))
    app = root.find("application")
    app.set(attr+"label", "@string/title_activity_main")
    for activity in app.findall("activity"):
        exported = activity.get(attr+"name") in (ORIGINAL+".MainActivity", ORIGINAL+".Glmark2Activity")
        activity.set(attr+"exported", str(exported).lower())
    xml.write(manifest, encoding="utf-8", xml_declaration=True)
    bridge = work / "src/org/ppsspp/ppsspp"
    bridge.mkdir(parents=True)
    shutil.copyfile(HERE.parent/"ppsspp/Pixel2Presentation.java", bridge/"Pixel2Presentation.java")
    (bridge/"Glmark2Output.java").write_text("""package org.ppsspp.ppsspp;

import android.app.Activity;
import android.opengl.GLSurfaceView;

public final class Glmark2Output {
    private Glmark2Output() {}

    public static void configure(GLSurfaceView view, Activity activity) {
        Pixel2Presentation.configure(view, activity);
    }
}
""")


def build(args):
    verify(args.official_apk, APK_HASH)
    verify(args.source_tar, SOURCE_HASH)
    sdk = args.sdk.resolve()
    platform = sdk/"platforms/android-36/android.jar"
    tools = sdk/"build-tools/36.0.0"
    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="glmark2-build-", dir=args.out)).resolve()
    extract_sources(args.source_tar, work)
    prepare_frontend(work)

    def call(*cmd):
        subprocess.run([str(arg) for arg in cmd], cwd=work, check=True)

    java = Path(os.environ["JAVA_HOME"])/"bin"
    generated = work/"generated"
    generated.mkdir()
    call(tools/"aapt2","compile","--dir",work/"res","-o","resources.zip")
    call(tools/"aapt2","link","-I",platform,"--manifest","AndroidManifest.xml","--java",generated,
         "--rename-manifest-package",PACKAGE,
         "-o","package.apk","resources.zip")
    classes = work/"classes"
    classes.mkdir()
    call(java/"javac","-encoding","UTF-8","-source","8","-target","8","-bootclasspath",platform,
         "-d",classes,*sorted((work/"src").rglob("*.java")),*sorted(generated.rglob("*.java")))
    call(java/"jar","cf","classes.jar","-C",classes,".")
    dex = work/"dex"
    dex.mkdir()
    call(tools/"d8","--min-api","31","--lib",platform,"--output",dex,"classes.jar")
    abi = "lib/armeabi-v7a/"
    with zipfile.ZipFile(args.official_apk) as original, zipfile.ZipFile(args.driver_apk) as driver, \
            zipfile.ZipFile(work/"package.apk","a") as out:
        original_entries = [ent for ent in original.infolist() if not ent.is_dir() and
                            (ent.filename.startswith("assets/") or ent.filename == abi+"libglmark2-android.so")]
        for item in original_entries:
            out.writestr(item.filename, original.read(item), compress_type=item.compress_type)
        for name in DRIVER_LIBS:
            out.writestr(abi+name, driver.read(abi+name), compress_type=zipfile.ZIP_DEFLATED)
        out.write(dex/"classes.dex","classes.dex",compress_type=zipfile.ZIP_DEFLATED)
    call(tools/"zipalign","-p","-f","4","package.apk","aligned.apk")
    result = work/"glmark2-pixel2-compare.apk"
    call(tools/"apksigner","sign","--ks",args.keystore,"--ks-key-alias","androiddebugkey",
         "--ks-pass","pass:android","--out",result,"aligned.apk")
    call(tools/"apksigner","verify","--min-sdk-version","31",result)
    with zipfile.ZipFile(args.official_apk) as original, zipfile.ZipFile(result) as rebuilt, \
            zipfile.ZipFile(args.driver_apk) as driver:
        for item in original_entries:
            if rebuilt.read(item.filename) != original.read(item):
                raise ValueError("glmark2 input changed: " + item.filename)
        for name in DRIVER_LIBS:
            if rebuilt.read(abi+name) != driver.read(abi+name):
                raise ValueError("Driver library changed: " + name)
    print(f"Verified {len(original_entries)} original entries and three driver libraries. APK {result}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("official_apk","source_tar","driver_apk","sdk","keystore","out"):
        parser.add_argument(arg,type=lambda p:Path(p).resolve())
    build(parser.parse_args())
