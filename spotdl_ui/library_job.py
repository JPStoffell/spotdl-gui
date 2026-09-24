"""Runs spotdl as an in-process library, in a background thread, for the
Windows/Qt front end.

The Linux front end (`window.py`) shells out to the real `spotdl` CLI
(`download_job.py`) - that gives it a real OS process it can cleanly cancel,
and it's a fair assumption that a Fedora user has (or can easily get) `spotdl`
and `ffmpeg` on their PATH.

Neither assumption holds for a portable Windows .exe someone downloads and
just double-clicks: there is no separate `spotdl` install to shell out to
once this app is frozen by PyInstaller, and no expectation that ffmpeg is
already on PATH. So this front end instead imports `spotdl` as a library
(bundled straight into the executable) and calls `download_ffmpeg()` itself
on first run if needed - exactly what spotdl's own CLI does before handing
off to the downloader.

The trade-off is cancellation: spotdl's `Spotdl.download_songs()` runs its
own asyncio event loop synchronously to completion for the whole batch it's
given, so there's no clean way to interrupt it mid-song from another thread.
`cancel()` here only takes effect between queries (i.e. it will finish
whatever playlist/album/song is currently in flight, then stop before
starting the next one) - callers should surface that in the UI rather than
implying an instant stop.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .download_job import DownloadResult

# Rough progress-percentage estimate per status word spotdl's progress
# handler reports (see spotdl/download/progress_handler.py `SongTracker`).
# Mirrors STATUS_PROGRESS in download_job.py so both front ends feel the same.
STATUS_PROGRESS = {
    "searching for song": 8,
    "getting audio meta": 20,
    "downloading": 45,
    "converting": 75,
    "embedding metadata": 90,
    "download error": 100,
    "error": 100,
}


@dataclass
class _Callbacks:
    on_log: Callable[[str, bool], None]
    on_progress: Callable[[int, int, str, int], None]
    on_finished: Callable[[DownloadResult], None]


# spotdl's SpotifyClient is a process-wide singleton (SpotifyClient.init()
# raises if called twice), so the Spotdl instance is created once, lazily,
# and reused across every LibraryDownloadJob for the life of the process.
_spotdl_instance = None
_spotdl_lock = threading.Lock()


class LibraryDownloadJob:
    """One spotdl library download run, on its own thread.

    Same public shape as `DownloadJob` in `download_job.py` (queries,
    output_dir, audio_format, bitrate, threads, overwrite, on_log,
    on_progress, on_finished, start(), cancel()) so the Qt window can be
    built the same way the GTK window is.
    """

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

        self._thread: Optional[threading.Thread] = None
        self._cancelled = threading.Event()
        self._done_songs = 0
        self._total_songs = 0

    # -- public API ---------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Stop before the next queued query starts. See module docstring:
        this can't interrupt a query that's already downloading."""
        self._cancelled.set()

    # -- worker thread --------------------------------------------------

    def _run(self) -> None:
        try:
            from spotdl.utils.ffmpeg import download_ffmpeg, is_ffmpeg_installed

            if not is_ffmpeg_installed():
                self._cb.on_log("ffmpeg not found - downloading a copy (one-time)...", False)
                try:
                    download_ffmpeg()
                    self._cb.on_log("ffmpeg downloaded.", False)
                except Exception as exc:  # noqa: BLE001 - surface any failure to the log
                    self._finish(DownloadResult(ok=False, error=f"Could not download ffmpeg: {exc}"))
                    return

            spotdl = self._get_spotdl()
        except Exception as exc:  # noqa: BLE001 - spotdl/ffmpeg setup failure
            self._finish(DownloadResult(ok=False, error=str(exc)))
            return

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        output_template = str(
            Path(self.output_dir) / "{list-name}" / "{artists} - {title}.{output-ext}"
        )

        spotdl.downloader.settings["output"] = output_template
        spotdl.downloader.settings["format"] = self.audio_format
        spotdl.downloader.settings["overwrite"] = self.overwrite
        spotdl.downloader.settings["threads"] = self.threads
        # Downloader.__init__ builds its concurrency semaphore once from
        # settings["threads"] at construction time and never re-reads it, so
        # just setting the dict entry above has no effect on an already-built
        # Downloader (this job reuses one singleton Spotdl/Downloader across
        # every run - see _get_spotdl). Rebuild the semaphore directly so the
        # thread count the user picked for *this* run actually takes effect.
        spotdl.downloader.semaphore = asyncio.Semaphore(self.threads)
        if self.bitrate and self.bitrate != "auto":
            spotdl.downloader.settings["bitrate"] = self.bitrate
        else:
            spotdl.downloader.settings["bitrate"] = None
        spotdl.downloader.progress_handler.update_callback = self._on_song_progress

        overall_ok = True
        overall_error: Optional[str] = None

        for query in self.queries:
            if self._cancelled.is_set():
                break

            self._total_songs = 0
            self._done_songs = 0
            try:
                songs = spotdl.search([query])
                self._total_songs = len(songs)
                self._emit_progress("", 0)

                results = spotdl.download_songs(songs)
                failed = [song.display_name for song, path in results if path is None]
                if failed:
                    overall_ok = False
                    overall_error = f"{len(failed)} track(s) failed - see the log above."
                    self._cb.on_log(f"Failed: {', '.join(failed)}", True)
            except Exception as exc:  # noqa: BLE001 - keep going with the next query
                overall_ok = False
                overall_error = str(exc)
                self._cb.on_log(f"Error downloading {query}: {exc}", True)

        if self._cancelled.is_set():
            self._finish(DownloadResult(ok=False, cancelled=True))
        else:
            self._finish(DownloadResult(ok=overall_ok, error=overall_error))

    def _get_spotdl(self):
        global _spotdl_instance
        with _spotdl_lock:
            if _spotdl_instance is None:
                from spotdl import Spotdl

                self._cb.on_log("Starting spotdl - first run may take a moment...", False)
                _spotdl_instance = Spotdl(
                    client_id="",
                    client_secret="",
                    user_auth=False,
                    cache_path=str(Path(self.output_dir) / ".spotdl-cache"),
                    downloader_settings={"simple_tui": True},
                    no_cache=True,
                )
            return _spotdl_instance

    def _on_song_progress(self, tracker, message: str) -> None:
        """Called by spotdl (from this worker thread) as each song progresses."""
        status = message.strip()
        if status.lower() in ("done", "skipped"):
            self._done_songs += 1
        pct = STATUS_PROGRESS.get(status.lower(), 50)
        is_error = "error" in status.lower()
        self._cb.on_log(f"{tracker.song_name}: {status}", is_error)
        self._emit_progress(f"{tracker.song_name} — {status}", pct)

    def _emit_progress(self, current_song: str, pct: int) -> None:
        self._cb.on_progress(self._done_songs, self._total_songs, current_song, pct)

    def _finish(self, result: DownloadResult) -> None:
        self._cb.on_finished(result)
