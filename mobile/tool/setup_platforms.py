"""Run once after `flutter create`: adds the permissions GharBox needs.

    cd mobile
    flutter create . --org com.gharbox --project-name gharbox --platforms=android,ios
    python tool/setup_platforms.py
"""
from pathlib import Path

root = Path(__file__).resolve().parent.parent

manifest = root / "android/app/src/main/AndroidManifest.xml"
if manifest.exists():
    s = manifest.read_text(encoding="utf-8")
    perms = [
        "android.permission.INTERNET",
        "android.permission.READ_MEDIA_IMAGES",
        "android.permission.READ_MEDIA_VIDEO",
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
        "android.permission.ACCESS_MEDIA_LOCATION",
    ]
    lines = "".join(f'    <uses-permission android:name="{p}" />\n' for p in perms if p not in s)
    lines += ('    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" '
              'android:maxSdkVersion="32" />\n') if "READ_EXTERNAL_STORAGE" not in s else ""
    s = s.replace("<application", lines + "    <application", 1) if lines else s
    if "usesCleartextTraffic" not in s:
        # your home server is plain http:// on the LAN
        s = s.replace("<application", '<application\n        android:usesCleartextTraffic="true"', 1)
    manifest.write_text(s, encoding="utf-8")
    print("patched", manifest)

plist = root / "ios/Runner/Info.plist"
if plist.exists():
    s = plist.read_text(encoding="utf-8")
    extra = {
        "NSPhotoLibraryUsageDescription": "GharBox backs up your photos and videos to your own computer.",
        "NSPhotoLibraryAddUsageDescription": "GharBox can save photos back to your library.",
        "NSLocalNetworkUsageDescription": "GharBox connects to your GharBox server on your home network.",
    }
    add = "".join(f"\t<key>{k}</key>\n\t<string>{v}</string>\n" for k, v in extra.items() if k not in s)
    if "NSAppTransportSecurity" not in s:
        add += ("\t<key>NSAppTransportSecurity</key>\n\t<dict>\n"
                "\t\t<key>NSAllowsArbitraryLoads</key>\n\t\t<true/>\n"
                "\t\t<key>NSAllowsLocalNetworking</key>\n\t\t<true/>\n\t</dict>\n")
    if add:
        idx = s.rfind("</dict>")
        s = s[:idx] + add + s[idx:]
        plist.write_text(s, encoding="utf-8")
    print("patched", plist)

print("done")
