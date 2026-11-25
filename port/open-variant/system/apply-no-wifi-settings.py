#!/usr/bin/env python3
"""Adapt Android Settings to a build without a Wi-Fi service."""
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: apply-no-wifi-settings.py GAMMA_SOURCE")
    source = Path(sys.argv[1])
    settings = source / (
        "packages/apps/Settings/src/com/android/settings/deviceinfo/"
        "WifiMacAddressPreferenceController.java"
    )
    shared = source / (
        "frameworks/base/packages/SettingsLib/src/com/android/settingslib/deviceinfo/"
        "AbstractWifiMacAddressPreferenceController.java"
    )
    changes = {
        settings: [
            (
                "import android.content.Context;\n",
                "import android.content.Context;\nimport android.content.pm.PackageManager;\n",
            ),
            (
                "return mContext.getResources().getBoolean(R.bool.config_show_wifi_mac_address);",
                "return super.isAvailable()\n"
                "                && mContext.getPackageManager().hasSystemFeature(PackageManager.FEATURE_WIFI)\n"
                "                && mContext.getResources().getBoolean(R.bool.config_show_wifi_mac_address);",
            ),
        ],
        shared: [
            ("public boolean isAvailable() {\n        return true;",
             "public boolean isAvailable() {\n        return mWifiManager != null;"),
            (
                "    protected void updateConnectivity() {\n"
                "        final String[] macAddresses = mWifiManager.getFactoryMacAddresses();",
                "    protected void updateConnectivity() {\n"
                "        if (mWifiManager == null || mWifiMacAddress == null) {\n"
                "            return;\n"
                "        }\n"
                "        final String[] macAddresses = mWifiManager.getFactoryMacAddresses();",
            ),
        ],
    }
    development = source / "packages/apps/Settings/src/com/android/settings/development"
    developer_changes = [
        (
            "    @Override\n    public String getPreferenceKey() {",
            "    @Override\n"
            "    public boolean isAvailable() {\n"
            "        return mWifiManager != null;\n"
            "    }\n\n"
            "    @Override\n    public String getPreferenceKey() {",
        ),
        (
            "    public boolean onPreferenceChange(Preference preference, Object newValue) {\n",
            "    public boolean onPreferenceChange(Preference preference, Object newValue) {\n"
            "        if (mWifiManager == null) {\n"
            "            return false;\n"
            "        }\n",
        ),
        (
            "    public void updateState(Preference preference) {\n",
            "    public void updateState(Preference preference) {\n"
            "        if (mWifiManager == null || mPreference == null) {\n"
            "            return;\n"
            "        }\n",
        ),
        (
            "    protected void onDeveloperOptionsSwitchDisabled() {\n",
            "    protected void onDeveloperOptionsSwitchDisabled() {\n"
            "        if (mWifiManager == null || mPreference == null) {\n"
            "            return;\n"
            "        }\n",
        ),
    ]
    changes[development / "WifiVerboseLoggingPreferenceController.java"] = developer_changes
    changes[development / "WifiScanThrottlingPreferenceController.java"] = developer_changes
    updated = {}
    for path, replacements in changes.items():
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            if text.count(new) == 1 and old not in text.replace(new, "", 1):
                continue
            if old == new or new in text or text.count(old) != 1:
                raise SystemExit(f"Unexpected Settings source: {path}")
            text = text.replace(old, new, 1)
        updated[path] = text
    for path, text in updated.items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
