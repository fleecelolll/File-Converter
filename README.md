<div align="center">

# file converter

A little tool I made with AI to quickly convert common image, audio, video, archive, and script files locally on 64-bit Windows.

<img src="File%20Converter.png" alt="File Converter app window" width="760">

</div>

## features

- Convert common image, audio, video, archive, and script formats
- Preserve image animation when the output format supports it
- Copy compatible media streams without re-encoding
- Extract audio from video files
- Convert archives or create new archives from files and folders
- Swap BAT/CMD and PY/PYW extensions without changing file contents
- Choose the output folder and follow progress in the built-in log
- Process every file locally without uploads or telemetry

## requirements

- 64-bit x64 Windows
- An internet connection during first setup
- Enough free space for private Python, packages, and FFmpeg
- No internet connection while using the installed app

## installation

1. Download the latest release ZIP.
2. Extract the complete folder.
3. Double-click `Installer.bat`.
4. Press **Y** once to approve setup.
5. Leave the setup window open until every check passes.
6. Double-click the `File Converter` shortcut created in the folder.

Keep the full extracted folder path at 72 characters or fewer so Windows can install the private packages reliably.

Setup keeps the private Python runtime and all app-specific components inside the extracted folder. It does not require administrator access, change PATH, or install global Python packages. The shortcut starts the app with that private runtime, so Microsoft Store or system Python is not required.

Setup pins and verifies official Python 3.14.7, pip, PySide6-Essentials, Pillow, pillow-heif, py7zr, FFmpeg, and FFprobe. Downloaded runtime archives are checked against pinned SHA-256 hashes before use.

Setup also installs one small shared per-user launcher in `%LOCALAPPDATA%\Fleece Tools\Python Launcher` and safely associates `.pyw` files with it for the current Windows account. It backs up an existing per-user association before the first change and never borrows another tool's Python runtime.

Run `Installer.bat` again to repair the private components or after moving the complete folder. Setup preserves your files and recreates the shortcut for the folder's current location.

## usage

1. Choose a category.
2. Choose a file or drag it into the app.
3. Select the output format.
4. Choose the output folder.
5. Click **Convert**.

The original input is never overwritten. Animation is preserved when the output supports it, and compatible media streams are copied without re-encoding when possible.

## built with

- [PySide6](https://doc.qt.io/qtforpython-6/)
- [Pillow](https://python-pillow.github.io/)
- [pillow-heif](https://github.com/bigcat88/pillow_heif)
- [py7zr](https://py7zr.readthedocs.io/)
- [FFmpeg](https://ffmpeg.org/)
- [Python](https://www.python.org/)

## privacy and removal

The app has no telemetry, analytics, advertisements, accounts, uploads, or runtime network requests. Files are processed locally. Setup logs can contain local folder paths, so review them before sharing.

To remove only File Converter, close it and delete the extracted folder. The app does not install a background service, add itself to startup, or create an uninstaller entry.

The shared `.pyw` launcher can be used by every installed Fleece Tool, so removing one tool does not remove it. To restore the association that existed before Fleece Tools first configured it, run `%LOCALAPPDATA%\Fleece Tools\Python Launcher\Restore pyw association.cmd` after closing every Fleece Tool.

## troubleshooting

If setup stops, review `setup.log`, correct the listed problem, and run `Installer.bat` again. Setup reports success only after its dependencies, offline self-tests, and shortcut all pass.

If the `File Converter` shortcut does not open, run `Installer.bat` again and keep the complete extracted folder together. Setup recreates and validates the shortcut for the folder's current location.

BAT/CMD and PY/PYW conversions only change the extension. They do not translate or rewrite script contents.

## source use

The source is public for transparency and security review. Copyright 2026 Fleece. All rights reserved. No permission is granted to use, copy, modify, redistribute, sell, or publish derivative versions. See [LICENSE](LICENSE).

## note

This project was made with AI.

Keep a backup of important files and verify converted output before deleting an original.
