"""Entry point for the PyInstaller-built Windows executable.

Kept as a plain top-level script (rather than `python -m spotdl_ui.qt_app`)
because PyInstaller needs a concrete script file to point at.
"""

import sys

from spotdl_ui.qt_app import main

if __name__ == "__main__":
    sys.exit(main())
