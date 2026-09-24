"""Runs `spotdl` as a subprocess in a background thread and streams its
progress back to the caller in near real time.

Why a subprocess instead of importing spotdl as a library:
  - it is the exact same code path the `spotdl` CLI itself uses, so output
    formatting is stable and well understood (`--simple-tui` prints
    `"<song>: <status>"` lines and `"<done>/<total> complete"` summaries),
  - it gives us a real OS process we can cleanly cancel (terminate the whole
    process group, including any ffmpeg children) instead of trying to
    interrupt spotdl's internal asyncio event loop from a worker thread.

This module has no GUI toolkit dependency: `on_log`/`on_progress`/`on_finished`
are called directly from the worker thread, so callers (GTK's `window.py`,
the Windows Qt front end, ...) are responsible for marshaling those calls
onto their own UI thread themselves (e.g. by wrapping the callbacks with
`GLib.idle_add` or a Qt signal emission) before touching any widgets in them.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

# Matches a Spotify album link, in either URL or URI form, e.g.
#   https://open.spotify.com/album/4LH4d3cOWNNsVw41Gqt2kv
#   https://open.spotify.com/intl-de/album/4LH4d3cOWNNsVw41Gqt2kv
#   spotify:album:4LH4d3cOWNNsVw41Gqt2kv
_ALBUM_QUERY_RE = re.compile(
    r"open\.spotify\.com/(?:[\w-]+/)*album/[A-Za-z0-9]+|spotify:album:[A-Za-z0-9]+",
    re.IGNORECASE,
)

# Matches a Spotify playlist link, in either URL or URI form, e.g.
#   https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
#   https://open.spotify.com/intl-de/playlist/37i9dQZF1DXcBWIGoYBM5M
#   spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
_PLAYLIST_QUERY_RE = re.compile(
    r"open\.spotify\.com/(?:[\w-]+/)*playlist/[A-Za-z0-9]+|spotify:playlist:[A-Za-z0-9]+",
    re.IGNORECASE,
)


def _is_album_query(query: str) -> bool:
    return bool(_ALBUM_QUERY_RE.search(query))


def _is_playlist_query(query: str) -> bool:
    return bool(_PLAYLIST_QUERY_RE.search(query))

# Rough progress-percentage estimate per status word spotdl's simple TUI
# prints (see spotdl/download/progress_handler.py `SongTracker`). spotdl
# gives no numeric percentage in this output mode, so this is a smooth,
# monotonic approximation good enough for a live progress bar.
STATUS_PROGRESS = {
    "searching for song": 8,
    "getting audio meta": 20,
    "downloading": 45,
    "converting": 75,
    "embedding metadata": 90,
    "done": 100,
    "skipped": 100,
    "error": 100,
}

_SONG_STATUS_RE = re.compile(r"^(?P<song>.+?): (?P<status>[A-Za-z][A-Za-z0-9 ]*)$")
_OVERALL_RE = re.compile(r"^(?P<done>\d+)/(?P<total>\d+) complete$")


@dataclass
class DownloadResult:
    ok: bool
    cancelled: bool = False
    error: Optional[str] = None


@dataclass
class _Callbacks:
    on_log: Callable[[str, bool], None]
    on_progress: Callable[[int, int, str, int], None]
    on_finished: Callable[[DownloadResult], None]


class DownloadJob:
    """One spotdl invocation, running on its own thread."""

    def __init__(
        self,
        queries: List[str],
        output_dir: str,
        audio_format: str,
        bitrate: str,
        threads: int,
        overwrite: str,
        *,
        on_log: Callable[[str, bool], None],
        on_progress: Callable[[int, int, str, int], None],
        on_finished: Callable[[DownloadResult], None],
    ) -> None:
        self.queries = [q for q in queries if q.strip()]
        self.output_dir = output_dir
        self.audio_format = audio_format
        self.bitrate = bitrate
        self.threads = threads
        self.overwrite = overwrite
        self._cb = _Callbacks(on_log, on_progress, on_finished)

        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._cancelled = threading.Event()
        self._total_songs = 0
        self._done_songs = 0
        # Songs already accounted for by groups run before the current one
        # (see `_run`: albums and everything else are downloaded as
        # separate spotdl invocations, so counts have to be added up
        # across them for one continuous overall progress bar).
        self._done_offset = 0
        self._spawn_error: Optional[str] = None

    # -- public API ---------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Ask the running spotdl process (and its children) to stop.

        spotdl installs its own SIGTERM handler, but it can sit behind a
        blocking network call on a worker thread and take a long time (or
        occasionally never) to actually honour it. So: ask nicely first,
        then escalate to SIGKILL on a background timer if it hasn't exited
        after a short grace period. Never blocks the calling (GTK) thread.
        """

        self._cancelled.set()
        proc = self._process
        if proc is None or proc.poll() is not None:
            return

        self._send_signal(signal.SIGTERM)
        timer = threading.Timer(2.5, self._escalate_to_kill)
        timer.daemon = True
        timer.start()

    def _send_signal(self, sig: signal.Signals) -> None:
        proc = self._process
        if proc is None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(sig)
            except OSError:
                pass

    def _escalate_to_kill(self) -> None:
        proc = self._process
        if proc is not None and proc.poll() is None:
            self._send_signal(signal.SIGKILL)

    # -- worker thread --------------------------------------------------

    def _run(self) -> None:
        spotdl_bin = shutil.which("spotdl")
        if spotdl_bin is None:
            self._finish(DownloadResult(ok=False, error="spotdl is not installed or not on PATH."))
            return

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        flat_template = str(Path(self.output_dir) / "{artists} - {title}.{output-ext}")
        # Albums and playlists each get their own subfolder (named after the
        # album/playlist) inside the chosen output location, so a multi-track
        # album or playlist doesn't spill its tracks loose into the main
        # folder.
        album_template = str(Path(self.output_dir) / "{album}" / "{artists} - {title}.{output-ext}")
        playlist_template = str(Path(self.output_dir) / "{list-name}" / "{artists} - {title}.{output-ext}")

        album_queries = [q for q in self.queries if _is_album_query(q)]
        playlist_queries = [
            q for q in self.queries if _is_playlist_query(q) and not _is_album_query(q)
        ]
        other_queries = [
            q for q in self.queries if not _is_album_query(q) and not _is_playlist_query(q)
        ]

        groups: List[Tuple[List[str], str]] = []
        if album_queries:
            groups.append((album_queries, album_template))
        if playlist_queries:
            groups.append((playlist_queries, playlist_template))
        if other_queries:
            groups.append((other_queries, flat_template))

        if len(groups) > 1:
            self._cb.on_log(
                f"Downloading {len(album_queries)} album(s) and {len(playlist_queries)} "
                f"playlist(s) into their own folders, and {len(other_queries)} other "
                f"item(s) into {self.output_dir}",
                False,
            )

        overall_ok = True
        overall_error: Optional[str] = None

        for queries, output_template in groups:
            if self._cancelled.is_set():
                break

            return_code = self._run_group(spotdl_bin, queries, output_template)
            self._done_offset += self._total_songs

            if return_code is None:
                overall_ok = False
                overall_error = self._spawn_error
                break
            if self._cancelled.is_set():
                break
            if return_code != 0:
                overall_ok = False
                overall_error = f"spotdl exited with status {return_code}. See the log above for details."

        if self._cancelled.is_set():
            self._finish(DownloadResult(ok=False, cancelled=True))
        else:
            self._finish(DownloadResult(ok=overall_ok, error=overall_error))

    def _run_group(self, spotdl_bin: str, queries: List[str], output_template: str) -> Optional[int]:
        """Run one spotdl invocation for `queries`. Returns its exit code,
        or None if the process could not even be started."""

        self._total_songs = 0
        self._done_songs = 0

        args = [
            spotdl_bin,
            "download",
            *queries,
            "--simple-tui",
            "--log-level",
            "INFO",
            "--output",
            output_template,
            "--format",
            self.audio_format,
            "--threads",
            str(self.threads),
            "--overwrite",
            self.overwrite,
        ]
        if self.bitrate and self.bitrate != "auto":
            args += ["--bitrate", self.bitrate]

        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            self._spawn_error = f"Could not start spotdl: {exc}"
            return None

        assert self._process.stdout is not None
        for raw_line in self._process.stdout:
            # spotdl's rich-based console can pad lines with trailing spaces
            # (terminal-width justification) even when writing to a pipe, so
            # strip all trailing whitespace, not just the line ending, or the
            # `$`-anchored patterns below silently stop matching.
            line = raw_line.rstrip()
            if not line:
                continue
            self._handle_line(line)

        return self._process.wait()

    def _handle_line(self, line: str) -> None:
        is_error = False

        overall_match = _OVERALL_RE.match(line)
        song_match = _SONG_STATUS_RE.match(line) if overall_match is None else None

        if overall_match:
            self._done_songs = int(overall_match.group("done"))
            self._total_songs = int(overall_match.group("total"))
            self._emit_progress(current_song="", pct=100)
        elif song_match:
            status = song_match.group("status").strip()
            song = song_match.group("song").strip()
            pct = STATUS_PROGRESS.get(status.lower(), 50)
            is_error = status.lower() == "error"
            self._emit_progress(current_song=f"{song} — {status}", pct=pct)
        else:
            is_error = "error" in line.lower() or "traceback" in line.lower()

        self._cb.on_log(line, is_error)

    def _emit_progress(self, current_song: str, pct: int) -> None:
        self._cb.on_progress(
            self._done_offset + self._done_songs,
            self._done_offset + self._total_songs,
            current_song,
            pct,
        )

    def _finish(self, result: DownloadResult) -> None:
        self._cb.on_finished(result)
