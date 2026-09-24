# SpotDL UI

A clean, modern desktop front end for [spotdl](https://github.com/spotDL/spotify-downloader):
a GTK4 / libadwaita app on Linux, and a portable PyQt6 `.exe` on Windows.

![format](https://img.shields.io/badge/GTK-4-blue) ![theme](https://img.shields.io/badge/libadwaita-1-green) ![windows](https://img.shields.io/badge/Windows-PyQt6-informational)

## Features

- Paste any number of Spotify track, album, playlist or artist links (or plain search terms), one per line
- Album and playlist links automatically get their own subfolder (named after the album/playlist) inside
  your chosen output location, so a multi-track album or playlist doesn't spill loose into the main folder
- Choose audio format (mp3, flac, ogg, opus, m4a, wav), bitrate, parallel download count, and overwrite behavior
- Live progress: an overall "N / M tracks" bar plus a per-track status bar, updated in near real time
- A live, scrolling log of exactly what spotdl is doing
- Pick an output folder with the native folder picker, **or create a new folder on the spot** with the
  "New folder" button next to the output path
- Launches like any other desktop app, with its own icon, from your application grid/search
- Cancel an in-progress download at any time

## Requirements

- Fedora Workstation (or any GNOME/GTK4 desktop) with `gtk4`, `libadwaita`, `python3-gobject`
- Python 3.9+
- [`spotdl`](https://pypi.org/project/spotdl/) (installed via pip)
- `ffmpeg` (for audio conversion)

## Install

```bash
./install.sh
```

This will:

1. Check for GTK4/libadwaita and offer to install them via `dnf` if missing
2. Check for `spotdl` and offer to install it via `pip install --user spotdl` if missing
3. Warn if `ffmpeg` is missing (Fedora needs [RPM Fusion](https://rpmfusion.org/) for it:
   `sudo dnf install ffmpeg`, or let spotdl fetch its own copy with `spotdl --download-ffmpeg`)
4. Install the app icon and a `.desktop` launcher so **SpotDL UI** shows up in your app grid/search,
   pinnable to the dock like any other application

Run `./uninstall.sh` to remove just the launcher/icon again (your settings and downloads are untouched).

## Running without installing

```bash
./bin/spotdl-ui
```

or

```bash
python3 -m spotdl_ui.app
```

## Windows

There's no Linux/GTK install available on Windows, so the Windows build is a separate, portable
`SpotDL-UI.exe` built with PyQt6 + PyInstaller instead - same options (format, bitrate, threads,
overwrite mode, album/playlist subfolders), same look and feel, no install required.

- **Download a build:** go to the [Actions tab](../../actions/workflows/build-windows.yml), open the
  latest successful run of "Build Windows executable", and grab the `SpotDL-UI-Windows` artifact
  (or, for a tagged release, attach that artifact to a GitHub Release for a stable download link).
- **Build it yourself:**
  ```powershell
  pip install -r requirements.txt
  pip install pyinstaller
  pyinstaller --name SpotDL-UI --onefile --windowed --collect-data pykakasi --collect-data ytmusicapi --collect-data spotdl --hidden-import spotipy windows_main.py
  ```
  The `.exe` ends up in `dist\`.

Unlike the Linux build, the Windows build embeds `spotdl` as a library rather than shelling out to the
`spotdl` CLI (there's nothing to shell out to once it's frozen into a single `.exe`), and it downloads its
own copy of `ffmpeg` on first run if one isn't already on `PATH`. One consequence: **Cancel** takes effect
after the current track/playlist/album finishes, rather than instantly - spotdl's library API doesn't give
a way to interrupt a batch that's already in flight, which is also why the Linux build shells out to the
CLI as a real, cleanly-killable OS process instead.

## Notes

- Settings (output folder, format, bitrate, thread count, overwrite mode) are remembered between runs in
  `~/.config/spotdl-ui/config.json` (Linux) or `%APPDATA%\spotdl-ui\config.json` (Windows).
- The Linux app shells out to the real `spotdl` CLI (`spotdl download ... --simple-tui`) in a background
  thread, so it always behaves exactly like the command line tool - this GUI is just a friendly face on
  top of it. The Windows build uses spotdl as a library instead - see "Windows" above.
- Because there's no official numeric download-percentage API from spotdl's simple-TUI output, the
  per-track progress bar is a smooth estimate based on which stage spotdl reports
  (searching → downloading → converting → done). The overall "N / M tracks" counter is exact.
- No Spotify account is required - spotdl ships with default API credentials that work out of the box.

## Project layout

```
bin/spotdl-ui            launcher script (what the desktop entry runs, Linux)
windows_main.py           entry point PyInstaller freezes into SpotDL-UI.exe (Windows)
spotdl_ui/
  app.py                  Adw.Application + About dialog (Linux/GTK)
  window.py                main window / all UI (Linux/GTK)
  qt_app.py                 QApplication entry point (Windows/PyQt6)
  qt_window.py               main window / all UI (Windows/PyQt6)
  download_job.py            background spotdl subprocess + log/progress parsing (Linux)
  library_job.py              in-process spotdl download worker (Windows)
  config.py                    tiny JSON settings store (shared)
data/
  io.github.spotdl_ui.svg          app icon
  io.github.spotdl_ui.desktop.in    desktop entry template (path filled in by install.sh)
.github/workflows/
  build-windows.yml         builds SpotDL-UI.exe on every push to main via GitHub Actions
install.sh / uninstall.sh
```
