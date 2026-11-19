# Video Batch Downloader

A Windows app for downloading a lot of videos at once. Paste links, press
**Start download**, and watch them come down one card at a time. It handles
playlists, whole channels, Instagram posts with several clips, and Spotify
links, and it can save audio instead of video.

---

## Installing

Grab the latest from the [releases page](https://github.com/KavumaHakim/video-batch-downloader/releases).
Two downloads, same app:

| Download | Pick this if |
|---|---|
| **VideoBatchDownloader-&lt;version&gt;-setup.exe** | You want it installed properly — Start Menu entry, optional desktop icon, an uninstaller, and FFmpeg already included so everything works offline. |
| **VideoBatchDownloader.exe** | You want it portable — one file, no install, runs from a USB stick. It fetches FFmpeg itself the first time it needs it. |

The installer needs no administrator rights. It installs to your own user
folder, upgrades an older version in place, and keeps your settings, history
and log.

Windows may warn that the app is from an unknown publisher, because the build
is not code-signed. Choose **More info → Run anyway** if you are happy to.

---

## Downloading something

1. Open the **Downloads** tab.
2. Paste one or more links into **Add links**. Separate them with new lines,
   commas or spaces — any mixture works. You can also drag links straight from
   your browser onto the window.
3. Press **Start download**.

That is the whole thing. Files land in your output folder, which starts as
`Video Batch Downloader` inside your Videos folder and can be changed in
Settings.

### What you can paste

| Paste this | You get |
|---|---|
| A video link | That video. |
| A playlist, channel or album link | Every video behind it, each queued separately. |
| An Instagram post with several photos or clips | All of its items, as separate files. |
| A Spotify track, album or playlist link | Each track, found on YouTube or SoundCloud. |
| A `.txt` file of links | Everything in it — use **From a file**, or drop the file on the window. |

Anything that is not a usable link stays in the list marked `Invalid` and is
skipped rather than stopping the batch.

---

## The download list

Each download is a card showing its artwork, title, where it came from, how it
is going, and a progress bar. The coloured edge and the label on the right tell
you its state at a glance.

| State | Means |
|---|---|
| **Queued** | Waiting its turn. |
| **Downloading** | In progress — the card shows size, speed and time left. |
| **Waiting** | Holding off because the site is rate limiting. It will carry on by itself. |
| **Completed** | Done. |
| **Skipped** | The file was already in your output folder. |
| **Failed** | Something went wrong — the reason is on the card. |

**Things you can do to a card**

- The button on the right changes with the state: **Retry** a failed download,
  or **Open** the folder of a finished one.
- **Double-click** a card to open its folder, or the original page if it has
  not downloaded yet.
- **Right-click** for everything else: open the folder or the source page, copy
  the link or the error, retry, or remove it from the queue. Select several
  cards first and it applies to all of them.

**Above the list**, the **All / Active / Done / Failed** buttons filter what you
are looking at and show how many of each there are, and the thin bar underneath
is the progress of the whole batch. **Clear finished** tidies away everything
that completed, taking it out of the links box too.

**Retry failed** at the bottom re-runs everything that failed in one go, and
tells you how many it will do. You do not have to wait for the batch to end —
retried downloads simply join the ones already running.

### Adding links while downloads are running

You can keep pasting while a batch is going. New links are picked up and start
downloading on their own, without stopping anything or needing another press of
**Start** — the status line confirms what was added and how many are left to
go.

Taking a link out of the box removes it from the queue, unless it is already
downloading, in which case it is left to finish.

---

## Choosing video or audio

The **Format** box at the bottom of the window decides what you end up with.

- **Video (MP4)** — the normal choice. Use **Quality** in Settings to cap the
  resolution; it is a maximum, so a lower-quality source is not stretched to
  match.
- **Audio: MP3, M4A, Opus, FLAC or WAV** — the soundtrack only. **Bitrate**
  applies to MP3, M4A and Opus; FLAC and WAV are lossless so it is ignored.

Pick an audio format before downloading music, or you will get video files with
the music inside them.

---

## Playlists, channels and Spotify

### Playlists and channels

On by default. A playlist, channel, album or set link is read once when you
press Start and queued as the individual videos behind it, each with its own
card.

- **Videos per playlist** caps how many one link contributes. Useful against a
  channel with thousands of uploads. `All` takes every one.
- **Save each playlist in its own subfolder** keeps things tidy by putting each
  playlist's videos in a folder named after it.
- Turn the whole thing off and a playlist link brings down just one video.

A link that cannot be opened as a playlist — a YouTube mix, a private list —
quietly falls back to downloading the single video it points at.

### Posts with several photos or clips

An Instagram carousel is one post holding several items. It stays as one card
and saves every item as its own file. Download these as video: a photo has no
soundtrack, so an audio format will fail on it.

### Spotify links

Spotify's own audio is copy-protected and cannot be downloaded — not here, not
anywhere. What this app does instead is read a Spotify link to see *what is on
it*, then find each track on **YouTube** or **SoundCloud** (your choice under
**Find tracks on**) and download that.

No Spotify account, login or setup is needed. Paste a track, album, playlist or
artist link and each track becomes its own card, showing `Artist — Title` until
the matched video's own title arrives.

Because it works by searching, a track with a vague name can occasionally match
the wrong upload — the card always shows what actually came down. Set an audio
format first if you want music files.

---

## Finding videos without a link

The **Search** tab searches YouTube, SoundCloud, Bilibili, Niconico and Yahoo
Video. Type a query, pick a site, and tick the results you want, then press
**Add selected to queue** — or double-click a single result. Pasting a link
into the search box just adds it to the queue.

---

## Subtitles

Settings has a **Subtitles** group that applies to the whole batch:

| Choice | Result |
|---|---|
| **No subtitles** | Nothing extra. |
| **Save as .srt file** | Captions saved next to the video. |
| **Embed in the video** | Captions become a track inside the MP4, switchable in any player. |
| **Embed and keep the file** | Both. |

**Languages** takes codes separated by commas or spaces (`en, es`), or `all`
for every language offered. Auto-generated captions can be accepted when
there is no human-made track.

Subtitles never cost you the video. If a video has none in the languages you
asked for, or the captions will not download, you still get the video and the
card says `no subtitles`.

---

## When downloads start failing

Ask a site for a lot in a short time and it starts refusing — often with errors
that look like the video is gone when really you are just going too fast.

Two settings under **Download options** handle it:

- **Pause between requests** puts a gap between requests. This is the one that
  prevents the problem. `Off` goes as fast as possible.
- **Retry if throttled** gives a refused download more goes before giving up.

When it happens, the whole batch waits rather than just the one download,
because the block is on your connection. Those cards read `Holding off`. A
video that genuinely is unavailable still fails straight away.

If it keeps happening, lower **Workers**, raise the pause, or come back later.

---

## Settings worth knowing

| Setting | Does |
|---|---|
| **Output folder** | Where files are saved. |
| **Quality** | Maximum video height. |
| **Mode / Workers** | Sequential does one at a time; Parallel does up to five at once. |
| **Skip files that already exist** | Leaves alone anything already in the output folder, so a re-run picks up where it left off. |
| **FFmpeg path** | Only needed if you want your own FFmpeg instead of the included one. |

Settings are saved when a download starts and when you close the app.

---

## History and the system tray

The **History** tab lists everything downloaded, with the time, title, status
and where it went. Double-click a row to open its folder. **Clear** empties it.

Closing the window keeps the app running in the system tray so downloads carry
on. Click the tray icon to bring it back, or right-click it and choose **Exit**
to quit properly. If a batch is still running, it will ask before closing.

---

## If something goes wrong

| Problem | Try this |
|---|---|
| A download failed | Read the reason on the card, then press **Retry** — many failures are temporary. |
| Lots of failures at once | The site is probably rate limiting you. See [When downloads start failing](#when-downloads-start-failing). |
| Audio formats are not working | FFmpeg is missing. In Settings, press **Download** next to the FFmpeg path. The installer version already has it. |
| The wrong song downloaded from a Spotify link | It matched the wrong upload. Remove that card and paste the correct video link instead. |
| A video downloads with no subtitles | It had none in the languages you asked for. Try adding more languages, or `all`. |
| The app closed by itself | `crash.log` next to the app records what it was doing at the time. Attaching it to a bug report is the single most useful thing you can do. |
| Something else | `download.log` next to the app records every download, with timestamps and errors. |

---

## About FFmpeg

The app uses FFmpeg to convert audio, join separate video and audio streams,
and handle subtitles. The installer includes it, so there is nothing to do. The
portable version downloads it once, when it first needs it.

The included FFmpeg is licensed under the GNU General Public License v3. Its
licence and a note saying where to get its source are in the `ffmpeg` folder
beside the app. You are free to delete that folder and point the FFmpeg path in
Settings at your own copy.
