"""Application entry point for SpotDL UI."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .window import MainWindow  # noqa: E402

APP_ID = "io.github.spotdl_ui"


class SpotdlUiApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self._window: MainWindow | None = None

        self._add_action("about", self._on_about)
        self._add_action("quit", self._on_quit, accels=["<primary>q"])

        self.set_accels_for_action("app.quit", ["<primary>q"])

    def do_startup(self) -> None:  # noqa: N802 - GTK virtual method name
        Adw.Application.do_startup(self)
        self._load_css()

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_string(
            """
            .log-view {
                font-family: monospace;
                font-size: 0.9em;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _add_action(self, name: str, callback, accels=None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accels:
            self.set_accels_for_action(f"app.{name}", accels)

    def do_activate(self) -> None:  # noqa: N802 - GTK virtual method name
        if self._window is None:
            self._window = MainWindow(self)
        self._window.present()

    def _on_quit(self, *_args) -> None:
        self.quit()

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name="SpotDL UI",
            application_icon=APP_ID,
            version=__version__,
            developer_name="You",
            comments="A clean, modern front end for spotdl, the Spotify command-line downloader.",
            website="https://github.com/spotDL/spotify-downloader",
            issue_url="https://github.com/spotDL/spotify-downloader/issues",
            license_type=Gtk.License.MIT_X11,
            developers=["Built with Claude Code"],
        )
        about.add_credit_section("Powered by", ["spotDL — github.com/spotDL/spotify-downloader"])
        about.present(self._window)


def main() -> int:
    app = SpotdlUiApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
