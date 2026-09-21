"""
SpotDL GUI - GTK Version for Linux
A beautiful desktop application for downloading Spotify playlists
"""

import sys
import os
import re
import json
import threading
from pathlib import Path
from datetime import datetime

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gio

try:
    from spotdl import Spotdl
except ImportError:
    print("Error: spotdl not installed. Install with: pip install spotdl yt-dlp")
    sys.exit(1)


# spotdl (with --simple-tui) logs "<song>: <stage>" as each song moves through
# these stages, in order, followed immediately by "<done>/<total> complete".
# "Done" is intentionally excluded: it's immediately followed by the "complete"
# line, which is the authoritative progress signal (it accounts for playlist
# size, which isn't known until the first song finishes).
STAGE_ORDER = [
    "Searching for song",
    "Getting audio meta",
    "Downloading",
    "Converting",
    "Embedding metadata",
]
_COMPLETE_RE = re.compile(r'^(\d+)/(\d+) complete$')
_STAGE_RE = re.compile(r'^.+: (.+)$')
_DOWNLOAD_TIMEOUT = 600


class DownloadThread(threading.Thread):
    """Worker thread for downloads"""

    def __init__(self, urls, output_path, settings, callback):
        super().__init__(daemon=True)
        self.urls = urls
        self.output_path = output_path
        self.settings = settings
        self.callback = callback
        self.is_running = True

    def run(self):
        import subprocess
        import time

        try:
            if not os.path.exists(self.output_path):
                os.makedirs(self.output_path)

            self.callback("log", f"[{datetime.now().strftime('%H:%M:%S')}] Starting download...\n")

            for url in self.urls:
                if not self.is_running:
                    break

                self.callback("status", f"Downloading: {url[:50]}...")
                self.callback("log", f"[{datetime.now().strftime('%H:%M:%S')}] Downloading: {url}\n")
                self.callback("progress", 0)

                try:
                    cmd = ['spotdl', 'download', url, '--output', self.output_path, '--simple-tui']
                    process = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1
                    )

                    start_time = time.monotonic()
                    total_songs = None

                    for line in process.stdout:
                        if not self.is_running:
                            process.terminate()
                            break

                        if time.monotonic() - start_time > _DOWNLOAD_TIMEOUT:
                            process.terminate()
                            self.callback("log", "✗ Error: download timed out\n")
                            break

                        line = line.rstrip("\n")
                        if not line:
                            continue
                        self.callback("log", line + "\n")

                        complete_match = _COMPLETE_RE.match(line)
                        if complete_match:
                            completed, total_songs = int(complete_match.group(1)), int(complete_match.group(2))
                            self.callback("progress", completed / total_songs * 100)
                            continue

                        # Once a playlist's song count is known, per-song stage
                        # progress would regress the overall bar, so ignore it.
                        if total_songs is None or total_songs <= 1:
                            stage_match = _STAGE_RE.match(line)
                            if stage_match and stage_match.group(1) in STAGE_ORDER:
                                stage_pct = (STAGE_ORDER.index(stage_match.group(1)) + 1) / len(STAGE_ORDER) * 100
                                self.callback("progress", stage_pct)

                    returncode = process.wait(timeout=30)

                    if returncode == 0:
                        self.callback("log", f"✓ Downloaded successfully!\n")
                    else:
                        self.callback("log", f"✗ Error: spotdl exited with code {returncode}\n")

                    self.callback("progress", 100)

                except Exception as e:
                    self.callback("log", f"✗ Error: {str(e)}\n")

            self.callback("log", f"\n[{datetime.now().strftime('%H:%M:%S')}] Download complete!\n")
            self.callback("status", "Ready")
            self.callback("finished", True)

        except Exception as e:
            self.callback("log", f"\n[{datetime.now().strftime('%H:%M:%S')}] ERROR: {str(e)}\n")
            self.callback("status", "Error")
            self.callback("finished", False)

    def stop(self):
        self.is_running = False


class SpotDLGUI(Gtk.ApplicationWindow):
    """Main application window"""
    
    def __init__(self, app):
        super().__init__(application=app)
        
        self.set_title("SpotDL - Spotify Downloader")
        self.set_default_size(900, 700)
        self.set_modal(False)
        
        # Settings
        self.output_path = str(Path.home() / "Music" / "SpotDL Downloads")
        self.download_thread = None
        self.settings = {
            'output_format': '{artist} - {title}.mp3',
            'skip_existing': True,
        }
        
        self.load_settings()
        self.build_ui()
    
    def build_ui(self):
        """Build the user interface"""
        
        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Header bar
        header = Gtk.HeaderBar()
        title_label = Gtk.Label(label="SpotDL - Spotify Downloader")
        title_label.add_css_class("title")
        header.set_title_widget(title_label)
        main_box.append(header)
        
        # Notebook (tabs)
        notebook = Gtk.Notebook()
        main_box.append(notebook)
        
        # Download tab
        download_box = self.create_download_tab()
        notebook.append_page(download_box, Gtk.Label(label="Download"))
        
        # Settings tab
        settings_box = self.create_settings_tab()
        notebook.append_page(settings_box, Gtk.Label(label="Settings"))
    
    def create_download_tab(self):
        """Create the download tab"""
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Title
        title = Gtk.Label(label="Spotify Playlist Downloader")
        title.add_css_class("title-2")
        box.append(title)
        
        # URL input
        url_label = Gtk.Label(label="Paste Spotify URL:")
        url_label.set_halign(Gtk.Align.START)
        box.append(url_label)
        
        self.url_input = Gtk.Entry()
        self.url_input.set_placeholder_text("https://open.spotify.com/playlist/...")
        box.append(self.url_input)
        
        # Output folder
        folder_label = Gtk.Label(label="Output Location:")
        folder_label.set_halign(Gtk.Align.START)
        box.append(folder_label)
        
        folder_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.folder_label = Gtk.Label(label=self.output_path)
        self.folder_label.set_wrap(True)
        self.folder_label.set_halign(Gtk.Align.START)
        folder_box.append(self.folder_label)
        
        browse_btn = Gtk.Button(label="Browse...")
        browse_btn.connect("clicked", self.on_browse)
        folder_box.append(browse_btn)

        new_folder_btn = Gtk.Button(label="New Folder...")
        new_folder_btn.connect("clicked", self.on_new_folder)
        folder_box.append(new_folder_btn)

        box.append(folder_box)
        
        # Progress
        progress_label = Gtk.Label(label="Progress:")
        progress_label.set_halign(Gtk.Align.START)
        box.append(progress_label)
        
        self.progress_bar = Gtk.ProgressBar()
        box.append(self.progress_bar)
        
        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_halign(Gtk.Align.START)
        box.append(self.status_label)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        self.download_btn = Gtk.Button(label="Download")
        self.download_btn.connect("clicked", self.on_download)
        button_box.append(self.download_btn)
        
        self.stop_btn = Gtk.Button(label="Stop")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self.on_stop)
        button_box.append(self.stop_btn)
        
        open_btn = Gtk.Button(label="Open Folder")
        open_btn.connect("clicked", self.on_open_folder)
        button_box.append(open_btn)
        
        box.append(button_box)
        
        # Log output
        log_label = Gtk.Label(label="Activity Log:")
        log_label.set_halign(Gtk.Align.START)
        box.append(log_label)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.log_output = Gtk.TextView()
        self.log_output.set_editable(False)
        self.log_output.set_monospace(True)
        self.log_output.set_margin_top(6)
        self.log_output.set_margin_bottom(6)
        self.log_output.set_margin_start(6)
        self.log_output.set_margin_end(6)
        scroll.set_child(self.log_output)
        box.append(scroll)
        
        return box
    
    def create_settings_tab(self):
        """Create the settings tab"""
        
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        
        # Title
        title = Gtk.Label(label="Settings")
        title.add_css_class("title-2")
        box.append(title)
        
        # Output format
        format_label = Gtk.Label(label="Filename template:")
        format_label.set_halign(Gtk.Align.START)
        box.append(format_label)
        
        self.format_input = Gtk.Entry()
        self.format_input.set_text(self.settings['output_format'])
        box.append(self.format_input)
        
        help_text = Gtk.Label(label="Variables: {artist}, {title}, {album}, {date}")
        help_text.set_halign(Gtk.Align.START)
        help_text.add_css_class("dim-label")
        box.append(help_text)
        
        # Checkboxes
        self.skip_checkbox = Gtk.CheckButton(label="Skip existing files")
        self.skip_checkbox.set_active(self.settings['skip_existing'])
        box.append(self.skip_checkbox)
        
        # Buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        save_btn = Gtk.Button(label="Save Settings")
        save_btn.connect("clicked", self.on_save_settings)
        button_box.append(save_btn)
        
        reset_btn = Gtk.Button(label="Reset to Default")
        reset_btn.connect("clicked", self.on_reset_settings)
        button_box.append(reset_btn)
        
        box.append(button_box)
        box.append(Gtk.Box())  # Spacer
        
        return box
    
    def on_browse(self, widget):
        """Open folder dialog"""
        dialog = Gtk.FileChooserDialog(
            title="Select Output Folder",
            action=Gtk.FileChooserAction.SELECT_FOLDER
        )
        dialog.set_transient_for(self)
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Open", Gtk.ResponseType.OK
        )
        
        def on_response(dialog, response_id):
            if response_id == Gtk.ResponseType.OK:
                self.output_path = dialog.get_file().get_path()
                self.folder_label.set_label(self.output_path)
            dialog.destroy()
        
        dialog.connect("response", on_response)
        dialog.present()

    def on_new_folder(self, widget):
        """Create a new subfolder inside the current output location"""
        dialog = Gtk.Dialog(title="New Folder", modal=True)
        dialog.set_transient_for(self)
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL,
            "_Create", Gtk.ResponseType.OK
        )
        dialog.set_default_response(Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_spacing(6)

        label = Gtk.Label(label=f"Create new folder in:\n{self.output_path}")
        label.set_halign(Gtk.Align.START)
        label.set_wrap(True)
        content.append(label)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Folder name")
        entry.set_activates_default(True)
        content.append(entry)

        def on_response(dialog, response_id):
            if response_id != Gtk.ResponseType.OK:
                dialog.destroy()
                return

            name = entry.get_text().strip()
            dialog.destroy()

            if not name:
                return

            if os.sep in name or (os.altsep and os.altsep in name):
                self.show_message_dialog(
                    Gtk.MessageType.WARNING, "Invalid Name",
                    "Folder name can't contain a path separator"
                )
                return

            new_path = os.path.join(self.output_path, name)
            try:
                os.makedirs(new_path, exist_ok=True)
            except OSError as e:
                self.show_message_dialog(
                    Gtk.MessageType.WARNING, "Couldn't Create Folder", str(e)
                )
                return

            self.output_path = new_path
            self.folder_label.set_label(self.output_path)

        dialog.connect("response", on_response)
        dialog.present()

    def show_message_dialog(self, message_type, text, secondary_text):
        """Show a non-blocking message dialog (GTK4 removed Dialog.run() and format_secondary_text())"""
        dialog = Gtk.MessageDialog(
            modal=True,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=text,
            secondary_text=secondary_text
        )
        dialog.set_transient_for(self)
        dialog.connect("response", lambda d, response_id: d.destroy())
        dialog.present()

    def on_download(self, widget):
        """Start download"""
        url = self.url_input.get_text().strip()

        if not url:
            self.show_message_dialog(
                Gtk.MessageType.WARNING, "Input Error", "Please enter a Spotify URL"
            )
            return
        
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
        
        self.download_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self.url_input.set_sensitive(False)
        self.progress_bar.set_fraction(0)
        self.log_output.get_buffer().set_text("")
        
        self.download_thread = DownloadThread(
            [url], self.output_path, self.settings,
            self.on_thread_event
        )
        self.download_thread.start()
    
    def on_stop(self, widget):
        """Stop download"""
        if self.download_thread:
            self.download_thread.stop()
        self.download_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.url_input.set_sensitive(True)
        self.append_log("[STOPPED] Download cancelled\n")
    
    def on_thread_event(self, event_type, data):
        """Handle events from download thread"""
        GLib.idle_add(self._handle_event, event_type, data)
    
    def _handle_event(self, event_type, data):
        """Handle thread events on main thread"""
        if event_type == "log":
            self.append_log(data)
        elif event_type == "progress":
            self.progress_bar.set_fraction(data / 100)
        elif event_type == "status":
            self.status_label.set_label(data)
        elif event_type == "finished":
            self.download_btn.set_sensitive(True)
            self.stop_btn.set_sensitive(False)
            self.url_input.set_sensitive(True)
            
            if data:
                self.show_message_dialog(
                    Gtk.MessageType.INFO, "Success", "Download completed!"
                )
        return False
    
    def append_log(self, text):
        """Append text to log"""
        buffer = self.log_output.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        self.log_output.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)
    
    def on_open_folder(self, widget):
        """Open output folder"""
        if os.path.exists(self.output_path):
            os.system(f'xdg-open "{self.output_path}"')
    
    def on_save_settings(self, widget):
        """Save settings"""
        self.settings['output_format'] = self.format_input.get_text()
        self.settings['skip_existing'] = self.skip_checkbox.get_active()
        
        settings_path = Path.home() / ".spotdl_gui" / "settings.json"
        settings_path.parent.mkdir(exist_ok=True)
        
        with open(settings_path, 'w') as f:
            json.dump(self.settings, f, indent=2)

        self.show_message_dialog(Gtk.MessageType.INFO, "Success", "Settings saved!")
    
    def on_reset_settings(self, widget):
        """Reset to default settings"""
        self.settings = {
            'output_format': '{artist} - {title}.mp3',
            'skip_existing': True,
        }
        self.format_input.set_text(self.settings['output_format'])
        self.skip_checkbox.set_active(self.settings['skip_existing'])
        self.on_save_settings(widget)
    
    def load_settings(self):
        """Load settings from file"""
        settings_path = Path.home() / ".spotdl_gui" / "settings.json"
        if settings_path.exists():
            try:
                with open(settings_path, 'r') as f:
                    loaded = json.load(f)
                    self.settings.update(loaded)
            except Exception:
                pass


class SpotDLApp(Gtk.Application):
    """Main application"""
    
    def __init__(self):
        super().__init__(application_id="com.spotdl.gui")
        self.connect("activate", self.on_activate)
    
    def on_activate(self, app):
        """Handle application activation"""
        window = SpotDLGUI(app)
        window.present()


def main():
    app = SpotDLApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    main()
