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

URLs come from two places and are merged: a links file (chosen via **Browse**
or by dragging a `.txt` file onto the window) and the **Direct links** box.
Dragging text or URLs from a browser onto the window appends them to the
direct links box. Both accept URLs separated by newlines, commas, spaces, or
any mixture. Duplicates across the two sources are removed while preserving
order. Malformed entries remain visible as `Invalid` and are skipped.

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

## Quality and downloads

Quality is a maximum height, not an exact target. For example, 1080p selects
the best compatible stream at or below 1080p where possible; lower-resolution
sources are not upscaled. Sequential mode uses one worker. Parallel mode uses
1–5 workers and defaults to 3.

The default output directory is `downloads`. yt-dlp resumes partial downloads,
uses retries for temporary failures, and merges to MP4 when FFmpeg is
available. Existing final files can be skipped; `.part` files alone are not
treated as completed files.

## Building a standalone executable

```powershell
.uild.ps1
```

This runs PyInstaller with `VideoBatchDownloader.spec` and produces
`dist\VideoBatchDownloader.exe`, a single windowed executable (about 55 MB)
that needs no Python install. Settings, history, the log, and the default
`downloads` folder are created next to the exe. FFmpeg is not bundled: keep it
on `PATH` or point the FFmpeg path setting at it.

The spec pins the OpenSSL DLLs from the build interpreter and excludes Qt's
OpenSSL plugin; without that, a same-named `libssl-3-x64.dll` earlier on
`PATH` (Git's `mingw64in`, for example) can get bundled and break `ssl`.

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
