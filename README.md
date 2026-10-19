# Video Batch Downloader

A focused desktop app for downloading batches of videos supported by
yt-dlp. The interface is built with PySide6 (Qt) and keeps all downloads off
the GUI thread, with per-video progress, retries, cancellation, persistent
history, system-tray support, and settings persistence.

## Requirements

- Python 3.10 or newer
- FFmpeg recommended (required when yt-dlp needs to merge separate video and
  audio streams)
- A network connection and a text file containing URLs

## Windows installation

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if it is
not already available. In PowerShell, the official installer is:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Open PowerShell in this folder:

```powershell
uv sync
uv run python app.py
```

`uv sync` creates and manages the project virtual environment automatically.
For environments that do not use uv, the compatible pip setup remains:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Install FFmpeg separately and put its `bin` directory on `PATH`, or use the
FFmpeg path field in the application. The app warns if it cannot find FFmpeg;
it does not exit just because FFmpeg is unavailable.

## URL sources

Pasting links into the **Links** box on the Downloads tab is the main route:
it accepts URLs separated by newlines, commas, spaces, or any mixture, and
re-reads as you type. Dragging text or URLs from a browser onto the window
appends them there.

**Load from a file** below that box expands a secondary row for picking a
`.txt` file of links (dropping a `.txt` file onto the window fills it in and
expands the row automatically). When both are in use the two sources are
merged and de-duplicated with order preserved. Malformed entries remain
visible as `Invalid` and are skipped.

## Searching for videos

The **Search** tab searches YouTube, SoundCloud, Bilibili, Niconico, or Yahoo
Video through yt-dlp's search extractors, so no API keys are needed. Results
show a thumbnail, title, uploader, duration, and view count. Tick the rows you
want and press **Add selected to queue** (or double-click a single row) to
append them to the direct links box; links already queued are skipped. Pasting
a URL into the search field adds it directly.

## System tray

Closing the window minimises the app to the system tray. Click the tray icon
or choose **Show** from its menu to restore the window; choose **Exit** to
quit fully. If a batch finishes while the window is hidden, a tray
notification reports the result. Any active batch is cancelled cleanly on
Exit and the history is flushed to disk.

## Download history

`download_history.json` is persistent across sessions. Each finished job
(Completed, Failed, Cancelled, or Skipped) is written with its original URL,
title, status, output path, error, byte counts, and a timestamp, updated as
each job finishes and again on exit. The History tab is sortable by any
column; double-click a row to open the file's folder.

## Retrying

Failed or cancelled jobs show a per-row **Retry** button, and **Retry failed**
in the bottom bar re-queues all of them at once. The failure reason is shown
inline in the Details column.

## ETA formatting

Remaining time is shown as `Ns` under a minute, `M:SS` under an hour, and
`H:MM:SS` otherwise.

## FFmpeg

FFmpeg is needed to merge separate video/audio streams and for every audio
format. Settings shows where it resolved to, and **Download** there fetches a
static build into an `ffmpeg` folder beside the app — no install or admin
rights required. Starting an audio batch without FFmpeg offers the same
download.

The archive comes from gyan.dev (the Windows build provider linked from
ffmpeg.org) over HTTPS and is checked against the SHA-256 published alongside
it; a mismatch is discarded rather than used. The transfer resumes if the
connection drops and can be cancelled. A copy already on `PATH`, or one set
explicitly in Settings, always takes precedence.

## Audio downloads (MP3 and friends)

The **Format** selector next to **Start download** switches the whole batch
between video and audio-only. Audio choices are MP3, M4A, Opus, FLAC and WAV:
yt-dlp grabs the best audio stream and FFmpeg converts it, so FFmpeg is
required for these (the app says so inline if it cannot find it).

The bitrate used for the lossy codecs is set in Settings; FLAC and WAV are
lossless, so that control is disabled for them. Skip-existing understands the
chosen extension, so re-running an MP3 batch skips tracks already converted
rather than downloading them again.

## Subtitles

Settings has a **Subtitles** group that applies to the whole batch. The choices
are no subtitles, save as an `.srt` file next to the video, embed a subtitle
track in the MP4, or both. **Languages** takes codes separated by commas or
spaces (`en, es`), or `all` for every language a video offers, and
auto-generated captions can be accepted when a video has no human-made track.

Embedding runs through FFmpeg, so it needs the same FFmpeg as audio downloads
and offers the built-in download if none is found; sidecar files are converted
to `.srt` when FFmpeg is available and otherwise kept in whatever format the
site serves. A video that offers no captions in the languages asked for still
downloads — the subtitle step is simply skipped. Audio-only formats ignore
subtitles, and the group says so.

## Quality and downloads

Quality is a maximum height, not an exact target. For example, 1080p selects
the best compatible stream at or below 1080p where possible; lower-resolution
sources are not upscaled. Sequential mode uses one worker. Parallel mode uses
1–5 workers and defaults to 3.

The default output directory is `Video Batch Downloader` under your Videos
folder. yt-dlp resumes partial downloads,
uses retries for temporary failures, and merges to MP4 when FFmpeg is
available. Existing final files can be skipped; `.part` files alone are not
treated as completed files.

## Building a standalone executable

```powershell
.\build.ps1            # dist\VideoBatchDownloader.exe
.\build.ps1 -Installer # also dist\VideoBatchDownloader-<version>-setup.exe
```

The first form runs PyInstaller with `VideoBatchDownloader.spec` and produces
a single windowed executable (about 53 MB) that needs no Python install. It is
portable: settings, history and the log are written beside it, so it can live
on a USB stick.

`-Installer` additionally compiles `installer.iss` with Inno Setup (install it
from https://jrsoftware.org/isdl.php if `ISCC.exe` is not found). The installer
is **per-user**: it needs no administrator rights, installs to
`%LOCALAPPDATA%\Programs\Video Batch Downloader`, and adds Start Menu entries
plus an optional desktop icon. A per-user location matters here because the app
writes its settings, history, log and any auto-downloaded FFmpeg next to the
executable, which a Program Files install would forbid. Uninstalling removes
those files; downloaded videos are left alone.

FFmpeg is not bundled in either case — use the Download button in Settings, or
keep FFmpeg on `PATH`.

The spec pins the OpenSSL DLLs from the build interpreter and excludes Qt's
OpenSSL plugin; without that, a same-named `libssl-3-x64.dll` earlier on
`PATH` (Git's `mingw64\bin`, for example) can get bundled and break `ssl`.

## Troubleshooting

- If the app says yt-dlp is missing, run `uv sync` and launch with
  `uv run python app.py`.
- If downloads requiring separate audio/video streams fail, install FFmpeg or
  choose its executable in the FFmpeg path field.
- See `download.log` for timestamps, URLs, statuses, errors, and output paths.
  A persistent record of every completed job is kept in `download_history.json`.

## CLI fallback

`python app.py` launches the GUI. The project intentionally keeps the GUI as
the primary interface; yt-dlp's Python API is used directly rather than by
spawning a subprocess for each download.
