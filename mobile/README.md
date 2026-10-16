# GharBox phone app

Backs up your camera roll to your GharBox server. It hashes each photo and video, asks the
server which ones it already has, and uploads only new ones in 8 MB resumable chunks. iPhone
Live Photos are saved as the photo plus its short video. Photos stored only in iCloud are
downloaded to the phone first, so the first backup can take a while.

Files land in `Camera Roll/<year>` in your GharBox files and appear in Photos by date.

## Build it

You need the Flutter SDK (free): https://docs.flutter.dev/get-started/install/windows

```powershell
cd mobile
flutter create . --org com.gharbox --project-name gharbox --platforms=android,ios
python tool/setup_platforms.py      # adds photo permissions and allows http:// on your LAN
flutter pub get
```

**Android:** connect your phone with USB debugging on, then `flutter run --release`, or build an
APK to share with family: `flutter build apk --release` (find it in `build/app/outputs/flutter-apk/`).

**iPhone:** building for iOS needs a Mac with Xcode. With a free Apple ID the app runs for
7 days before you reinstall it; a paid developer account ($99/year) removes that limit. Until
then, your iPhone can upload through Safari at your GharBox address.

## Using it

1. Open the app and enter your server address, for example `http://192.168.0.105:8080`.
2. Sign in with your GharBox account and allow full photo access.
3. Backup starts by itself and runs again every time you open the app.

Phones pause apps in the background, so keep GharBox open (it keeps the screen on) during the
first big backup. Later runs only send new photos and finish quickly.

## Not yet included

- Automatic backup in the background (Android WorkManager, iOS background tasks)
- Choosing which albums to back up
- Browsing and streaming from the app (use the web app in your phone's browser for now)
