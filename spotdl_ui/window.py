"""Main window for SpotDL UI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import config
from .download_job import DownloadJob, DownloadResult

FORMATS = ["mp3", "flac", "ogg", "opus", "m4a", "wav"]
BITRATES = ["auto", "128k", "160k", "192k", "256k", "320k"]
OVERWRITE_MODES = [
    ("skip", "Skip existing files"),
    ("force", "Overwrite existing files"),
    ("metadata", "Update metadata only"),
]


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="SpotDL UI")
        self.set_default_size(760, 820)
        self.set_size_request(440, 560)

        self.settings = config.load()
        self.output_dir = self.settings["output_dir"]
        self._job: Optional[DownloadJob] = None
        self._last_logged_current: str = ""

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(toolbar_view)

        toolbar_view.add_top_bar(self._build_header_bar())

        self.dependency_banner = Adw.Banner(title="")
        self.dependency_banner.connect("button-clicked", self._on_banner_button_clicked)
        toolbar_view.add_top_bar(self.dependency_banner)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view.set_content(scroller)

        clamp = Adw.Clamp(maximum_size=640, tightening_threshold=480)
        clamp.set_margin_top(24)
        clamp.set_margin_bottom(24)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scroller.set_child(clamp)

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        clamp.set_child(root_box)

        root_box.append(self._build_source_group())
        root_box.append(self._build_options_group())
        root_box.append(self._build_output_group())
        root_box.append(self._build_action_row())
        root_box.append(self._build_progress_group())

        self._check_dependencies()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_header_bar(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="SpotDL UI", subtitle="Download music from Spotify")
        header.set_title_widget(title)

        open_folder_btn = Gtk.Button(icon_name="folder-open-symbolic")
        open_folder_btn.set_tooltip_text("Open the output folder")
        open_folder_btn.connect("clicked", self._on_open_folder_clicked)
        header.pack_start(open_folder_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_tooltip_text("Main menu")
        menu = Gio.Menu()
        menu.append("About SpotDL UI", "app.about")
        menu_btn.set_menu_model(menu)
        header.pack_end(menu_btn)

        return header

    def _build_source_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="What to download",
            description="One Spotify track, album, playlist or search term per line.",
        )

        frame = Gtk.Frame()
        frame.add_css_class("card")

        self.query_view = Gtk.TextView()
        self.query_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.query_view.set_top_margin(10)
        self.query_view.set_bottom_margin(10)
        self.query_view.set_left_margin(10)
        self.query_view.set_right_margin(10)
        self.query_view.set_accepts_tab(False)

        query_scroller = Gtk.ScrolledWindow(has_frame=False)
        query_scroller.set_min_content_height(110)
        query_scroller.set_max_content_height(220)
        query_scroller.set_child(self.query_view)

        frame.set_child(query_scroller)
        group.add(frame)
        return group

    def _build_options_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Options")

        self.format_row = Adw.ComboRow(title="Audio format")
        self.format_row.set_model(Gtk.StringList.new(FORMATS))
        self.format_row.set_selected(
            FORMATS.index(self.settings["format"]) if self.settings["format"] in FORMATS else 0
        )
        group.add(self.format_row)

        self.bitrate_row = Adw.ComboRow(title="Bitrate")
        self.bitrate_row.set_subtitle("Ignored for lossless formats like FLAC/WAV")
        self.bitrate_row.set_model(Gtk.StringList.new(BITRATES))
        self.bitrate_row.set_selected(
            BITRATES.index(self.settings["bitrate"]) if self.settings["bitrate"] in BITRATES else 5
        )
        group.add(self.bitrate_row)

        self.threads_row = Adw.SpinRow.new_with_range(1, 16, 1)
        self.threads_row.set_title("Parallel downloads")
        self.threads_row.set_subtitle("How many tracks to fetch at once")
        self.threads_row.set_value(self.settings["threads"])
        group.add(self.threads_row)

        overwrite_keys = [key for key, _ in OVERWRITE_MODES]
        self.overwrite_row = Adw.ComboRow(title="If a file already exists")
        self.overwrite_row.set_model(Gtk.StringList.new([label for _, label in OVERWRITE_MODES]))
        self.overwrite_row.set_selected(
            overwrite_keys.index(self.settings["overwrite"])
            if self.settings["overwrite"] in overwrite_keys
            else 0
        )
        group.add(self.overwrite_row)

        return group

    def _build_output_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Output location")

        self.output_row = Adw.ActionRow(title="Save to")
        self.output_row.set_subtitle(self.output_dir)
        self.output_row.set_subtitle_lines(1)
        icon = Gtk.Image.new_from_icon_name("folder-symbolic")
        self.output_row.add_prefix(icon)

        browse_btn = Gtk.Button(icon_name="folder-open-symbolic")
        browse_btn.set_tooltip_text("Choose folder")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.add_css_class("flat")
        browse_btn.connect("clicked", self._on_browse_clicked)

        new_folder_btn = Gtk.Button(icon_name="folder-new-symbolic")
        new_folder_btn.set_tooltip_text("Create new folder here")
        new_folder_btn.set_valign(Gtk.Align.CENTER)
        new_folder_btn.add_css_class("flat")
        new_folder_btn.connect("clicked", self._on_new_folder_clicked)

        self.output_row.add_suffix(new_folder_btn)
        self.output_row.add_suffix(browse_btn)
        group.add(self.output_row)
        return group

    def _build_action_row(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_margin_top(4)

        self.download_btn = Gtk.Button(label="Download")
        self.download_btn.add_css_class("suggested-action")
        self.download_btn.add_css_class("pill")
        self.download_btn.set_size_request(160, -1)
        self.download_btn.connect("clicked", self._on_download_clicked)

        self.cancel_btn = Gtk.Button(label="Cancel")
        self.cancel_btn.add_css_class("destructive-action")
        self.cancel_btn.add_css_class("pill")
        self.cancel_btn.set_sensitive(False)
        self.cancel_btn.connect("clicked", self._on_cancel_clicked)

        box.append(self.download_btn)
        box.append(self.cancel_btn)
        return box

    def _build_progress_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Progress")

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.add_css_class("card")
        container.set_margin_top(6)
        container.set_margin_bottom(12)
        container.set_margin_start(12)
        container.set_margin_end(12)

        self.overall_label = Gtk.Label(label="Ready", xalign=0)
        self.overall_label.add_css_class("heading")

        self.overall_bar = Gtk.ProgressBar()
        self.overall_bar.set_show_text(False)

        self.current_label = Gtk.Label(label="", xalign=0)
        self.current_label.add_css_class("dim-label")
        self.current_label.set_ellipsize(Pango.EllipsizeMode.END)

        self.current_bar = Gtk.ProgressBar()
        self.current_bar.set_show_text(False)

        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header_box.set_margin_top(12)
        header_box.set_margin_start(12)
        header_box.set_margin_end(12)
        header_box.append(self.overall_label)
        header_box.append(self.overall_bar)
        header_box.append(self.current_label)
        header_box.append(self.current_bar)
        container.append(header_box)

        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.set_editable(False)
        self.log_view.set_cursor_visible(False)
        self.log_view.set_monospace(True)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_view.set_top_margin(8)
        self.log_view.set_bottom_margin(8)
        self.log_view.set_left_margin(8)
        self.log_view.set_right_margin(8)
        self.log_view.add_css_class("log-view")

        self._error_tag = self.log_buffer.create_tag("error", foreground="#e01b24")

        log_scroller = Gtk.ScrolledWindow(has_frame=False)
        log_scroller.set_min_content_height(220)
        log_scroller.set_vexpand(True)
        log_scroller.set_child(self.log_view)

        log_frame = Gtk.Frame()
        log_frame.add_css_class("view")
        log_frame.set_margin_start(12)
        log_frame.set_margin_end(12)
        log_frame.set_margin_bottom(12)
        log_frame.set_child(log_scroller)
        container.append(log_frame)

        group.add(container)
        return group

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------

    def _check_dependencies(self) -> None:
        missing = []
        if shutil.which("spotdl") is None:
            missing.append("spotdl")
        if shutil.which("ffmpeg") is None:
            missing.append("ffmpeg")

        if not missing:
            self.dependency_banner.set_revealed(False)
            return

        if missing == ["spotdl"]:
            text = "spotdl was not found on your PATH."
            action = "Install spotdl"
        elif missing == ["ffmpeg"]:
            text = "ffmpeg was not found. Audio conversion will fail."
            action = "How to install"
        else:
            text = "spotdl and ffmpeg were not found."
            action = "How to install"

        self.dependency_banner.set_title(text)
        self.dependency_banner.set_button_label(action)
        self.dependency_banner.set_revealed(True)

    def _on_banner_button_clicked(self, _banner: Adw.Banner) -> None:
        self._append_log(
            "Install spotdl with:  pip install --user spotdl\n"
            "Install ffmpeg on Fedora with:  sudo dnf install ffmpeg   (needs RPM Fusion)\n"
            "Or let spotdl fetch its own copy with:  spotdl --download-ffmpeg",
            is_error=False,
        )
        self._toast("Instructions added to the log below")

    # ------------------------------------------------------------------
    # Output folder: browse + create
    # ------------------------------------------------------------------

    def _on_open_folder_clicked(self, _btn: Gtk.Button) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        try:
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(self.output_dir).get_uri())
        except GLib.Error as exc:
            self._toast(f"Couldn't open folder: {exc.message}")

    def _on_browse_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Choose output folder")
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        dialog.set_initial_folder(Gio.File.new_for_path(self.output_dir))
        dialog.select_folder(self, None, self._on_browse_finished)

    def _on_browse_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return  # user cancelled
        if folder is None:
            return
        path = folder.get_path()
        if path:
            self._set_output_dir(path)

    def _on_new_folder_clicked(self, _btn: Gtk.Button) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading("New folder")
        dialog.set_body(f"Create a new folder inside:\n{self.output_dir}")

        entry = Adw.EntryRow(title="Folder name")
        entry.set_show_apply_button(False)
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.append(entry)
        dialog.set_extra_child(listbox)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        def on_response(dlg: Adw.AlertDialog, response: str) -> None:
            if response != "create":
                return
            name = entry.get_text().strip()
            if not name:
                self._toast("Folder name can't be empty")
                return
            if "/" in name:
                self._toast("Folder name can't contain '/'")
                return
            new_path = Path(self.output_dir) / name
            try:
                new_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._toast(f"Couldn't create folder: {exc}")
                return
            self._set_output_dir(str(new_path))
            self._toast(f"Created “{name}” and set it as the output folder")

        dialog.connect("response", on_response)
        dialog.present(self)
        entry.grab_focus()

    def _set_output_dir(self, path: str) -> None:
        self.output_dir = path
        self.output_row.set_subtitle(path)
        self.settings["output_dir"] = path
        config.save(self.settings)

    # ------------------------------------------------------------------
    # Download lifecycle
    # ------------------------------------------------------------------

    def _on_download_clicked(self, _btn: Gtk.Button) -> None:
        if self._job is not None:
            return

        start, end = self.query_view.get_buffer().get_bounds()
        text = self.query_view.get_buffer().get_text(start, end, False)
        queries = [line.strip() for line in text.splitlines() if line.strip()]
        if not queries:
            self._toast("Add at least one Spotify link or search term first")
            return

        if shutil.which("spotdl") is None:
            self._toast("spotdl is not installed - see the log for install instructions")
            self._check_dependencies()
            return

        audio_format = FORMATS[self.format_row.get_selected()]
        bitrate = BITRATES[self.bitrate_row.get_selected()]
        threads = int(self.threads_row.get_value())
        overwrite = OVERWRITE_MODES[self.overwrite_row.get_selected()][0]

        self.settings.update(
            {
                "format": audio_format,
                "bitrate": bitrate,
                "threads": threads,
                "overwrite": overwrite,
                "output_dir": self.output_dir,
            }
        )
        config.save(self.settings)

        self.log_buffer.set_text("")
        self._last_logged_current = ""
        self.overall_bar.set_fraction(0.0)
        self.current_bar.set_fraction(0.0)
        self.overall_label.set_label(f"Starting — {len(queries)} item(s) queued…")
        self.current_label.set_label("")

        self.download_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(True)

        # DownloadJob calls these from its worker thread; GTK widgets may
        # only be touched from the main loop, so marshal each call via
        # GLib.idle_add before it ever reaches a widget.
        self._job = DownloadJob(
            queries=queries,
            output_dir=self.output_dir,
            audio_format=audio_format,
            bitrate=bitrate,
            threads=threads,
            overwrite=overwrite,
            on_log=lambda line, is_error: GLib.idle_add(self._append_log, line, is_error),
            on_progress=lambda done, total, current, pct: GLib.idle_add(
                self._on_progress, done, total, current, pct
            ),
            on_finished=lambda result: GLib.idle_add(self._on_finished, result),
        )
        self._job.start()

    def _on_cancel_clicked(self, _btn: Gtk.Button) -> None:
        if self._job is None:
            return
        self.cancel_btn.set_sensitive(False)
        self.overall_label.set_label("Cancelling…")
        self._job.cancel()

    def _on_progress(self, done: int, total: int, current: str, pct: int) -> bool:
        if total > 0:
            self.overall_bar.set_fraction(done / total)
            self.overall_label.set_label(f"{done} / {total} tracks complete")
        if current:
            self.current_label.set_label(current)
            self.current_bar.set_fraction(pct / 100)
        return GLib.SOURCE_REMOVE

    def _on_finished(self, result: DownloadResult) -> bool:
        self._job = None
        self.download_btn.set_sensitive(True)
        self.cancel_btn.set_sensitive(False)
        self.current_bar.set_fraction(0.0)

        if result.cancelled:
            self.overall_label.set_label("Cancelled")
            self._toast("Download cancelled")
        elif result.ok:
            self.overall_bar.set_fraction(1.0)
            self.overall_label.set_label("All done")
            self.current_label.set_label("")
            self._toast("Download complete")
        else:
            self.overall_label.set_label("Finished with errors")
            self._toast(result.error or "spotdl reported an error - check the log")

        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_log(self, line: str, is_error: bool) -> bool:
        end_iter = self.log_buffer.get_end_iter()
        if is_error:
            self.log_buffer.insert_with_tags(end_iter, line + "\n", self._error_tag)
        else:
            self.log_buffer.insert(end_iter, line + "\n")

        mark = self.log_buffer.get_insert()
        self.log_buffer.place_cursor(self.log_buffer.get_end_iter())
        self.log_view.scroll_mark_onscreen(mark)
        return GLib.SOURCE_REMOVE

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=4))

    def do_close_request(self) -> bool:  # noqa: N802 - GTK virtual method name
        if self._job is not None:
            self._job.cancel()
        return False
