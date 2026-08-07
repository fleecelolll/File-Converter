<div align="center">

# file converter

A little tool I made with AI to quickly convert common image, audio, video, archive, and script files locally on 64-bit Windows.

</div>

<p align="center">
  <img src="File Converter.png" alt="file converter" width="673">
</p>

## features

- convert common image, audio, video, archive, and script formats
- preserve image animation when the output format supports it
- copy compatible media streams without re-encoding or quality loss
- extract audio from video files
- convert existing archives or create new archives from files and folders
- swap BAT/CMD and PY/PYW extensions without changing file contents
- choose the output folder
- follow progress in the built-in log
- process every file locally without uploads or telemetry

Supported images include PNG, JPG, WEBP, BMP, ICO, GIF, TIFF, TGA, AVIF, HEIC, and HEIF. Audio and video conversion uses FFmpeg. Archives support ZIP, 7Z, TAR, TAR.GZ, TGZ, and GZ.

## installation

1. Download and extract the release ZIP.
2. Double-click `Installer.bat`.
3. Let every setup check pass.
4. Double-click the `File Converter` shortcut created in the folder.

The setup keeps the app runtime, verified FFmpeg tools, and Python packages inside the extracted folder. It does not need administrator access. It also installs one small shared launcher in `%LOCALAPPDATA%\Fleece Tools\Python Launcher` and sets `.pyw` files to open with it for your Windows account. The launcher always uses the selected tool's sibling `.venv\Scripts\pythonw.exe`, then its sibling `.runtime\python\pythonw.exe`. It does not change PATH, install global Python packages, or use another tool's private Python. You can copy the shortcut to your Desktop or pin it to the taskbar.

Before the first Fleece Tools association change, setup exports any existing per-user `.pyw` settings to that shared folder. If the previous setting cannot be backed up safely, setup stops without overwriting it. A later non-Fleece choice is also left alone.

If compatible 64-bit Python 3.10 through 3.14 is already installed, setup uses it to create a private `.venv`. Otherwise, setup can download official Python 3.14.7 privately into this folder. Python, pip, PySide6, Pillow, pillow-heif, py7zr, FFmpeg, and FFprobe are pinned and validated. Downloaded runtime archives are checked against pinned SHA-256 checksums.

Run `Installer.bat` again whenever you want to repair or update the private components. Run it again after moving the extracted folder so the shortcut is recreated for the folder's new location. Always open the `File Converter` shortcut, not `File Converter.pyw`.

## usage

1. choose a category
2. choose a file or drag it into the app
3. select the output format
4. choose the output folder
5. click **Convert**

In the Archives category, Browse lets you choose multiple files or one folder. Drag and drop can combine files and folders in one archive. Selecting one existing archive converts it to another archive format.

Animation preservation and compatible media stream copying happen automatically. If direct media copying is not compatible with the selected format, FFmpeg performs a normal conversion instead. The original input is never overwritten.

## built with

- [PySide6](https://doc.qt.io/qtforpython-6/)
- [Pillow](https://python-pillow.github.io/)
- [pillow-heif](https://github.com/bigcat88/pillow_heif)
- [py7zr](https://py7zr.readthedocs.io/)
- [FFmpeg](https://ffmpeg.org/)
- [Python](https://www.python.org/)

## privacy and removal

The app has no telemetry, analytics, accounts, or usage tracking. Files are processed locally and are never uploaded. The app makes no runtime network requests.

To remove only File Converter, close it and delete the extracted folder. The app does not install a background service, add itself to startup, or create an uninstaller entry.

The shared `.pyw` launcher is used by every installed Fleece Tool, so removing one tool does not remove it. To restore the `.pyw` settings that existed before Fleece Tools first configured them, run `%LOCALAPPDATA%\Fleece Tools\Python Launcher\Restore pyw association.cmd`. The restore helper refuses to overwrite a newer non-Fleece choice. After restoring, and after removing every Fleece Tool that uses it, you can delete the shared `Python Launcher` folder. The registry backup files can contain local application names and paths, so review them before sharing.

## note

This project was made with AI.

BAT/CMD and PY/PYW swaps only change the extension. They do not translate the script or change its contents.
