# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare a dedicated PPSSPP 1.20.4 checkout for the Pixel 2 presentation test."""
import argparse
import hashlib
import shutil
import subprocess
import zipfile
from pathlib import Path

COMMIT = "fa50bb1976065c4f8b1b47af227d367fe9771555"
APK_SHA = "dd702a31270ecd68db37afee311d6efe08b1d4da9601d2750ce1a73bbd316c3f"
PACKAGE = "org.ppsspp.ppsspp.pixel2test"
HERE = Path(__file__).resolve().parent


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Unexpected PPSSPP source around " + old)
    return source.replace(old, new)


def prepare(root, apk):
    if git(root, "rev-parse", "HEAD").strip() != COMMIT:
        raise ValueError("Use a separate checkout at PPSSPP v1.20.4")
    if git(root, "status", "--porcelain").strip():
        raise ValueError("Use a fresh dedicated checkout so local edits cannot be overwritten")
    if hashlib.sha256(apk.read_bytes()).hexdigest() != APK_SHA:
        raise ValueError("Official PPSSPP APK digest mismatch")
    android = root / "android"
    with zipfile.ZipFile(apk) as official:
        for item in official.namelist():
            if item.endswith("/"):
                continue
            parts = Path(item).parts
            if ".." in parts or Path(item).is_absolute():
                raise ValueError(item)
            if parts[0] == "assets":
                output = android.joinpath("pixel2assets", *parts[1:])
            elif item in ("lib/armeabi-v7a/libppsspp_jni.so", "lib/armeabi-v7a/libc++_shared.so"):
                output = android.joinpath("src/main/jniLibs", *parts[1:])
            else:
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(official.read(item))

    gradle = git(root, "show", "HEAD:android/build.gradle.kts")
    lines = []
    closing = None
    for line in gradle.splitlines(keepends=True):
        if closing is not None:
            if line.rstrip() == closing:
                closing = None
            continue
        if line.strip() == "externalNativeBuild {":
            closing = line[:line.index("externalNativeBuild")] + "}"
        elif line.strip().startswith("ndkVersion ="):
            continue
        else:
            lines.append(line)
    gradle = "".join(lines)
    gradle = gradle.replace('applicationId = "org.ppsspp.ppsspp"', f'applicationId = "{PACKAGE}"')
    gradle = replace_once(gradle, 'assets.directories.add("../assets")', 'assets.directories.add("pixel2assets")')
    gradle = replace_once(gradle, 'jniLibs.useLegacyPackaging = true', 'jniLibs.useLegacyPackaging = true\n\t\tjniLibs.keepDebugSymbols.add("**/*.so")')
    gradle = replace_once(gradle, 'getByName("debug") {\n\t\t\tstoreFile = file("debug.keystore")\n\t\t}', 'getByName("debug") { }')
    (android / "build.gradle.kts").write_text(gradle)
    activity = "android/src/org/ppsspp/ppsspp/PpssppActivity.java"
    hook = "mGLSurfaceView.setEGLContextClientVersion(isVRDevice() ? 3 : 2);"
    source = replace_once(git(root, "show", "HEAD:" + activity), hook, hook + "\n\t\t\tPixel2Presentation.configure(mGLSurfaceView, this);")
    (root / activity).write_text(source)
    # This separate package starts fresh and uses Android's document picker.
    # Some handheld ROMs report legacy storage even on a newly installed app.
    manifest = "android/AndroidManifest.xml"
    xml = git(root, "show", "HEAD:" + manifest)
    for attribute in ("requestLegacyExternalStorage", "preserveLegacyExternalStorage"):
        xml = replace_once(xml, attribute + '="true"', attribute + '="false"')
    anchor = '<meta-data android:name="isGame" android:value="true" />'
    alias = '''<activity-alias android:name="org.ppsspp.ppsspp.Pixel2G31Launcher"
            android:targetActivity="org.ppsspp.ppsspp.PpssppActivity"
            android:exported="true" android:label="@string/pixel2_g31_name">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
                <category android:name="android.intent.category.LEANBACK_LAUNCHER" />
            </intent-filter>
        </activity-alias>'''
    xml = replace_once(xml, anchor, alias + "\n        " + anchor)
    (root / manifest).write_text(xml)
    storage = "android/src/org/ppsspp/ppsspp/ContentUri.java"
    java = git(root, "show", "HEAD:" + storage)
    java = replace_once(java, "return Environment.isExternalStorageLegacy();",
                        "return Build.VERSION.SDK_INT < 30 && Environment.isExternalStorageLegacy();")
    (root / storage).write_text(java)
    shutil.copyfile(HERE / "Pixel2Presentation.java", (root / activity).with_name("Pixel2Presentation.java"))
    strings = "android/res/values/strings.xml"
    xml = git(root, "show", "HEAD:" + strings)
    xml = replace_once(xml, ">PPSSPP<", ">PPSSPP Pixel 2 Test<")
    (root / strings).write_text(replace_once(xml, "</resources>", '    <string name="pixel2_g31_name">PPSSPP G31</string>\n</resources>'))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkout", type=Path)
    parser.add_argument("official_apk", type=Path)
    args = parser.parse_args()
    prepare(args.checkout.resolve(), args.official_apk)
