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

1. download the latest ZIP from the [releases page](../../releases/latest)
2. extract the folder
3. run `Installer.bat`
4. open `File Converter.pyw`

The download contains only the installer and app. Setup creates a private `.venv` for the required Python packages and downloads verified FFmpeg tools into a private `.runtime` folder. It does not require administrator access.

If compatible 64-bit Python 3.10 through 3.14 is already installed, setup uses it to create the private environment. If Python is unavailable, setup can install Python 3.13 for the current Windows user through winget.

The FFmpeg archive is checked against a pinned SHA-256 checksum. Run `Installer.bat` again whenever you want to repair the private environment or downloaded components.

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

The app has no telemetry, analytics, accounts, or usage tracking. Files are processed locally and are never uploaded. To remove everything installed specifically for the app, close it and delete its folder. A Python installation added through winget may remain in your user environment.

## note

This project was made with AI.

BAT/CMD and PY/PYW swaps only change the extension. They do not translate the script or change its contents.
