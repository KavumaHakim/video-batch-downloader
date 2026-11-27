# Video Batch Downloader for Android

The Android version of Video Batch Downloader. It's a native Kotlin / Jetpack
Compose app built on [youtubedl-android](https://github.com/yausername/youtubedl-android),
which bundles yt-dlp, Python and FFmpeg into the app. Downloads work the same
way as on the desktop app.

## What it does

- **Downloads tab:** paste one link per line, choose **Video** or **Audio
  only**, and tap **Start download**. Each video gets a card with its progress,
  and you can cancel it, retry it, or open it when it's done.
- **Share to the app:** in YouTube, Instagram, a browser or any other app,
  choose **Share → Video Batch Downloader**. The link lands in the box, ready
  to start.
- **Playlists and channels** are split into one card per video. You can limit
  how many videos are taken, and each playlist can go into its own folder.
- **Spotify links** (tracks, albums, playlists) are read for their track
  names. Each track is then found on YouTube or SoundCloud, because Spotify's
  own audio is DRM-protected.
- **Search tab:** search YouTube, SoundCloud, Bilibili or Niconico, tick the
  results you want, and download them.
- **Video is always H.264 in MP4**, up to 1080p. It plays on every phone and
  PC without converting. Only a site that offers no H.264 at all gets its best
  other stream.
- **Audio** can be MP3, M4A, Opus, FLAC or WAV.
- Downloads **carry on in the background**, with a progress notification.
- **Play without downloading:** tap ▶ on a YouTube search result, or
  **Play** beside **Download** for pasted links, playlists, channels and
  Spotify links. Audio streams from YouTube, with the next songs looked up
  early so they start at once. Songs you've played are kept in a 500 MB
  cache so replays use no data. Settings has a quality for Wi-Fi and one for
  mobile data (Normal about 130 kbps, Data saver about 50 kbps). The player's
  ⬇ button saves the song that's playing. SoundCloud and the other search
  sites are download-only for now, because SoundCloud serves only HLS streams.
- **A music home:** the **Home** tab has recently played songs, mixes made
  from the artists you play most, quick picks and your playlists. **♥** a
  song in the player, its notification or any ⋮ menu to add it to Liked
  songs. **Library → Playlists** lets you make playlists, rename them, move
  songs up or down, and import a Spotify or YouTube playlist from its link.
  **Start radio** on any song queues songs like it, and **Autoplay** keeps the
  music going when the queue runs out. Search on **YouTube Music** finds songs
  with their artist, length and cover. The queue comes back, paused, the next
  time you open the app. Likes, playlists and history are stored only on the
  phone.
- **Built-in player:** tap **Play** on a finished card, or anything in the
  **Library** tab, which lists everything the app has saved. Playback has a
  queue, shuffle, repeat, speed control, 10-second skips and full-screen
  video. It keeps playing in the background, with controls in the
  notification and on the lock screen. A mini player sits above the tabs.
- **yt-dlp updates itself** once a day, and Settings has an **Update now**
  button. Sites change often, and an old yt-dlp is the usual reason downloads
  start failing.

Files are saved to **Download/Video Batch Downloader** on the phone, so the
gallery, music player and file manager all see them.

## Installing

The app isn't on Google Play, because Play doesn't allow YouTube downloaders.
Install the APK directly:

| APK | For |
|---|---|
| `app-arm64-v8a-release.apk` | Almost every phone from the last several years. Pick this if unsure. |
| `app-armeabi-v7a-release.apk` | Older 32-bit phones. |
| `app-x86_64-release.apk` | The Android emulator and a few tablets. |

Each APK is about 70 MB, because it carries its own Python and FFmpeg. The
app needs Android 7.0 or newer.

## Building

You need JDK 17 and the Android SDK (platform 36). Put the SDK's location in
`local.properties` (`sdk.dir=...`); Android Studio does this for you. Then:

```powershell
cd android
.\gradlew.bat assembleDebug
```

The APKs are written to `app/build/outputs/apk/debug/`. Install one on a
phone that has USB debugging turned on:

```powershell
adb install -r app\build\outputs\apk\debug\app-arm64-v8a-debug.apk
```

### Release builds

`.\gradlew.bat assembleRelease` signs with your own key when
`android/keystore.properties` exists:

```properties
storeFile=release.jks
storePassword=...
keyAlias=...
keyPassword=...
```

Without that file, release builds are signed with the debug key. They still
install, but keep one real key for every release you publish, because Android
only lets an APK update an installed app that was signed with the same key.
Never commit the key or `keystore.properties`; `.gitignore` already excludes
them.

## License note

youtubedl-android is GPL-3.0. Because this app includes it, any APK you
distribute must be under GPL-3.0 too, with the source available. The source
is in this repository.
