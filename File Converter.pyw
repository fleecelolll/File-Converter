from __future__ import annotations

import atexit
import ctypes
import gzip
import hashlib
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import traceback
import uuid
import warnings
import wave
import zipfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from ctypes import wintypes
from typing import Callable, Optional


APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / ".runtime"
VENV_ROOT = APP_DIR / ".venv"
VENV_PY = VENV_ROOT / "Scripts" / "python.exe"
VENV_PYW = VENV_ROOT / "Scripts" / "pythonw.exe"
EMBEDDED_PY = RUNTIME_DIR / "python" / "python.exe"
EMBEDDED_PYW = RUNTIME_DIR / "python" / "pythonw.exe"
SETUP_LOCK_DIR = RUNTIME_DIR / "setup.lock"
ERROR_LOG_PATH = RUNTIME_DIR / "error.log"
APP_TITLE = "File Converter"
APP_VERSION = "1.0.6"
APP_MUTEX_NAMES = (
    r"Global\FleeceFileConverterApp",
    r"Local\FleeceFileConverterApp",
)
APP_MUTEX_HANDLE = None
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183


def show_native_setup_error(message: str):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, 0x10)
    else:
        print(f"{APP_TITLE}: {message}", file=sys.stderr)


def bootstrap_local_python():
    current = os.path.normcase(os.path.realpath(sys.executable))
    for local_python, local_pythonw in (
        (VENV_PY, VENV_PYW),
        (EMBEDDED_PY, EMBEDDED_PYW),
    ):
        valid_executables = {
            os.path.normcase(os.path.realpath(path))
            for path in (local_python, local_pythonw)
            if path.is_file()
        }
        if current in valid_executables and sys.flags.isolated:
            return
        if not local_python.is_file() or not local_pythonw.is_file():
            continue
        try:
            if current not in valid_executables:
                validation = subprocess.run(
                    [str(local_python), "-I", "-c", "pass"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if validation.returncode != 0:
                    continue
            subprocess.Popen(
                [
                    str(local_pythonw),
                    "-I",
                    str(Path(__file__).resolve()),
                    *sys.argv[1:],
                ],
                cwd=str(APP_DIR),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            continue
        raise SystemExit(0)

    show_native_setup_error(
        "Setup is missing, incomplete, or no longer usable.\n\n"
        "Run Installer.bat, let it finish, then open the File Converter shortcut."
    )
    raise SystemExit(1)


if __name__ == "__main__":
    bootstrap_local_python()


try:
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QObject,
        QPoint,
        QPropertyAnimation,
        QRect,
        QThread,
        Qt,
        QUrl,
        Signal,
        Slot,
    )
    from PySide6.QtGui import (
        QCloseEvent,
        QDesktopServices,
        QDragEnterEvent,
        QDropEvent,
        QKeyEvent,
        QMouseEvent,
        QPainter,
        QPen,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QScrollArea,
        QSizePolicy,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    from shiboken6 import delete as delete_qt_object
except Exception:
    if __name__ == "__main__":
        show_native_setup_error(
            "Setup is incomplete and the app window cannot load.\n\n"
            "Run Installer.bat again to repair the setup."
        )
        raise SystemExit(1)
    raise


py7zr = None
Image = None
ImageOps = None
UnidentifiedImageError = None
features = None
_IMAGE_BACKEND_LOCK = threading.Lock()
_ARCHIVE_BACKEND_LOCK = threading.Lock()


def load_image_backend():
    """Load image codecs on first image work instead of delaying every startup."""
    global Image, ImageOps, UnidentifiedImageError, features
    if Image is not None:
        return
    with _IMAGE_BACKEND_LOCK:
        if Image is not None:
            return
        try:
            from PIL import Image as pillow_image
            from PIL import ImageOps as pillow_image_ops
            from PIL import UnidentifiedImageError as unidentified_image_error
            from PIL import features as pillow_features
            from pillow_heif import register_heif_opener

            register_heif_opener(thumbnails=False)
        except Exception as error:
            raise RuntimeError(
                "Image support is incomplete. Run Installer.bat again to repair it."
            ) from error
        Image = pillow_image
        ImageOps = pillow_image_ops
        UnidentifiedImageError = unidentified_image_error
        features = pillow_features


def load_archive_backend():
    """Load the optional 7Z backend only when archive work needs it."""
    global py7zr
    if py7zr is not None:
        return
    with _ARCHIVE_BACKEND_LOCK:
        if py7zr is not None:
            return
        try:
            import py7zr as seven_zip_backend
        except Exception as error:
            raise RuntimeError(
                "7Z support is incomplete. Run Installer.bat again to repair it."
            ) from error
        py7zr = seven_zip_backend


def screen_aware_window_dimensions(width: int, height: int):
    usable_width = max(1, int(width) - 32)
    usable_height = max(1, int(height) - 32)
    return (
        min(660, usable_width),
        min(570, usable_height),
        min(620, usable_width),
        min(530, usable_height),
    )


if os.name == "nt":
    NATIVE_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    NATIVE_KERNEL32.CreateMutexW.argtypes = (
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    NATIVE_KERNEL32.CreateMutexW.restype = wintypes.HANDLE
    NATIVE_KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    NATIVE_KERNEL32.CloseHandle.restype = wintypes.BOOL
else:
    NATIVE_KERNEL32 = None


def release_app_mutex():
    global APP_MUTEX_HANDLE
    if APP_MUTEX_HANDLE is None or NATIVE_KERNEL32 is None:
        return
    NATIVE_KERNEL32.CloseHandle(APP_MUTEX_HANDLE)
    APP_MUTEX_HANDLE = None


def _try_create_named_mutex(name):
    if NATIVE_KERNEL32 is None:
        return "unavailable", None
    ctypes.set_last_error(0)
    handle = NATIVE_KERNEL32.CreateMutexW(None, False, name)
    error_code = ctypes.get_last_error()
    if handle and error_code == ERROR_ALREADY_EXISTS:
        NATIVE_KERNEL32.CloseHandle(handle)
        return "exists", None
    if handle:
        return "acquired", handle
    if error_code == ERROR_ACCESS_DENIED:
        return "denied", None
    return "failed", None


def acquire_app_mutex():
    global APP_MUTEX_HANDLE
    if NATIVE_KERNEL32 is None:
        return True
    for index, name in enumerate(APP_MUTEX_NAMES):
        status, handle = _try_create_named_mutex(name)
        if status == "acquired":
            APP_MUTEX_HANDLE = handle
            atexit.register(release_app_mutex)
            return True
        if status == "exists":
            return False
        if index == 0 and status == "denied":
            continue
        return False
    return False


def exception_report(error_type, error, trace) -> str:
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return (
        f"{APP_TITLE} {APP_VERSION}\n"
        f"Time: {timestamp}\n\n"
        + "".join(traceback.format_exception(error_type, error, trace))
    )


def write_exception_log(error_type, error, trace, path: Path = ERROR_LOG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            exception_report(error_type, error, trace),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def handle_unhandled_exception(error_type, error, trace):
    try:
        write_exception_log(error_type, error, trace)
    except Exception:
        pass
    show_native_setup_error(
        "The app stopped because of an unexpected error.\n\n"
        "Details were saved to .runtime\\error.log. If the issue continues, "
        "run Installer.bat to repair the setup."
    )
    application = QApplication.instance()
    if application is not None:
        application.quit()


def handle_unhandled_thread_exception(arguments):
    handle_unhandled_exception(
        arguments.exc_type,
        arguments.exc_value,
        arguments.exc_traceback,
    )


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".ico",
    ".gif",
    ".tiff",
    ".tif",
    ".tga",
    ".avif",
    ".heic",
    ".heif",
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".tar", ".tar.gz", ".tgz", ".gz"}
BATCH_EXTENSIONS = {".bat", ".cmd"}
PYTHON_EXTENSIONS = {".py", ".pyw"}
SCRIPT_EXTENSIONS = BATCH_EXTENSIONS | PYTHON_EXTENSIONS
SUPPORTED_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | AUDIO_EXTENSIONS
    | VIDEO_EXTENSIONS
    | ARCHIVE_EXTENSIONS
    | SCRIPT_EXTENSIONS
)
IMAGE_FORMATS = {
    "PNG image (.png)": (".png", "PNG"),
    "JPG image (.jpg)": (".jpg", "JPEG"),
    "WEBP image (.webp)": (".webp", "WEBP"),
    "BMP image (.bmp)": (".bmp", "BMP"),
    "ICO icon (.ico)": (".ico", "ICO"),
    "GIF image (.gif)": (".gif", "GIF"),
    "TIFF image (.tiff)": (".tiff", "TIFF"),
    "TGA image (.tga)": (".tga", "TGA"),
    "AVIF image (.avif)": (".avif", "AVIF"),
    "HEIC image (.heic)": (".heic", "HEIF"),
}
AUDIO_FORMATS = {
    "MP3 audio (.mp3)": (".mp3", "audio"),
    "WAV audio (.wav)": (".wav", "audio"),
    "FLAC audio (.flac)": (".flac", "audio"),
    "OGG audio (.ogg)": (".ogg", "audio"),
    "M4A audio (.m4a)": (".m4a", "audio"),
    "AAC audio (.aac)": (".aac", "audio"),
}
VIDEO_FORMATS = {
    "MP4 video (.mp4)": (".mp4", "video"),
    "MKV video (.mkv)": (".mkv", "video"),
    "WEBM video (.webm)": (".webm", "video"),
    "MOV video (.mov)": (".mov", "video"),
    "AVI video (.avi)": (".avi", "video"),
}
ARCHIVE_FORMATS = {
    "ZIP archive (.zip)": ".zip",
    "7Z archive (.7z)": ".7z",
    "TAR archive (.tar)": ".tar",
    "TAR.GZ archive (.tar.gz)": ".tar.gz",
    "GZ compressed file (.gz)": ".gz",
}
SCRIPT_FORMATS = {
    "BAT script (.bat)": ".bat",
    "CMD script (.cmd)": ".cmd",
    "Python script (.py)": ".py",
    "Python window script (.pyw)": ".pyw",
}
IMAGE_LABEL_BY_EXTENSION = {
    ".png": "PNG image (.png)",
    ".jpg": "JPG image (.jpg)",
    ".jpeg": "JPG image (.jpg)",
    ".webp": "WEBP image (.webp)",
    ".bmp": "BMP image (.bmp)",
    ".ico": "ICO icon (.ico)",
    ".gif": "GIF image (.gif)",
    ".tiff": "TIFF image (.tiff)",
    ".tif": "TIFF image (.tiff)",
    ".tga": "TGA image (.tga)",
    ".avif": "AVIF image (.avif)",
    ".heic": "HEIC image (.heic)",
    ".heif": "HEIC image (.heic)",
}
MEDIA_FORMATS = {**AUDIO_FORMATS, **VIDEO_FORMATS}
MAX_IMAGE_BYTES = 512 * 1024 * 1024
MAX_IMAGE_FRAMES = 500
MAX_IMAGE_TOTAL_PIXELS = 150_000_000
MAX_MEDIA_BYTES = 100 * 1024 * 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 20000
MAX_SCRIPT_BYTES = 64 * 1024 * 1024
FFMPEG_PATH = APP_DIR / ".runtime" / "ffmpeg" / "ffmpeg.exe"
FFPROBE_PATH = APP_DIR / ".runtime" / "ffmpeg" / "ffprobe.exe"
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ConversionCancelled(Exception):
    pass


def extension_for_path(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    if name.endswith(".tgz"):
        return ".tgz"
    return path.suffix.lower()


def category_for_extension(extension: str) -> Optional[str]:
    if extension in IMAGE_EXTENSIONS:
        return "Images"
    if extension in AUDIO_EXTENSIONS:
        return "Audio"
    if extension in VIDEO_EXTENSIONS:
        return "Video"
    if extension in ARCHIVE_EXTENSIONS:
        return "Archives"
    if extension in SCRIPT_EXTENSIONS:
        return "Scripts"
    return None


def source_label_for_extension(category: str, extension: str) -> Optional[str]:
    if category == "Images":
        return IMAGE_LABEL_BY_EXTENSION.get(extension)
    if category == "Audio":
        for label, (target_extension, _) in AUDIO_FORMATS.items():
            if extension == target_extension:
                return label
    if category == "Video":
        for label, (target_extension, _) in VIDEO_FORMATS.items():
            if extension == target_extension:
                return label
    if category == "Archives":
        canonical = ".tar.gz" if extension == ".tgz" else extension
        for label, target_extension in ARCHIVE_FORMATS.items():
            if canonical == target_extension:
                return label
    return None


def output_extension_for_label(label: str) -> Optional[str]:
    if label in IMAGE_FORMATS:
        return IMAGE_FORMATS[label][0]
    if label in MEDIA_FORMATS:
        return MEDIA_FORMATS[label][0]
    if label in ARCHIVE_FORMATS:
        return ARCHIVE_FORMATS[label]
    return SCRIPT_FORMATS.get(label)


def base_name_for_path(path: Path) -> str:
    extension = extension_for_path(path)
    return path.name[: -len(extension)] if extension else path.stem


def temporary_output_path(output: Path) -> Path:
    extension = extension_for_path(output)
    base = base_name_for_path(output)
    return output.with_name(f".{base}.{uuid.uuid4().hex}{extension}")


def check_cancel(cancel_event: Optional[threading.Event]):
    if cancel_event is not None and cancel_event.is_set():
        raise ConversionCancelled("Conversion cancelled.")


def terminate_subprocess_safely(process, timeout: float = 5.0):
    """Best-effort cleanup that never replaces the conversion's real outcome."""
    try:
        running = process.poll() is None
    except Exception:
        running = True
    if running:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=timeout)
    except Exception:
        pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def flatten_to_rgb(image: Image.Image) -> Image.Image:
    if has_alpha(image):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def prepare_png(image: Image.Image) -> Image.Image:
    if has_alpha(image):
        return image.convert("RGBA")
    if image.mode in {"1", "L", "P", "RGB", "I;16"}:
        return image.copy()
    return image.convert("RGB")


def prepare_webp(image: Image.Image) -> Image.Image:
    return image.convert("RGBA") if has_alpha(image) else image.convert("RGB")


def prepare_icon(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    contained = ImageOps.contain(
        rgba,
        (256, 256),
        method=Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    position = (
        (canvas.width - contained.width) // 2,
        (canvas.height - contained.height) // 2,
    )
    canvas.alpha_composite(contained, position)
    return canvas


def prepare_gif_frame(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    prepared = rgba.quantize(
        colors=255,
        method=Image.Quantize.FASTOCTREE,
    )
    alpha = rgba.getchannel("A")
    transparency_mask = alpha.point(lambda value: 255 if value < 128 else 0)
    prepared.paste(255, mask=transparency_mask)
    return prepared


def validate_image_output(
    path: Path,
    expected_format: str,
    expected_frames: int = 1,
):
    load_image_backend()
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("The converted image was not created.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            if image.format != expected_format:
                raise RuntimeError("The converted image format check failed.")
            image.load()
            if image.width < 1 or image.height < 1:
                raise RuntimeError("The converted image has an invalid size.")
            if int(getattr(image, "n_frames", 1)) != expected_frames:
                raise RuntimeError("The converted image frame count check failed.")
            if expected_format == "ICO":
                sizes = set(image.info.get("sizes", ()))
                required = {(16, 16), (32, 32), (48, 48), (256, 256)}
                if not required.issubset(sizes):
                    raise RuntimeError("The icon size check failed.")


def convert_image(
    source: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    load_image_backend()
    if target_label not in IMAGE_FORMATS:
        raise ValueError("Choose a valid image format.")
    if source.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("The image is larger than the 512 MB limit.")

    output_extension, pillow_format = IMAGE_FORMATS[target_label]
    if output.suffix.lower() != output_extension:
        raise ValueError("The output extension does not match the selected format.")

    temporary = temporary_output_path(output)
    try:
        check_cancel(cancel_event)
        animated_formats = {"PNG", "GIF", "WEBP", "TIFF", "AVIF", "HEIF"}
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as opened:
                frame_count = int(getattr(opened, "n_frames", 1))
                preserve_animation = frame_count > 1 and pillow_format in animated_formats
                frames_to_read = frame_count if preserve_animation else 1
                if frames_to_read > MAX_IMAGE_FRAMES:
                    raise ValueError(
                        f"The image contains more than {MAX_IMAGE_FRAMES} frames."
                    )
                loop = int(opened.info.get("loop", 0) or 0)
                frames = []
                durations = []
                total_pixels = 0
                for frame_index in range(frames_to_read):
                    check_cancel(cancel_event)
                    opened.seek(frame_index)
                    frame_pixels = opened.width * opened.height
                    if frame_pixels < 1:
                        raise ValueError("The image contains a frame with an invalid size.")
                    total_pixels += frame_pixels
                    if total_pixels > MAX_IMAGE_TOTAL_PIXELS:
                        raise ValueError("The image animation is too large to process safely.")
                    opened.load()
                    frames.append(ImageOps.exif_transpose(opened).copy())
                    duration = opened.info.get("duration", 100)
                    try:
                        duration = max(1, min(3_600_000, int(round(float(duration)))))
                    except (TypeError, ValueError):
                        duration = 100
                    durations.append(duration)
                image = frames[0]

        check_cancel(cancel_event)
        if pillow_format == "PNG":
            prepared_frames = [
                frame.convert("RGBA") if preserve_animation else prepare_png(frame)
                for frame in frames
            ]
            save_options = {
                "format": "PNG",
                "optimize": not preserve_animation,
                "compress_level": 6,
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                )
            prepared_frames[0].save(temporary, **save_options)
        elif pillow_format == "JPEG":
            prepared = flatten_to_rgb(image)
            prepared.save(
                temporary,
                format="JPEG",
                quality=95,
                subsampling=0,
                optimize=True,
            )
        elif pillow_format == "WEBP":
            if not features.check("webp"):
                raise RuntimeError("WEBP support is missing. Run Installer.bat again.")
            prepared_frames = [prepare_webp(frame) for frame in frames]
            save_options = {
                "format": "WEBP",
                "quality": 95,
                "method": 4,
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                )
            prepared_frames[0].save(temporary, **save_options)
        elif pillow_format == "BMP":
            prepared = flatten_to_rgb(image)
            prepared.save(temporary, format="BMP")
        elif pillow_format == "ICO":
            prepared = prepare_icon(image)
            prepared.save(
                temporary,
                format="ICO",
                sizes=[
                    (16, 16),
                    (20, 20),
                    (24, 24),
                    (32, 32),
                    (40, 40),
                    (48, 48),
                    (64, 64),
                    (128, 128),
                    (256, 256),
                ],
            )
        elif pillow_format == "GIF":
            prepared_frames = [prepare_gif_frame(frame) for frame in frames]
            save_options = {
                "format": "GIF",
                "optimize": not preserve_animation,
                "transparency": 255,
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                    disposal=2,
                )
            prepared_frames[0].save(temporary, **save_options)
        elif pillow_format == "TIFF":
            prepared_frames = [prepare_webp(frame) for frame in frames]
            save_options = {
                "format": "TIFF",
                "compression": "tiff_deflate",
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                )
            prepared_frames[0].save(temporary, **save_options)
        elif pillow_format == "TGA":
            prepared = prepare_webp(image)
            prepared.save(temporary, format="TGA")
        elif pillow_format == "AVIF":
            if not features.check("avif"):
                raise RuntimeError("AVIF support is missing. Run Installer.bat again.")
            prepared_frames = [prepare_webp(frame) for frame in frames]
            save_options = {
                "format": "AVIF",
                "quality": 90,
                "speed": 6,
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                )
            prepared_frames[0].save(temporary, **save_options)
        elif pillow_format == "HEIF":
            prepared_frames = [prepare_webp(frame) for frame in frames]
            save_options = {
                "format": "HEIF",
                "quality": 90,
            }
            if preserve_animation:
                save_options.update(
                    save_all=True,
                    append_images=prepared_frames[1:],
                    duration=durations,
                    loop=loop,
                )
            prepared_frames[0].save(temporary, **save_options)
        else:
            raise ValueError("Choose a valid image format.")

        check_cancel(cancel_event)
        expected_frames = frame_count if preserve_animation else 1
        validate_image_output(temporary, pillow_format, expected_frames)
        check_cancel(cancel_event)
        os.replace(temporary, output)
        message = (
            f"Created {output.name} from a {image.width} x {image.height} image."
        )
        if frame_count > 1:
            if preserve_animation:
                message += f" Preserved all {frame_count} frames."
            else:
                message += (
                    f" Used the first of {frame_count} frames because "
                    f"{output_extension.upper().lstrip('.')} is a static format."
                )
        return message
    except (UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValueError("The selected file is not a safe readable image.") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def compatible_script_targets(source_extension: str):
    if source_extension in BATCH_EXTENSIONS:
        allowed = BATCH_EXTENSIONS
    elif source_extension in PYTHON_EXTENSIONS:
        allowed = PYTHON_EXTENSIONS
    else:
        return []
    return [
        label
        for label, extension in SCRIPT_FORMATS.items()
        if extension in allowed and extension != source_extension
    ]


def convert_script(
    source: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    if target_label not in SCRIPT_FORMATS:
        raise ValueError("Choose a valid script format.")
    if source.stat().st_size > MAX_SCRIPT_BYTES:
        raise ValueError("The script is larger than the 64 MB limit.")

    source_extension = source.suffix.lower()
    target_extension = SCRIPT_FORMATS[target_label]
    valid_targets = compatible_script_targets(source_extension)
    if target_label not in valid_targets or output.suffix.lower() != target_extension:
        raise ValueError("That script conversion is not supported.")

    temporary = temporary_output_path(output)
    try:
        check_cancel(cancel_event)
        shutil.copyfile(source, temporary)
        check_cancel(cancel_event)
        if temporary.stat().st_size != source.stat().st_size:
            raise RuntimeError("The copied script size check failed.")
        if sha256_file(temporary) != sha256_file(source):
            raise RuntimeError("The copied script content check failed.")
        check_cancel(cancel_event)
        os.replace(temporary, output)
        return f"Created {output.name} without changing the script contents."
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def media_arguments(target_label: str):
    if target_label == "MP3 audio (.mp3)":
        return ["-map", "0:a:0?", "-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    if target_label == "WAV audio (.wav)":
        return ["-map", "0:a:0?", "-vn", "-c:a", "pcm_s16le"]
    if target_label == "FLAC audio (.flac)":
        return [
            "-map",
            "0:a:0?",
            "-vn",
            "-c:a",
            "flac",
            "-compression_level",
            "8",
        ]
    if target_label == "OGG audio (.ogg)":
        return ["-map", "0:a:0?", "-vn", "-c:a", "libvorbis", "-q:a", "6"]
    if target_label == "M4A audio (.m4a)":
        return [
            "-map",
            "0:a:0?",
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
        ]
    if target_label == "AAC audio (.aac)":
        return [
            "-map",
            "0:a:0?",
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-f",
            "adts",
        ]

    common_video = [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    ]
    if target_label == "MP4 video (.mp4)":
        return common_video + [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    if target_label == "MKV video (.mkv)":
        return common_video + [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
        ]
    if target_label == "WEBM video (.webm)":
        return common_video + [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "30",
            "-b:v",
            "0",
            "-deadline",
            "good",
            "-cpu-used",
            "4",
            "-c:a",
            "libopus",
            "-b:a",
            "160k",
        ]
    if target_label == "MOV video (.mov)":
        return common_video + [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    if target_label == "AVI video (.avi)":
        return common_video + [
            "-c:v",
            "mpeg4",
            "-q:v",
            "3",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "3",
        ]
    raise ValueError("Choose a valid audio or video format.")


def media_codec_matches(codec: str, allowed: set) -> bool:
    return codec in allowed or ("pcm_*" in allowed and codec.startswith("pcm_"))


def stream_copy_arguments(target_label: str, information: dict):
    audio_codecs = {
        "MP3 audio (.mp3)": {"mp3"},
        "WAV audio (.wav)": {"pcm_*"},
        "FLAC audio (.flac)": {"flac"},
        "OGG audio (.ogg)": {"opus", "vorbis"},
        "M4A audio (.m4a)": {"aac", "alac"},
        "AAC audio (.aac)": {"aac"},
    }
    video_codecs = {
        "MP4 video (.mp4)": {"av1", "h264", "hevc", "mpeg4"},
        "MKV video (.mkv)": {
            "av1",
            "h264",
            "hevc",
            "mjpeg",
            "mpeg4",
            "prores",
            "theora",
            "vp8",
            "vp9",
        },
        "WEBM video (.webm)": {"av1", "vp8", "vp9"},
        "MOV video (.mov)": {"h264", "hevc", "mjpeg", "mpeg4", "prores"},
        "AVI video (.avi)": {"mjpeg", "mpeg4"},
    }
    video_audio_codecs = {
        "MP4 video (.mp4)": {"aac", "alac", "mp3"},
        "MKV video (.mkv)": {
            "aac",
            "ac3",
            "alac",
            "eac3",
            "flac",
            "mp3",
            "opus",
            "pcm_*",
            "vorbis",
        },
        "WEBM video (.webm)": {"opus", "vorbis"},
        "MOV video (.mov)": {"aac", "alac", "mp3", "pcm_*"},
        "AVI video (.avi)": {"mp3", "pcm_*"},
    }
    streams = information.get("streams", [])
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )

    if target_label in audio_codecs:
        if audio_stream is None:
            return None
        codec = str(audio_stream.get("codec_name", "")).lower()
        if not media_codec_matches(codec, audio_codecs[target_label]):
            return None
        arguments = ["-map", "0:a:0", "-vn", "-c:a", "copy"]
        if target_label == "M4A audio (.m4a)":
            arguments += ["-movflags", "+faststart"]
        elif target_label == "AAC audio (.aac)":
            arguments += ["-f", "adts"]
        return arguments

    if target_label not in video_codecs or video_stream is None:
        return None
    video_codec = str(video_stream.get("codec_name", "")).lower()
    if not media_codec_matches(video_codec, video_codecs[target_label]):
        return None
    if audio_stream is not None:
        audio_codec = str(audio_stream.get("codec_name", "")).lower()
        if not media_codec_matches(audio_codec, video_audio_codecs[target_label]):
            return None
    arguments = ["-map", "0:v:0", "-map", "0:a:0?", "-c", "copy"]
    if target_label in {"MP4 video (.mp4)", "MOV video (.mov)"}:
        arguments += ["-movflags", "+faststart"]
    return arguments


def probe_media(path: Path, ffprobe_path: Path):
    result = subprocess.run(
        [
            str(ffprobe_path),
            "-v",
            "error",
            "-protocol_whitelist",
            "file,crypto,data",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "FFprobe could not read the file.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("FFprobe returned invalid file information.") from error


def validate_media_output(path: Path, target_kind: str, ffprobe_path: Path):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("The converted media file was not created.")
    information = probe_media(path, ffprobe_path)
    stream_types = {
        stream.get("codec_type") for stream in information.get("streams", [])
    }
    if target_kind not in stream_types:
        raise RuntimeError(f"The converted file does not contain a {target_kind} stream.")


def convert_media(
    source: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    process_controller=None,
) -> str:
    if target_label not in MEDIA_FORMATS:
        raise ValueError("Choose a valid audio or video format.")
    if source.stat().st_size > MAX_MEDIA_BYTES:
        raise ValueError("The media file is larger than the 100 GB limit.")
    if not FFMPEG_PATH.is_file() or not FFPROBE_PATH.is_file():
        raise RuntimeError("FFmpeg is missing. Run Installer.bat again.")

    source_category = category_for_extension(extension_for_path(source))
    output_extension, target_kind = MEDIA_FORMATS[target_label]
    if source_category == "Audio" and target_kind == "video":
        raise ValueError("An audio file cannot be converted into a video file.")
    if output.suffix.lower() != output_extension:
        raise ValueError("The output extension does not match the selected format.")

    information = probe_media(source, FFPROBE_PATH)
    copy_arguments = stream_copy_arguments(target_label, information)
    try:
        duration = float(information.get("format", {}).get("duration", 0) or 0)
    except (TypeError, ValueError):
        duration = 0.0

    temporary = temporary_output_path(output)
    command = [
        str(FFMPEG_PATH),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-v",
        "error",
        "-progress",
        "pipe:1",
        "-protocol_whitelist",
        "file,crypto,data",
        "-i",
        str(source),
        "-map_metadata",
        "-1",
        "-sn",
        "-dn",
        *(copy_arguments or media_arguments(target_label)),
        str(temporary),
    ]

    process = None
    recent_output = []
    try:
        check_cancel(cancel_event)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process_controller is not None:
            process_controller.set_process(process)

        if process.stdout is not None:
            for raw_line in process.stdout:
                check_cancel(cancel_event)
                line = raw_line.strip()
                if not line:
                    continue
                key, separator, value = line.partition("=")
                if separator and key in {"out_time_us", "out_time_ms"} and duration > 0:
                    try:
                        completed = float(value) / 1_000_000
                        progress = max(0, min(99, int(completed / duration * 100)))
                        if progress_callback is not None:
                            progress_callback(progress)
                    except ValueError:
                        pass
                elif separator and key == "progress" and value == "end":
                    if progress_callback is not None:
                        progress_callback(99)
                elif not separator:
                    recent_output.append(line)
                    recent_output = recent_output[-12:]

        return_code = process.wait()
        check_cancel(cancel_event)
        if return_code != 0:
            details = "\n".join(recent_output).strip()
            raise RuntimeError(details or f"FFmpeg exited with code {return_code}.")

        validate_media_output(temporary, target_kind, FFPROBE_PATH)
        check_cancel(cancel_event)
        os.replace(temporary, output)
        if progress_callback is not None:
            progress_callback(100)
        if copy_arguments is not None:
            return (
                f"Created {output.name} by copying compatible media streams "
                "without re-encoding."
            )
        return f"Created {output.name} with FFmpeg re-encoding."
    finally:
        if process_controller is not None:
            try:
                process_controller.clear_process(process)
            except Exception:
                pass
        if process is not None:
            terminate_subprocess_safely(process)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def safe_archive_destination(root: Path, member_name: str, seen: set) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/"):
        raise ValueError("The archive contains an absolute path.")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    if not normalized or "\x00" in normalized:
        raise ValueError("The archive contains an invalid empty path.")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("The archive contains an unsafe path.")
    for part in pure.parts:
        if ":" in part:
            raise ValueError("The archive contains an unsafe Windows path.")
        cleaned_part = part.rstrip(" .")
        if not cleaned_part or cleaned_part != part:
            raise ValueError("The archive contains a path ending in a dot or space.")
        name_root = cleaned_part.split(".", 1)[0].upper()
        if name_root in WINDOWS_RESERVED_NAMES:
            raise ValueError("The archive contains a reserved Windows filename.")

    key = "/".join(pure.parts).casefold()
    if key in seen:
        raise ValueError("The archive contains duplicate paths.")
    seen.add(key)

    destination = root.joinpath(*pure.parts).resolve()
    resolved_root = root.resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("The archive contains a path outside its root.") from error
    return destination


def copy_limited(
    source_stream,
    destination_stream,
    running_total: list,
    cancel_event: Optional[threading.Event],
):
    while True:
        check_cancel(cancel_event)
        block = source_stream.read(1024 * 1024)
        if not block:
            break
        running_total[0] += len(block)
        if running_total[0] > MAX_ARCHIVE_EXPANDED_BYTES:
            raise ValueError("The expanded archive is larger than the 4 GB limit.")
        destination_stream.write(block)


def validate_extracted_tree(root: Path):
    entries = 0
    files = 0
    total = 0
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        entries += 1
        if entries > MAX_ARCHIVE_FILES:
            raise ValueError("The archive contains more than 20,000 entries.")
        if path.is_symlink() or (
            hasattr(path, "is_junction") and path.is_junction()
        ):
            raise ValueError("The archive contains a link or junction.")
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError as error:
            raise ValueError("The archive escaped its temporary folder.") from error
        if path.is_file():
            files += 1
            total += path.stat().st_size
            if files > MAX_ARCHIVE_FILES:
                raise ValueError("The archive contains more than 20,000 files.")
            if total > MAX_ARCHIVE_EXPANDED_BYTES:
                raise ValueError("The expanded archive is larger than the 4 GB limit.")
    if files == 0:
        raise ValueError("The archive does not contain any files.")
    return files, total


def extract_archive(
    source: Path,
    destination: Path,
    cancel_event: Optional[threading.Event] = None,
):
    source_extension = extension_for_path(source)
    seen = set()
    running_total = [0]
    entry_count = 0
    file_count = 0

    if source_extension == ".zip":
        with zipfile.ZipFile(source, "r") as archive:
            for info in archive.infolist():
                check_cancel(cancel_event)
                entry_count += 1
                if entry_count > MAX_ARCHIVE_FILES:
                    raise ValueError("The archive contains more than 20,000 entries.")
                target = safe_archive_destination(destination, info.filename, seen)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise ValueError("The ZIP archive contains a symbolic link.")
                if info.flag_bits & 0x1:
                    raise ValueError("Password-protected ZIP files are not supported.")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                file_count += 1
                if file_count > MAX_ARCHIVE_FILES:
                    raise ValueError("The archive contains more than 20,000 files.")
                if info.file_size < 0 or running_total[0] + info.file_size > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ValueError("The expanded archive is larger than the 4 GB limit.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source_stream, target.open("xb") as output_stream:
                    copy_limited(source_stream, output_stream, running_total, cancel_event)
    elif source_extension in {".tar", ".tar.gz", ".tgz"}:
        with tarfile.open(source, "r:*") as archive:
            for member in archive:
                check_cancel(cancel_event)
                entry_count += 1
                if entry_count > MAX_ARCHIVE_FILES:
                    raise ValueError("The archive contains more than 20,000 entries.")
                root_name = member.name.replace("\\", "/").strip("/")
                if member.isdir() and root_name in {"", "."}:
                    continue
                target = safe_archive_destination(destination, member.name, seen)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ValueError("The TAR archive contains a link or special file.")
                file_count += 1
                if file_count > MAX_ARCHIVE_FILES:
                    raise ValueError("The archive contains more than 20,000 files.")
                if member.size < 0 or running_total[0] + member.size > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ValueError("The expanded archive is larger than the 4 GB limit.")
                source_stream = archive.extractfile(member)
                if source_stream is None:
                    raise ValueError("A TAR file could not be read.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with source_stream, target.open("xb") as output_stream:
                    copy_limited(source_stream, output_stream, running_total, cancel_event)
    elif source_extension == ".7z":
        load_archive_backend()
        with py7zr.SevenZipFile(
            source,
            "r",
            max_extract_size=MAX_ARCHIVE_EXPANDED_BYTES,
        ) as archive:
            if archive.needs_password():
                raise ValueError("Password-protected 7Z files are not supported.")
            entries = archive.list()
            for info in entries:
                check_cancel(cancel_event)
                entry_count += 1
                if entry_count > MAX_ARCHIVE_FILES:
                    raise ValueError("The archive contains more than 20,000 entries.")
                root_name = info.filename.replace("\\", "/").strip("/")
                if info.is_directory and root_name in {"", "."}:
                    continue
                safe_archive_destination(destination, info.filename, seen)
                if info.is_symlink:
                    raise ValueError("The 7Z archive contains a symbolic link.")
                if info.is_file:
                    file_count += 1
                    running_total[0] += int(info.uncompressed or 0)
            if file_count > MAX_ARCHIVE_FILES:
                raise ValueError("The archive contains more than 20,000 files.")
            if running_total[0] > MAX_ARCHIVE_EXPANDED_BYTES:
                raise ValueError("The expanded archive is larger than the 4 GB limit.")
            archive.extractall(path=destination)
    elif source_extension == ".gz":
        output_name = source.name[:-3] or "file"
        target = safe_archive_destination(destination, Path(output_name).name, seen)
        with gzip.open(source, "rb") as source_stream, target.open("xb") as output_stream:
            copy_limited(source_stream, output_stream, running_total, cancel_event)
        file_count = 1
    else:
        raise ValueError("Choose a supported archive file.")

    check_cancel(cancel_event)
    return validate_extracted_tree(destination)


def normalized_tar_info(info: tarfile.TarInfo):
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if info.isdir():
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o644
    return info


def write_archive(
    source_root: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
):
    target_extension = ARCHIVE_FORMATS[target_label]
    children = sorted(source_root.iterdir(), key=lambda path: path.name.casefold())
    if not children:
        raise ValueError("The archive does not contain anything to convert.")

    check_cancel(cancel_event)
    if target_extension == ".zip":
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            copied_total = [0]
            for path in sorted(source_root.rglob("*"), key=lambda item: str(item).casefold()):
                check_cancel(cancel_event)
                relative = path.relative_to(source_root).as_posix()
                if path.is_dir():
                    if not any(path.iterdir()):
                        info = zipfile.ZipInfo(relative.rstrip("/") + "/")
                        info.date_time = (1980, 1, 1, 0, 0, 0)
                        info.external_attr = 0o40755 << 16
                        archive.writestr(info, b"")
                else:
                    info = zipfile.ZipInfo(relative)
                    info.date_time = (1980, 1, 1, 0, 0, 0)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    with path.open("rb") as source_stream, archive.open(info, "w", force_zip64=True) as output_stream:
                        copy_limited(
                            source_stream,
                            output_stream,
                            copied_total,
                            cancel_event,
                        )
    elif target_extension == ".7z":
        load_archive_backend()
        with py7zr.SevenZipFile(output, "w") as archive:
            for child in children:
                check_cancel(cancel_event)
                archive.writeall(child, arcname=child.name)
    elif target_extension in {".tar", ".tar.gz"}:
        if target_extension == ".tar.gz":
            archive_context = tarfile.open(output, "w:gz", compresslevel=6)
        else:
            archive_context = tarfile.open(output, "w")
        with archive_context as archive:
            for child in children:
                check_cancel(cancel_event)
                archive.add(
                    child,
                    arcname=child.name,
                    recursive=True,
                    filter=normalized_tar_info,
                )
    elif target_extension == ".gz":
        files = [path for path in source_root.rglob("*") if path.is_file()]
        if len(files) != 1:
            raise ValueError("GZ output requires an archive containing exactly one file.")
        with files[0].open("rb") as source_stream, output.open("wb") as raw_output:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                compresslevel=6,
                fileobj=raw_output,
                mtime=0,
            ) as compressed:
                while True:
                    check_cancel(cancel_event)
                    block = source_stream.read(1024 * 1024)
                    if not block:
                        break
                    compressed.write(block)
    else:
        raise ValueError("Choose a valid archive format.")


def is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True

    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        return is_junction()

    if os.name != "nt":
        return False
    try:
        return path.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
    except (AttributeError, OSError):
        return False


def stage_archive_sources(
    sources,
    destination: Path,
    cancel_event: Optional[threading.Event] = None,
):
    resolved_sources = []
    top_level_names = set()
    for selected in sources:
        check_cancel(cancel_event)
        selected = Path(os.path.abspath(os.fspath(Path(selected).expanduser())))
        if is_link_or_junction(selected):
            raise ValueError("Links and junctions cannot be added to an archive.")
        if not selected.is_file() and not selected.is_dir():
            raise FileNotFoundError("A selected archive item no longer exists.")
        resolved = selected.resolve()
        name_key = resolved.name.casefold()
        if not resolved.name or name_key in top_level_names:
            raise ValueError("Selected archive items must have unique names.")
        top_level_names.add(name_key)
        resolved_sources.append(resolved)

    if not resolved_sources:
        raise ValueError("Choose at least one file or folder to archive.")

    file_count = 0
    entry_count = 0
    copied_total = [0]
    for source in resolved_sources:
        stack = [(source, destination / source.name)]
        while stack:
            check_cancel(cancel_event)
            current, target = stack.pop()
            entry_count += 1
            if entry_count > MAX_ARCHIVE_FILES:
                raise ValueError("More than 20,000 archive entries were selected.")
            if is_link_or_junction(current):
                raise ValueError("Links and junctions cannot be added to an archive.")
            if current.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                children = []
                for child in current.iterdir():
                    children.append(child)
                    if entry_count + len(stack) + len(children) > MAX_ARCHIVE_FILES:
                        raise ValueError("More than 20,000 archive entries were selected.")
                children.sort(key=lambda path: path.name.casefold(), reverse=True)
                stack.extend((child, target / child.name) for child in children)
            elif current.is_file():
                file_count += 1
                if file_count > MAX_ARCHIVE_FILES:
                    raise ValueError("More than 20,000 files were selected.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with current.open("rb") as source_stream, target.open("xb") as output_stream:
                    copy_limited(
                        source_stream,
                        output_stream,
                        copied_total,
                        cancel_event,
                    )
            else:
                raise ValueError("Only normal files and folders can be archived.")
    return resolved_sources, file_count, copied_total[0]


def create_archive_from_sources(
    sources,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    if target_label not in ARCHIVE_FORMATS:
        raise ValueError("Choose a valid archive format.")
    output = output.expanduser().resolve()
    if extension_for_path(output) != ARCHIVE_FORMATS[target_label]:
        raise ValueError("The output extension does not match the selected format.")

    checked_sources = []
    for selected in sources:
        selected = Path(os.path.abspath(os.fspath(Path(selected).expanduser())))
        if is_link_or_junction(selected):
            raise ValueError("Links and junctions cannot be added to an archive.")
        resolved = selected.resolve()
        if resolved == output:
            raise ValueError("The output cannot overwrite a selected file.")
        if resolved.is_dir():
            try:
                output.relative_to(resolved)
            except ValueError:
                pass
            else:
                raise ValueError("Save the archive outside the selected folder.")
        checked_sources.append(resolved)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_output_path(output)
    try:
        with tempfile.TemporaryDirectory(prefix="file-converter-") as work:
            staged = Path(work) / "selected"
            staged.mkdir()
            _, file_count, total = stage_archive_sources(
                checked_sources,
                staged,
                cancel_event,
            )
            if progress_callback is not None:
                progress_callback(40)
            write_archive(staged, temporary, target_label, cancel_event)
            if progress_callback is not None:
                progress_callback(90)
            validate_archive_output(temporary)
            check_cancel(cancel_event)
            os.replace(temporary, output)
            if progress_callback is not None:
                progress_callback(100)
            size_text = f"{total / (1024 * 1024):.1f} MB"
            return f"Created {output.name} from {file_count} files totaling {size_text}."
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def validate_archive_output(path: Path):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("The converted archive was not created.")
    extension = extension_for_path(path)
    if extension == ".zip":
        with zipfile.ZipFile(path, "r") as archive:
            if not archive.infolist() or archive.testzip() is not None:
                raise RuntimeError("The ZIP archive verification failed.")
    elif extension == ".7z":
        load_archive_backend()
        with py7zr.SevenZipFile(path, "r") as archive:
            if not archive.list() or archive.test() is False:
                raise RuntimeError("The 7Z archive verification failed.")
    elif extension in {".tar", ".tar.gz", ".tgz"}:
        with tarfile.open(path, "r:*") as archive:
            if not archive.getmembers():
                raise RuntimeError("The TAR archive verification failed.")
    elif extension == ".gz":
        with gzip.open(path, "rb") as archive:
            archive.read(1)
    else:
        raise RuntimeError("The archive extension verification failed.")


def convert_archive(
    source: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    if target_label not in ARCHIVE_FORMATS:
        raise ValueError("Choose a valid archive format.")
    if source.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("The archive is larger than the 2 GB limit.")
    if extension_for_path(output) != ARCHIVE_FORMATS[target_label]:
        raise ValueError("The output extension does not match the selected format.")

    temporary = temporary_output_path(output)
    try:
        with tempfile.TemporaryDirectory(prefix="file-converter-") as work:
            extracted = Path(work) / "extracted"
            extracted.mkdir()
            try:
                file_count, total = extract_archive(
                    source,
                    extracted,
                    cancel_event,
                )
            except Exception as error:
                if py7zr is not None and isinstance(
                    error,
                    py7zr.exceptions.PasswordRequired,
                ):
                    raise ValueError(
                        "Password-protected 7Z files are not supported."
                    ) from error
                raise
            if progress_callback is not None:
                progress_callback(45)
            write_archive(extracted, temporary, target_label, cancel_event)
            if progress_callback is not None:
                progress_callback(90)
            validate_archive_output(temporary)
            check_cancel(cancel_event)
            os.replace(temporary, output)
            if progress_callback is not None:
                progress_callback(100)
            size_text = f"{total / (1024 * 1024):.1f} MB"
            return f"Created {output.name} from {file_count} files totaling {size_text}."
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def convert_file(
    source: Path,
    output: Path,
    target_label: str,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    process_controller=None,
) -> str:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError("The selected file no longer exists.")
    source_extension = extension_for_path(source)
    if source_extension not in SUPPORTED_EXTENSIONS:
        raise ValueError("The selected file type is not supported.")
    if source == output:
        raise ValueError("The output cannot overwrite the original file.")
    output.parent.mkdir(parents=True, exist_ok=True)

    if source_extension in IMAGE_EXTENSIONS:
        return convert_image(source, output, target_label, cancel_event)
    if source_extension in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
        return convert_media(
            source,
            output,
            target_label,
            cancel_event,
            progress_callback,
            process_controller,
        )
    if source_extension in ARCHIVE_EXTENSIONS:
        return convert_archive(
            source,
            output,
            target_label,
            cancel_event,
            progress_callback,
        )
    return convert_script(source, output, target_label, cancel_event)


def run_self_test(folder: Path) -> int:
    assert APP_VERSION == "1.0.6"
    folder.mkdir(parents=True, exist_ok=True)
    if Image is not None or py7zr is not None:
        raise RuntimeError("Conversion backends were loaded before first use.")
    load_image_backend()
    if Image is None or ImageOps is None or features is None:
        raise RuntimeError("The image backend did not finish loading.")
    if screen_aware_window_dimensions(400, 300) != (368, 268, 368, 268):
        raise RuntimeError("Small-screen window sizing is not bounded correctly.")

    try:
        raise RuntimeError("self-test exception detail")
    except RuntimeError:
        error_type, error, trace = sys.exc_info()
    exception_log = folder / "unhandled-error.log"
    write_exception_log(error_type, error, trace, exception_log)
    exception_text = exception_log.read_text(encoding="utf-8")
    if (
        f"{APP_TITLE} {APP_VERSION}" not in exception_text
        or "RuntimeError: self-test exception detail" not in exception_text
    ):
        raise RuntimeError("Unhandled exception logging lost important details.")

    cleanup_calls = []

    class BrokenCleanupProcess:
        def poll(self):
            cleanup_calls.append("poll")
            raise OSError("mocked poll failure")

        def kill(self):
            cleanup_calls.append("kill")
            raise OSError("mocked kill failure")

        def wait(self, timeout):
            cleanup_calls.append(("wait", timeout))
            raise subprocess.TimeoutExpired("mocked", timeout)

    terminate_subprocess_safely(BrokenCleanupProcess(), timeout=0.01)
    if cleanup_calls != ["poll", "kill", ("wait", 0.01)]:
        raise RuntimeError("FFmpeg cleanup did not remain best-effort after failures.")

    if NATIVE_KERNEL32 is not None:
        test_mutex_name = f"Local\\FleeceFileConverterSelfTest-{uuid.uuid4().hex}"
        first_status, first_handle = _try_create_named_mutex(test_mutex_name)
        if first_status != "acquired" or not first_handle:
            raise RuntimeError("The app-instance mutex could not be acquired.")
        try:
            second_status, second_handle = _try_create_named_mutex(test_mutex_name)
            if second_handle:
                NATIVE_KERNEL32.CloseHandle(second_handle)
            if second_status != "exists":
                raise RuntimeError("The app-instance mutex did not reject a duplicate.")
        finally:
            NATIVE_KERNEL32.CloseHandle(first_handle)

    source_png = folder / "source.png"
    pixels = []
    for y in range(48):
        for x in range(80):
            alpha = 0 if x < 8 else min(255, (x - 8) * 5)
            pixels.append((x * 3 % 256, y * 5 % 256, 180, alpha))
    image = Image.new("RGBA", (80, 48))
    image.putdata(pixels)
    image.save(source_png, format="PNG")

    image_outputs = {}
    for label, (extension, output_format) in IMAGE_FORMATS.items():
        if label == "PNG image (.png)":
            continue
        output = folder / f"check{extension}"
        convert_file(source_png, output, label)
        validate_image_output(output, output_format)
        image_outputs[label] = output

    for label, source in image_outputs.items():
        source_name = extension_for_path(source).lstrip(".")
        output = folder / f"round-{source_name}.png"
        convert_file(source, output, "PNG image (.png)")
        validate_image_output(output, "PNG")

    jpeg_source = folder / "check.jpeg"
    shutil.copyfile(folder / "check.jpg", jpeg_source)
    tif_source = folder / "check.tif"
    shutil.copyfile(folder / "check.tiff", tif_source)
    heif_source = folder / "check.heif"
    shutil.copyfile(folder / "check.heic", heif_source)
    for alias in (jpeg_source, tif_source, heif_source):
        alias_output = folder / f"alias-{alias.suffix.lstrip('.')}.png"
        convert_file(alias, alias_output, "PNG image (.png)")
        validate_image_output(alias_output, "PNG")

    animated_gif = folder / "animated.gif"
    first_frame = Image.new("RGBA", (32, 24), (255, 0, 0, 255))
    second_frame = Image.new("RGBA", (32, 24), (0, 0, 255, 255))
    first_frame.save(
        animated_gif,
        save_all=True,
        append_images=[second_frame],
        duration=[50, 90],
        loop=2,
    )
    for label in (
        "PNG image (.png)",
        "GIF image (.gif)",
        "WEBP image (.webp)",
        "TIFF image (.tiff)",
        "AVIF image (.avif)",
        "HEIC image (.heic)",
    ):
        extension, output_format = IMAGE_FORMATS[label]
        animated_output = folder / f"animated-output{extension}"
        animated_message = convert_file(animated_gif, animated_output, label)
        validate_image_output(animated_output, output_format, 2)
        if "Preserved all 2 frames" not in animated_message:
            raise RuntimeError("The animated image preservation test failed.")
    static_message = convert_file(
        animated_gif,
        folder / "animated-first-frame.jpg",
        "JPG image (.jpg)",
    )
    if "first of 2 frames" not in static_message:
        raise RuntimeError("The static image frame notice test failed.")

    varying_tiff = folder / "varying-frame-sizes.tiff"
    small_frame = Image.new("RGB", (10, 10), (1, 2, 3))
    large_frame = Image.new("RGB", (40, 30), (4, 5, 6))
    small_frame.save(
        varying_tiff,
        format="TIFF",
        save_all=True,
        append_images=[large_frame],
    )
    original_pixel_limit = globals()["MAX_IMAGE_TOTAL_PIXELS"]
    globals()["MAX_IMAGE_TOTAL_PIXELS"] = 1_000
    try:
        try:
            convert_file(
                varying_tiff,
                folder / "varying-frame-sizes.png",
                "PNG image (.png)",
            )
        except ValueError as error:
            if "too large" not in str(error):
                raise RuntimeError("Variable frame sizes gave an unclear error.") from error
        else:
            raise RuntimeError("Later oversized image frames bypassed the pixel limit.")
    finally:
        globals()["MAX_IMAGE_TOTAL_PIXELS"] = original_pixel_limit

    source_wav = folder / "audio.wav"
    sample_rate = 16000
    with wave.open(str(source_wav), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate // 2):
            value = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        audio.writeframes(frames)

    audio_outputs = {}
    for label, (extension, _) in AUDIO_FORMATS.items():
        if label == "WAV audio (.wav)":
            continue
        output = folder / f"audio{extension}"
        convert_file(source_wav, output, label)
        validate_media_output(output, "audio", FFPROBE_PATH)
        audio_outputs[label] = output
    for source in audio_outputs.values():
        source_name = source.suffix.lstrip(".")
        output = folder / f"audio-round-{source_name}.wav"
        convert_file(source, output, "WAV audio (.wav)")
        validate_media_output(output, "audio", FFPROBE_PATH)
    copied_audio = folder / "audio-copy.m4a"
    copied_audio_message = convert_file(
        audio_outputs["AAC audio (.aac)"],
        copied_audio,
        "M4A audio (.m4a)",
    )
    validate_media_output(copied_audio, "audio", FFPROBE_PATH)
    if "without re-encoding" not in copied_audio_message:
        raise RuntimeError("The audio stream copy test failed.")

    source_video = folder / "video.mp4"
    video_result = subprocess.run(
        [
            str(FFMPEG_PATH),
            "-hide_banner",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=96x64:rate=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000",
            "-t",
            "0.5",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source_video),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if video_result.returncode != 0:
        raise RuntimeError(video_result.stderr.strip() or "Video test setup failed.")

    video_outputs = {}
    video_messages = {}
    for label, (extension, _) in VIDEO_FORMATS.items():
        if label == "MP4 video (.mp4)":
            continue
        output = folder / f"video{extension}"
        video_messages[label] = convert_file(source_video, output, label)
        validate_media_output(output, "video", FFPROBE_PATH)
        video_outputs[label] = output
    for source in video_outputs.values():
        source_name = source.suffix.lstrip(".")
        output = folder / f"video-round-{source_name}.mp4"
        convert_file(source, output, "MP4 video (.mp4)")
        validate_media_output(output, "video", FFPROBE_PATH)
    if "without re-encoding" not in video_messages["MOV video (.mov)"]:
        raise RuntimeError("The video stream copy test failed.")
    if "re-encoding" not in video_messages["WEBM video (.webm)"]:
        raise RuntimeError("The video re-encoding fallback test failed.")
    source_streams = {
        (stream.get("codec_type"), stream.get("codec_name"))
        for stream in probe_media(source_video, FFPROBE_PATH).get("streams", [])
    }
    copied_streams = {
        (stream.get("codec_type"), stream.get("codec_name"))
        for stream in probe_media(
            video_outputs["MOV video (.mov)"],
            FFPROBE_PATH,
        ).get("streams", [])
    }
    if source_streams != copied_streams:
        raise RuntimeError("The copied video codec verification failed.")
    extracted_audio = folder / "video-audio.mp3"
    convert_file(source_video, extracted_audio, "MP3 audio (.mp3)")
    validate_media_output(extracted_audio, "audio", FFPROBE_PATH)

    source_archive = folder / "archive.zip"
    with zipfile.ZipFile(source_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("folder/data.txt", b"file-converter-archive-ok")
    non_7z_output = folder / "archive-without-7z.tar"
    convert_file(source_archive, non_7z_output, "TAR archive (.tar)")
    validate_archive_output(non_7z_output)
    if py7zr is not None:
        raise RuntimeError("Non-7Z archive work loaded the 7Z backend.")
    archive_outputs = {}
    for label, extension in ARCHIVE_FORMATS.items():
        if label == "ZIP archive (.zip)":
            continue
        output = folder / f"archive{extension}"
        convert_file(source_archive, output, label)
        validate_archive_output(output)
        archive_outputs[label] = output
    if py7zr is None:
        raise RuntimeError("7Z work did not load the 7Z backend.")
    for source in archive_outputs.values():
        source_name = extension_for_path(source).replace(".", "-").strip("-")
        output = folder / f"archive-round-{source_name}.zip"
        convert_file(source, output, "ZIP archive (.zip)")
        validate_archive_output(output)
        with zipfile.ZipFile(output, "r") as archive:
            payloads = [
                archive.read(info)
                for info in archive.infolist()
                if not info.is_dir()
            ]
        if b"file-converter-archive-ok" not in payloads:
            raise RuntimeError("The archive content round-trip test failed.")

    tgz_source = folder / "archive.tgz"
    shutil.copyfile(folder / "archive.tar.gz", tgz_source)
    tgz_output = folder / "archive-tgz.zip"
    convert_file(tgz_source, tgz_output, "ZIP archive (.zip)")
    validate_archive_output(tgz_output)

    package_folder = folder / "package-folder"
    package_folder.mkdir()
    (package_folder / "nested").mkdir()
    (package_folder / "nested" / "inside.txt").write_bytes(b"inside")
    loose_file = folder / "loose.txt"
    loose_file.write_bytes(b"loose")
    for label, extension in ARCHIVE_FORMATS.items():
        if extension == ".gz":
            continue
        output = folder / f"selected-items{extension}"
        create_archive_from_sources(
            [package_folder, loose_file],
            output,
            label,
        )
        validate_archive_output(output)
    selected_zip = folder / "selected-items.zip"
    with zipfile.ZipFile(selected_zip, "r") as archive:
        if archive.read("package-folder/nested/inside.txt") != b"inside":
            raise RuntimeError("The folder archive creation test failed.")
        if archive.read("loose.txt") != b"loose":
            raise RuntimeError("The file archive creation test failed.")

    selected_gz = folder / "selected-file.gz"
    create_archive_from_sources(
        [loose_file],
        selected_gz,
        "GZ compressed file (.gz)",
    )
    with gzip.open(selected_gz, "rb") as archive:
        if archive.read() != b"loose":
            raise RuntimeError("The selected file GZ creation test failed.")

    try:
        create_archive_from_sources(
            [package_folder],
            package_folder / "inside.zip",
            "ZIP archive (.zip)",
        )
    except ValueError:
        pass
    else:
        raise RuntimeError("The nested output archive protection test failed.")

    multi_archive = folder / "multi.zip"
    with zipfile.ZipFile(multi_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.txt", b"one")
        archive.writestr("two.txt", b"two")
    try:
        convert_file(multi_archive, folder / "multi.gz", "GZ compressed file (.gz)")
    except ValueError:
        pass
    else:
        raise RuntimeError("The multi-file GZ rejection test failed.")

    escape_name = f"file-converter-escape-{uuid.uuid4().hex}.txt"
    escape_path = folder.parent / escape_name
    unsafe_archive = folder / "unsafe.zip"
    with zipfile.ZipFile(unsafe_archive, "w") as archive:
        archive.writestr(f"../{escape_name}", b"unsafe")
    try:
        convert_file(unsafe_archive, folder / "unsafe.7z", "7Z archive (.7z)")
    except ValueError:
        pass
    else:
        raise RuntimeError("The unsafe archive path test failed.")
    if escape_path.exists():
        escape_path.unlink()
        raise RuntimeError("The archive path protection test failed.")

    entry_limit_archive = folder / "entry-limit.zip"
    with zipfile.ZipFile(entry_limit_archive, "w") as archive:
        for index in range(4):
            archive.writestr(f"directory-{index}/", b"")
    entry_limit_source = folder / "entry-limit-source"
    entry_limit_source.mkdir(exist_ok=True)
    for index in range(3):
        (entry_limit_source / f"directory-{index}").mkdir(exist_ok=True)
    original_archive_limit = globals()["MAX_ARCHIVE_FILES"]
    globals()["MAX_ARCHIVE_FILES"] = 3
    try:
        with tempfile.TemporaryDirectory(
            prefix="file-converter-entry-limit-",
            dir=folder,
        ) as limited_destination:
            try:
                extract_archive(entry_limit_archive, Path(limited_destination))
            except ValueError as error:
                if "entries" not in str(error):
                    raise RuntimeError("The extraction entry limit gave an unclear error.") from error
            else:
                raise RuntimeError("Archive directories bypassed the extraction entry limit.")
        try:
            create_archive_from_sources(
                [entry_limit_source],
                folder / "entry-limit-output.zip",
                "ZIP archive (.zip)",
            )
        except ValueError as error:
            if "entries" not in str(error):
                raise RuntimeError("The creation entry limit gave an unclear error.") from error
        else:
            raise RuntimeError("Selected directories bypassed the archive entry limit.")
    finally:
        globals()["MAX_ARCHIVE_FILES"] = original_archive_limit

    batch_source = folder / "check.bat"
    batch_source.write_bytes(b"@echo off\r\necho file-converter-ok\r\n")
    batch_output = folder / "check.cmd"
    convert_file(batch_source, batch_output, "CMD script (.cmd)")
    if sha256_file(batch_source) != sha256_file(batch_output):
        raise RuntimeError("The BAT to CMD content test failed.")
    batch_round_trip = folder / "batch-round-trip.bat"
    convert_file(batch_output, batch_round_trip, "BAT script (.bat)")
    if sha256_file(batch_source) != sha256_file(batch_round_trip):
        raise RuntimeError("The CMD to BAT content test failed.")

    python_source = folder / "check.py"
    python_source.write_bytes(b"print('file-converter-ok')\n")
    python_output = folder / "check.pyw"
    convert_file(python_source, python_output, "Python window script (.pyw)")
    if sha256_file(python_source) != sha256_file(python_output):
        raise RuntimeError("The PY to PYW content test failed.")
    python_round_trip = folder / "python-round-trip.py"
    convert_file(python_output, python_round_trip, "Python script (.py)")
    if sha256_file(python_source) != sha256_file(python_round_trip):
        raise RuntimeError("The PYW to PY content test failed.")

    invalid_image = folder / "invalid.png"
    invalid_image.write_bytes(b"not-an-image")
    try:
        convert_file(invalid_image, folder / "invalid.jpg", "JPG image (.jpg)")
    except ValueError:
        pass
    else:
        raise RuntimeError("The invalid image test failed.")

    try:
        convert_file(source_png, source_png, "PNG image (.png)")
    except ValueError:
        pass
    else:
        raise RuntimeError("The source overwrite test failed.")

    application = QApplication.instance() or QApplication([])
    window = FileConverter()
    window.show()
    application.processEvents()
    screen = application.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        if (
            window.minimumWidth() > max(1, available.width() - 32)
            or window.minimumHeight() > max(1, available.height() - 32)
        ):
            raise RuntimeError("The app minimum size exceeds the available screen.")
        window.move(available.right() - 8, available.top())
        application.processEvents()
        window.category_dropdown.show_popup()
        popup_geometry = window.category_dropdown.popup.geometry()
        if (
            popup_geometry.left() < available.left()
            or popup_geometry.right() > available.right()
            or popup_geometry.top() < available.top()
            or popup_geometry.bottom() > available.bottom()
        ):
            raise RuntimeError("A dropdown popup escaped the available screen.")

        escape_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        if not window.category_dropdown.eventFilter(application, escape_event):
            raise RuntimeError("Escape did not dismiss an open dropdown.")
        if not window.category_dropdown._closing:
            raise RuntimeError("Escape did not start dropdown dismissal.")
        window.category_dropdown._stop_popup_animation()
        window.category_dropdown.popup.hide()
        window.category_dropdown._closing = False

        window.category_dropdown.popup.show()
        application.installEventFilter(window.category_dropdown)
        window.category_dropdown.eventFilter(
            application,
            QEvent(QEvent.ApplicationDeactivate),
        )
        if not window.category_dropdown._closing:
            raise RuntimeError("Application deactivation did not dismiss a dropdown.")
        window.category_dropdown._stop_popup_animation()
        window.category_dropdown.popup.hide()
        window.category_dropdown._closing = False
        application.removeEventFilter(window.category_dropdown)
    window.set_source_file(source_png)
    worker_start_folder = folder / f"worker-start-{uuid.uuid4().hex}"
    window.output_folder = worker_start_folder
    worker_globals = window.start_conversion.__globals__
    original_qthread = worker_globals["QThread"]
    original_conversion_worker = worker_globals["ConversionWorker"]
    cancellation_snapshots = []

    class CancellationProbeWorker(original_conversion_worker):
        def cancel(self):
            super().cancel()
            cancellation_snapshots.append(self.cancel_event.is_set())

    class FailingStartThread(original_qthread):
        def start(self, *args, **kwargs):
            del args, kwargs
            raise RuntimeError("mocked worker start failure")

    worker_globals["ConversionWorker"] = CancellationProbeWorker
    worker_globals["QThread"] = FailingStartThread
    try:
        window.start_conversion()
    finally:
        worker_globals["QThread"] = original_qthread
        worker_globals["ConversionWorker"] = original_conversion_worker
    if (
        window.running
        or window.worker is not None
        or window.worker_thread is not None
        or window.output_file is not None
        or window.convert_button.text() != "Convert"
        or not window.convert_button.isEnabled()
        or not window.file_browse_button.isEnabled()
        or not window.output_browse_button.isEnabled()
        or window.progress_bar.value() != 0
        or window.status_label.text() != "Conversion could not start"
        or "No output was changed" not in window.log_box.toPlainText()
        or cancellation_snapshots != [True]
    ):
        raise RuntimeError("A QThread.start failure wedged the conversion UI.")

    partial_start_seen = threading.Event()
    partial_start_release = threading.Event()

    class BlockingStartProbeWorker(original_conversion_worker):
        @Slot()
        def run(self):
            partial_start_seen.set()
            partial_start_release.wait(5)
            self.finished.emit("cancelled", "Conversion cancelled.")

    class PartiallyFailingStartThread(original_qthread):
        def run(self):
            partial_start_seen.set()
            partial_start_release.wait(5)

        def start(self, *args, **kwargs):
            super().start(*args, **kwargs)
            if not partial_start_seen.wait(2):
                raise RuntimeError("mocked worker did not launch")
            raise RuntimeError("mocked partial worker start failure")

    active_partial_thread = None
    worker_globals["ConversionWorker"] = BlockingStartProbeWorker
    worker_globals["QThread"] = PartiallyFailingStartThread
    try:
        window.start_conversion()
        active_partial_thread = window.worker_thread
        partial_state = (
            window.running,
            window.worker is not None,
            active_partial_thread is not None,
            window.convert_button.text(),
            window.convert_button.isEnabled(),
            window.status_label.text(),
        )
        if partial_state != (
            True,
            True,
            True,
            "Stopping...",
            False,
            "Stopping after start failure",
        ):
            raise RuntimeError(
                f"A partially started conversion worker was deleted unsafely: {partial_state!r}"
            )
    finally:
        worker_globals["QThread"] = original_qthread
        worker_globals["ConversionWorker"] = original_conversion_worker
        partial_start_release.set()
        if active_partial_thread is not None:
            active_partial_thread.quit()
            active_partial_thread.wait(3000)
        application.processEvents()
    if (
        window.running
        or window.worker is not None
        or window.worker_thread is not None
        or window.convert_button.text() != "Convert"
        or not window.convert_button.isEnabled()
    ):
        raise RuntimeError("A partially started conversion worker did not clean up safely.")
    window.close()
    application.processEvents()

    (folder / "self-test-passed.txt").write_text(
        "File Converter self-test passed.\n",
        encoding="utf-8",
    )
    print("File Converter self-test passed.")
    return 0


class TrafficLightButton(QPushButton):
    def __init__(self, color_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setObjectName(color_name)
        self.setToolTip(tooltip)
        self.setFixedSize(13, 13)
        self.setCursor(Qt.PointingHandCursor)


class TitleBar(QFrame):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.drag_offset = QPoint()
        self.setObjectName("titleBar")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(8)

        maximize_button = TrafficLightButton("maximizeDot", "Maximize")
        minimize_button = TrafficLightButton("minimizeDot", "Minimize")
        close_button = TrafficLightButton("closeDot", "Close")
        close_button.clicked.connect(host.close)
        minimize_button.clicked.connect(host.showMinimized)
        maximize_button.clicked.connect(self.toggle_maximized)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addWidget(maximize_button)
        controls.addWidget(minimize_button)
        controls.addWidget(close_button)

        controls_holder = QWidget()
        controls_holder.setFixedWidth(64)
        controls_holder.setLayout(controls)

        title = QLabel(APP_TITLE)
        title.setObjectName("windowTitle")
        title.setAlignment(Qt.AlignCenter)

        left_spacer = QWidget()
        left_spacer.setFixedWidth(64)

        layout.addWidget(left_spacer)
        layout.addStretch()
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(controls_holder)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.host.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and not self.host.isMaximized():
            self.host.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()


class ChevronButton(QPushButton):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(Qt.white, 1.4))
        x = self.width() - 20
        y = self.height() // 2 - 1
        painter.drawLine(x - 4, y - 2, x, y + 2)
        painter.drawLine(x, y + 2, x + 4, y - 2)


class AnimatedDropdown(QWidget):
    changed = Signal(str)

    def __init__(self, items, current_index=0, parent=None):
        super().__init__(parent)
        self.items = []
        self._current = ""
        self._animation = None
        self._closing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = ChevronButton()
        self.button.setObjectName("dropdownButton")
        self.button.setMinimumHeight(38)
        self.button.clicked.connect(self.toggle_popup)
        layout.addWidget(self.button)

        self.popup = QFrame(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint,
        )
        self.popup.setObjectName("dropdownPopup")
        self.popup.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self.popup)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = QFrame()
        self.surface.setObjectName("dropdownSurface")
        self.surface_layout = QVBoxLayout(self.surface)
        self.surface_layout.setContentsMargins(5, 5, 5, 5)
        self.surface_layout.setSpacing(2)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("dropdownScroll")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setWidget(self.surface)
        outer.addWidget(self.scroll_area)

        self.set_items(items, current_index)

    def currentText(self):
        return self._current

    def set_items(self, items, current_index=0):
        self.hide_popup()
        while self.surface_layout.count():
            item = self.surface_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.items = list(items)
        if not self.items:
            self.items = ["Unavailable"]
        current_index = max(0, min(current_index, len(self.items) - 1))
        self._current = self.items[current_index]
        self.button.setText(self._current)

        for value in self.items:
            option = QPushButton(value)
            option.setObjectName("dropdownOption")
            option.setMinimumHeight(32)
            option.clicked.connect(
                lambda checked=False, selected=value: self.select(selected)
            )
            self.surface_layout.addWidget(option)
        self.surface.setMinimumHeight(len(self.items) * 34 + 10)

    def select(self, value):
        if value not in self.items:
            return
        changed = value != self._current
        self._current = value
        self.button.setText(value)
        self.hide_popup()
        if changed:
            self.changed.emit(value)

    def toggle_popup(self):
        if not self.isEnabled():
            return
        if self.popup.isVisible() and not self._closing:
            self.hide_popup()
        else:
            self.show_popup()

    def show_popup(self):
        self._stop_popup_animation()
        self._closing = False
        popup_height = min(len(self.items) * 34 + 12, 284)
        popup_width = self.width()
        button_top_left = self.mapToGlobal(QPoint(0, 0))
        below_y = button_top_left.y() + self.height() + 4
        screen = QApplication.screenAt(button_top_left) or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect()

        if available:
            popup_width = min(popup_width, available.width())
            popup_height = min(popup_height, available.height())
        if available and below_y + popup_height - 1 > available.bottom():
            final_y = button_top_left.y() - popup_height - 4
        else:
            final_y = below_y
        final_x = button_top_left.x()
        if available:
            final_x = min(final_x, available.right() - popup_width + 1)
            final_x = max(available.left(), final_x)
            final_y = min(final_y, available.bottom() - popup_height + 1)
            final_y = max(available.top(), final_y)

        end_rect = QRect(
            final_x,
            final_y,
            popup_width,
            popup_height,
        )
        QApplication.instance().installEventFilter(self)
        self.popup.setGeometry(end_rect)
        self.popup.setWindowOpacity(0.0)
        self.popup.show()
        self.popup.raise_()

        opacity_animation = QPropertyAnimation(
            self.popup, b"windowOpacity", self
        )
        opacity_animation.setDuration(110)
        opacity_animation.setStartValue(0.0)
        opacity_animation.setEndValue(1.0)
        opacity_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation = opacity_animation
        opacity_animation.finished.connect(
            lambda current=opacity_animation: self._popup_animation_finished(
                current, False
            )
        )
        opacity_animation.start()

    def hide_popup(self):
        if not hasattr(self, "popup") or not self.popup.isVisible():
            return
        self._stop_popup_animation()
        self._closing = True
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)

        opacity_animation = QPropertyAnimation(
            self.popup, b"windowOpacity", self
        )
        opacity_animation.setDuration(75)
        opacity_animation.setStartValue(self.popup.windowOpacity())
        opacity_animation.setEndValue(0.0)
        opacity_animation.setEasingCurve(QEasingCurve.InCubic)
        self._animation = opacity_animation
        opacity_animation.finished.connect(
            lambda current=opacity_animation: self._popup_animation_finished(
                current, True
            )
        )
        opacity_animation.start()

    def _stop_popup_animation(self):
        if self._animation is None:
            return
        animation = self._animation
        self._animation = None
        animation.stop()
        animation.deleteLater()

    def _popup_animation_finished(self, animation, hide_after):
        if self._animation is animation:
            self._animation = None
        if hide_after:
            self.popup.hide()
            self.popup.setWindowOpacity(1.0)
            self._closing = False
        animation.deleteLater()

    def eventFilter(self, watched, event):
        if self.popup.isVisible() and event.type() == QEvent.MouseButtonPress:
            global_position = event.globalPosition().toPoint()
            popup_rect = self.popup.frameGeometry()
            button_rect = QRect(
                self.button.mapToGlobal(QPoint(0, 0)),
                self.button.size(),
            )
            if (
                not popup_rect.contains(global_position)
                and not button_rect.contains(global_position)
            ):
                self.hide_popup()
        elif self.popup.isVisible() and event.type() in {
            QEvent.ApplicationDeactivate,
            QEvent.WindowDeactivate,
        }:
            self.hide_popup()
        elif (
            self.popup.isVisible()
            and event.type() == QEvent.KeyPress
            and event.key() == Qt.Key_Escape
        ):
            self.hide_popup()
            return True
        return super().eventFilter(watched, event)


class ConversionWorker(QObject):
    finished = Signal(str, str)
    progress = Signal(int)

    def __init__(
        self,
        source: Optional[Path],
        output: Path,
        target_label: str,
        archive_sources=(),
    ):
        super().__init__()
        self.source = source
        self.output = output
        self.target_label = target_label
        self.archive_sources = tuple(archive_sources)
        self.cancel_event = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None

    def set_process(self, process):
        with self.process_lock:
            self.process = process
            should_cancel = self.cancel_event.is_set()
        if should_cancel and process.poll() is None:
            process.kill()

    def clear_process(self, process):
        with self.process_lock:
            if self.process is process:
                self.process = None

    def cancel(self):
        self.cancel_event.set()
        with self.process_lock:
            process = self.process
        if process is not None and process.poll() is None:
            process.kill()

    def report_progress(self, value: int):
        self.progress.emit(max(0, min(100, int(value))))

    @Slot()
    def run(self):
        try:
            if self.archive_sources:
                message = create_archive_from_sources(
                    self.archive_sources,
                    self.output,
                    self.target_label,
                    self.cancel_event,
                    self.report_progress,
                )
            elif self.source is not None:
                message = convert_file(
                    self.source,
                    self.output,
                    self.target_label,
                    self.cancel_event,
                    self.report_progress,
                    self,
                )
            else:
                raise ValueError("Choose a file or folder first.")
            check_cancel(self.cancel_event)
            self.finished.emit("success", message)
        except ConversionCancelled:
            self.finished.emit("cancelled", "Conversion cancelled.")
        except Exception as error:
            self.finished.emit("failed", str(error) or error.__class__.__name__)


class FileConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        screen = QApplication.primaryScreen()
        available = (
            screen.availableGeometry() if screen is not None else QRect(0, 0, 660, 570)
        )
        width, height, minimum_width, minimum_height = screen_aware_window_dimensions(
            available.width(), available.height()
        )
        self.resize(width, height)
        self.setMinimumSize(minimum_width, minimum_height)

        self.source_file: Optional[Path] = None
        self.archive_sources = []
        self.output_folder = Path.home() / "Downloads"
        self.output_file: Optional[Path] = None
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[ConversionWorker] = None
        self.running = False
        self.last_log_message = ""

        self.apply_style()
        self.build_ui()
        self.category_changed("Images")

    def apply_style(self):
        QApplication.instance().setStyleSheet(
            """
            QWidget {
                color: #f5f5f5;
                font-family: "Segoe UI";
                font-size: 13px;
            }

            QFrame#windowFrame {
                background: #070707;
                border: 1px solid #252525;
                border-radius: 14px;
            }

            QFrame#titleBar {
                background: #070707;
                border: none;
                border-bottom: 1px solid #1c1c1c;
                border-top-left-radius: 14px;
                border-top-right-radius: 14px;
            }

            QLabel#windowTitle {
                color: #bdbdbd;
                font-size: 12px;
                font-weight: 600;
            }

            QPushButton#closeDot,
            QPushButton#minimizeDot,
            QPushButton#maximizeDot {
                border: none;
                border-radius: 6px;
                min-height: 13px;
                max-height: 13px;
                min-width: 13px;
                max-width: 13px;
                padding: 0;
            }

            QPushButton#closeDot { background: #ff5f57; }
            QPushButton#minimizeDot { background: #febc2e; }
            QPushButton#maximizeDot { background: #28c840; }

            QPushButton#closeDot:hover,
            QPushButton#minimizeDot:hover,
            QPushButton#maximizeDot:hover {
                border: 1px solid rgba(0, 0, 0, 90);
            }

            QLabel#label {
                color: #b8b8b8;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#status {
                color: #8b8b8b;
                font-size: 12px;
            }

            QLabel#note {
                color: #7a7a7a;
                font-size: 11px;
            }

            QFrame#panel {
                background: #0d0d0d;
                border: 1px solid #242424;
                border-radius: 14px;
            }

            QPushButton {
                background: #151515;
                border: 1px solid #2b2b2b;
                border-radius: 10px;
                min-height: 38px;
                padding: 0 14px;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #1d1d1d;
                border-color: #3a3a3a;
            }

            QPushButton:pressed { background: #101010; }

            QPushButton:disabled {
                color: #555555;
                background: #101010;
                border-color: #202020;
            }

            QPushButton#primary {
                background: #ffffff;
                color: #000000;
                border: none;
                min-height: 42px;
            }

            QPushButton#primary:hover { background: #e7e7e7; }
            QPushButton#primary:disabled { background: #777777; color: #202020; }

            QPushButton#small {
                min-height: 28px;
                max-height: 28px;
                border-radius: 8px;
                padding: 0 10px;
                color: #bdbdbd;
                font-size: 11px;
            }

            QPushButton#dropdownButton {
                background: #0a0a0a;
                border: 1px solid #292929;
                border-radius: 10px;
                min-height: 38px;
                padding: 0 38px 0 12px;
                text-align: left;
                font-weight: 500;
            }

            QPushButton#dropdownButton:hover {
                background: #101010;
                border-color: #3b3b3b;
            }

            QFrame#dropdownSurface {
                background: #111111;
                border: 1px solid #303030;
                border-radius: 11px;
            }

            QScrollArea#dropdownScroll {
                background: transparent;
                border: none;
            }

            QPushButton#dropdownOption {
                background: transparent;
                border: none;
                border-radius: 7px;
                min-height: 32px;
                padding: 0 10px;
                text-align: left;
                font-weight: 500;
            }

            QPushButton#dropdownOption:hover { background: #242424; }

            QFrame#pathFrame {
                background: #0a0a0a;
                border: 1px solid #292929;
                border-radius: 10px;
            }

            QLabel#pathLabel {
                color: #d7d7d7;
                padding-left: 11px;
            }

            QTextEdit {
                background: #090909;
                color: #c8c8c8;
                border: 1px solid #242424;
                border-radius: 10px;
                padding: 8px;
                font-family: "Cascadia Mono", "Consolas";
                font-size: 11px;
                selection-background-color: #ffffff;
                selection-color: #000000;
            }

            QProgressBar {
                background: #121212;
                border: none;
                border-radius: 3px;
                min-height: 6px;
                max-height: 6px;
            }

            QProgressBar::chunk {
                background: #ffffff;
                border-radius: 3px;
            }

            QScrollBar:vertical {
                width: 8px;
                background: transparent;
            }

            QScrollBar::handle:vertical {
                background: #333333;
                border-radius: 4px;
                min-height: 24px;
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            """
        )

    def build_ui(self):
        label_gap = 6
        group_gap = 10
        side_button_width = 84

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        window_frame = QFrame()
        window_frame.setObjectName("windowFrame")
        outer.addWidget(window_frame)
        window_layout = QVBoxLayout(window_frame)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)
        window_layout.addWidget(TitleBar(self))

        content = QWidget()
        window_layout.addWidget(content, 1)
        page = QVBoxLayout(content)
        page.setContentsMargins(22, 18, 22, 18)
        page.setSpacing(0)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(group_gap)

        file_group = QVBoxLayout()
        file_group.setSpacing(label_gap)
        self.file_label = QLabel("Image or script file")
        self.file_label.setObjectName("label")
        file_group.addWidget(self.file_label)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_frame = QFrame()
        file_frame.setObjectName("pathFrame")
        file_frame.setMinimumHeight(38)
        file_layout = QHBoxLayout(file_frame)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_path_label = QLabel("Choose a file or drag it here")
        self.file_path_label.setObjectName("pathLabel")
        self.file_path_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.file_path_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.file_path_label.setMinimumWidth(0)
        file_layout.addWidget(self.file_path_label)
        self.file_browse_button = QPushButton("Browse")
        self.file_browse_button.setFixedWidth(side_button_width)
        self.file_browse_button.clicked.connect(self.choose_file)
        file_row.addWidget(file_frame, 1)
        file_row.addWidget(self.file_browse_button)
        file_group.addLayout(file_row)
        layout.addLayout(file_group)

        selectors = QHBoxLayout()
        selectors.setSpacing(10)
        category_column = QVBoxLayout()
        category_column.setSpacing(label_gap)
        category_label = QLabel("Category")
        category_label.setObjectName("label")
        self.category_dropdown = AnimatedDropdown(
            ["Images", "Audio", "Video", "Archives", "Scripts"]
        )
        self.category_dropdown.changed.connect(self.category_changed)
        category_column.addWidget(category_label)
        category_column.addWidget(self.category_dropdown)

        format_column = QVBoxLayout()
        format_column.setSpacing(label_gap)
        format_label = QLabel("Convert to")
        format_label.setObjectName("label")
        self.format_dropdown = AnimatedDropdown(list(IMAGE_FORMATS))
        format_column.addWidget(format_label)
        format_column.addWidget(self.format_dropdown)
        selectors.addLayout(category_column, 1)
        selectors.addLayout(format_column, 1)
        layout.addLayout(selectors)

        self.format_note = QLabel()
        self.format_note.setObjectName("note")
        self.format_note.setWordWrap(True)
        layout.addWidget(self.format_note)

        save_group = QVBoxLayout()
        save_group.setSpacing(label_gap)
        output_label = QLabel("Save to")
        output_label.setObjectName("label")
        save_group.addWidget(output_label)
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_frame = QFrame()
        path_frame.setObjectName("pathFrame")
        path_frame.setMinimumHeight(38)
        path_layout = QHBoxLayout(path_frame)
        path_layout.setContentsMargins(0, 0, 0, 0)
        self.output_path_label = QLabel(str(self.output_folder))
        self.output_path_label.setObjectName("pathLabel")
        self.output_path_label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.output_path_label.setSizePolicy(
            QSizePolicy.Ignored,
            QSizePolicy.Preferred,
        )
        self.output_path_label.setMinimumWidth(0)
        self.output_path_label.setToolTip(str(self.output_folder))
        path_layout.addWidget(self.output_path_label)
        self.output_browse_button = QPushButton("Browse")
        self.output_browse_button.setFixedWidth(side_button_width)
        self.output_browse_button.clicked.connect(self.choose_output_folder)
        path_row.addWidget(path_frame, 1)
        path_row.addWidget(self.output_browse_button)
        save_group.addLayout(path_row)
        layout.addLayout(save_group)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("primary")
        self.convert_button.clicked.connect(self.start_conversion)
        layout.addWidget(self.convert_button)

        progress_group = QVBoxLayout()
        progress_group.setSpacing(label_gap)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_group.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status")
        progress_group.addWidget(self.status_label)
        layout.addLayout(progress_group)

        log_group = QVBoxLayout()
        log_group.setSpacing(label_gap)
        log_header = QHBoxLayout()
        log_header.setSpacing(6)
        log_label = QLabel("Log")
        log_label.setObjectName("label")
        self.open_folder_button = QPushButton("Open output")
        self.open_folder_button.setObjectName("small")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self.open_output_folder)
        clear_button = QPushButton("Clear")
        clear_button.setObjectName("small")
        clear_button.clicked.connect(self.clear_log)
        log_header.addWidget(log_label)
        log_header.addStretch()
        log_header.addWidget(self.open_folder_button)
        log_header.addWidget(clear_button)
        log_group.addLayout(log_header)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("No activity")
        self.log_box.setMinimumHeight(105)
        log_group.addWidget(self.log_box, 1)
        layout.addLayout(log_group, 1)
        page.addWidget(panel, 1)

    def category_changed(self, category: str):
        selection_cleared = False
        if self.archive_sources and category != "Archives":
            self.archive_sources = []
            self.output_file = None
            selection_cleared = True
        if self.source_file is not None:
            source_category = category_for_extension(
                extension_for_path(self.source_file)
            )
            if source_category != category:
                self.source_file = None
                self.output_file = None
                selection_cleared = True

        if selection_cleared:
            self.file_path_label.setText("Choose a file or drag it here")
            self.file_path_label.setToolTip("")
            self.open_folder_button.setEnabled(False)
            self.append_log("The selection was cleared after changing category.")

        if category == "Images":
            self.file_label.setText("Image file")
            self.format_note.setText(
                "Animation is preserved when the selected output format supports it."
            )
        elif category == "Audio":
            self.file_label.setText("Audio file")
            self.format_note.setText(
                "Supports MP3, WAV, FLAC, OGG, M4A and AAC through FFmpeg."
            )
        elif category == "Video":
            self.file_label.setText("Video file")
            self.format_note.setText(
                "Supports MP4, MKV, WEBM, MOV and AVI. Audio can also be extracted."
            )
        elif category == "Archives":
            self.file_label.setText("Archive, files, or folder")
            self.format_note.setText(
                "Convert an archive or package selected files and folders. GZ requires one file."
            )
        else:
            self.file_label.setText("Script file (.bat, .cmd, .py, or .pyw)")
            self.format_note.setText(
                "BAT/CMD and PY/PYW swaps keep the file contents unchanged."
            )
        self.update_format_options()

    def update_format_options(self):
        category = self.category_dropdown.currentText()
        if category == "Images":
            options = list(IMAGE_FORMATS)
        elif category == "Audio":
            options = list(AUDIO_FORMATS)
        elif category == "Video":
            options = [*VIDEO_FORMATS, *AUDIO_FORMATS]
        elif category == "Archives":
            options = list(ARCHIVE_FORMATS)
        elif self.source_file is None:
            self.format_dropdown.set_items(["Choose a script first"])
            self.format_dropdown.setEnabled(False)
            return
        else:
            options = compatible_script_targets(
                extension_for_path(self.source_file)
            )

        if self.source_file is not None and category != "Scripts":
            current = source_label_for_extension(
                category,
                extension_for_path(self.source_file),
            )
            if current is not None:
                options = [option for option in options if option != current]
        self.format_dropdown.set_items(options)
        self.format_dropdown.setEnabled(bool(options))

    def choose_file(self):
        if self.source_file is not None:
            start_folder = str(self.source_file.parent)
        elif self.archive_sources:
            first = self.archive_sources[0]
            start_folder = str(first if first.is_dir() else first.parent)
        else:
            start_folder = str(Path.home() / "Downloads")
        category = self.category_dropdown.currentText()
        if category == "Archives":
            self.choose_archive_input(start_folder)
            return
        if category == "Images":
            title = "Choose Image"
            file_filter = (
                "Image files (*.png *.jpg *.jpeg *.webp *.bmp *.ico *.gif "
                "*.tiff *.tif *.tga *.avif *.heic *.heif);;"
                "All files (*.*)"
            )
        elif category == "Audio":
            title = "Choose Audio"
            file_filter = (
                "Audio files (*.mp3 *.wav *.flac *.ogg *.m4a *.aac);;"
                "All files (*.*)"
            )
        elif category == "Video":
            title = "Choose Video"
            file_filter = (
                "Video files (*.mp4 *.mkv *.webm *.mov *.avi);;"
                "All files (*.*)"
            )
        else:
            title = "Choose Script"
            file_filter = "Script files (*.bat *.cmd *.py *.pyw);;All files (*.*)"
        filename, _ = QFileDialog.getOpenFileName(
            self,
            title,
            start_folder,
            file_filter,
        )
        if filename:
            self.set_source_file(Path(filename))

    def choose_archive_input(self, start_folder: str):
        choice = QMessageBox(self)
        choice.setWindowTitle("Choose Archive Input")
        choice.setText("Choose files or one folder.")
        files_button = choice.addButton(
            "Files",
            QMessageBox.ButtonRole.AcceptRole,
        )
        folder_button = choice.addButton(
            "Folder",
            QMessageBox.ButtonRole.AcceptRole,
        )
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()

        if choice.clickedButton() is files_button:
            filenames, _ = QFileDialog.getOpenFileNames(
                self,
                "Choose Files",
                start_folder,
                "All files (*.*)",
            )
            if not filenames:
                return
            paths = [Path(filename) for filename in filenames]
            if len(paths) == 1 and extension_for_path(paths[0]) in ARCHIVE_EXTENSIONS:
                self.set_source_file(paths[0])
            else:
                self.set_archive_sources(paths)
        elif choice.clickedButton() is folder_button:
            folder = QFileDialog.getExistingDirectory(
                self,
                "Choose Folder",
                start_folder,
            )
            if folder:
                self.set_archive_sources([Path(folder)])

    def set_source_file(self, path: Path):
        try:
            path = path.expanduser().resolve()
        except OSError as error:
            self.status_label.setText("Invalid file")
            self.append_log(f"Could not read that path: {error}")
            return

        extension = extension_for_path(path)
        if not path.is_file() or extension not in SUPPORTED_EXTENSIONS:
            self.status_label.setText("Choose a supported file")
            self.append_log("Choose a supported file type.")
            return

        category = category_for_extension(extension)
        if category is None:
            self.status_label.setText("Choose a supported file")
            return
        self.category_dropdown.select(category)
        self.archive_sources = []
        self.source_file = path
        self.output_folder = path.parent
        self.output_file = None
        self.file_path_label.setText(str(path))
        self.file_path_label.setToolTip(str(path))
        self.output_path_label.setText(str(self.output_folder))
        self.output_path_label.setToolTip(str(self.output_folder))
        self.open_folder_button.setEnabled(False)
        self.update_format_options()
        self.status_label.setText("Ready")
        self.append_log(f"Selected: {path.name}")

    def set_archive_sources(self, paths):
        selected = []
        names = set()
        try:
            for path in paths:
                path = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
                if is_link_or_junction(path):
                    raise ValueError("Links and junctions cannot be archived.")
                if not path.is_file() and not path.is_dir():
                    raise FileNotFoundError("A selected item no longer exists.")
                resolved = path.resolve()
                name_key = resolved.name.casefold()
                if name_key in names:
                    raise ValueError("Selected items must have unique names.")
                names.add(name_key)
                selected.append(resolved)
        except (OSError, ValueError) as error:
            self.status_label.setText("Invalid selection")
            self.append_log(str(error))
            return

        if not selected:
            return
        self.category_dropdown.select("Archives")
        self.source_file = None
        self.archive_sources = selected
        self.output_file = None
        first = selected[0]
        self.output_folder = first.parent
        if len(selected) == 1:
            display = str(first)
            log_text = f"Selected: {first.name}"
        else:
            display = f"{len(selected)} items selected"
            log_text = f"Selected {len(selected)} items to archive."
        self.file_path_label.setText(display)
        self.file_path_label.setToolTip("\n".join(str(path) for path in selected))
        self.output_path_label.setText(str(self.output_folder))
        self.output_path_label.setToolTip(str(self.output_folder))
        self.open_folder_button.setEnabled(False)
        self.update_format_options()
        self.status_label.setText("Ready")
        self.append_log(log_text)

    def choose_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Folder",
            str(self.output_folder),
        )
        if folder:
            self.output_folder = Path(folder).resolve()
            self.output_path_label.setText(str(self.output_folder))
            self.output_path_label.setToolTip(str(self.output_folder))

    def selected_output_extension(self) -> Optional[str]:
        return output_extension_for_label(self.format_dropdown.currentText())

    def start_conversion(self):
        if self.running:
            self.cancel_conversion()
            return
        archive_sources = (
            tuple(self.archive_sources)
            if self.category_dropdown.currentText() == "Archives"
            else ()
        )
        if archive_sources:
            selection_exists = all(
                path.is_file() or path.is_dir() for path in archive_sources
            )
        else:
            selection_exists = self.source_file is not None and self.source_file.is_file()
        if not selection_exists:
            self.status_label.setText("Choose an input")
            self.append_log("Choose a supported file or folder first.")
            return

        target_label = self.format_dropdown.currentText()
        output_extension = self.selected_output_extension()
        if output_extension is None:
            self.status_label.setText("Choose a format")
            self.append_log("Choose an output format first.")
            return

        if archive_sources:
            if len(archive_sources) == 1:
                selected = archive_sources[0]
                output_base = (
                    selected.name if selected.is_dir() else base_name_for_path(selected)
                )
            else:
                output_base = "archive"
        else:
            output_base = base_name_for_path(self.source_file)
        output_file = self.output_folder / f"{output_base}{output_extension}"
        try:
            output_file = output_file.resolve()
            source_file = self.source_file.resolve() if self.source_file is not None else None
        except OSError as error:
            self.status_label.setText("Invalid output")
            self.append_log(f"Could not resolve the output path: {error}")
            return

        if source_file is not None and output_file == source_file:
            self.status_label.setText("Choose a different format")
            self.append_log("The output cannot overwrite the original file.")
            return

        for selected in archive_sources:
            if selected.is_file() and output_file == selected:
                self.status_label.setText("Choose a different output")
                self.append_log("The output cannot overwrite a selected file.")
                return
            if selected.is_dir():
                try:
                    output_file.relative_to(selected)
                except ValueError:
                    pass
                else:
                    self.status_label.setText("Choose a different output")
                    self.append_log("Save the archive outside the selected folder.")
                    return

        try:
            self.output_folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.status_label.setText("Invalid output")
            self.append_log(f"Could not create the output folder: {error}")
            return

        if output_file.exists():
            choice = QMessageBox.question(
                self,
                "Replace output?",
                f"{output_file.name} already exists. Replace it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if choice != QMessageBox.Yes:
                self.status_label.setText("Cancelled")
                return

        self.output_file = output_file
        self.open_folder_button.setEnabled(False)
        self.log_box.clear()
        self.last_log_message = ""
        if archive_sources:
            self.append_log(
                f"Input: {archive_sources[0]}"
                if len(archive_sources) == 1
                else f"Inputs: {len(archive_sources)} selected items"
            )
        else:
            self.append_log(f"Input: {self.source_file}")
        self.append_log(f"Format: {target_label}")
        self.append_log(f"Output: {output_file}")

        self.worker_thread = QThread(self)
        self.worker = ConversionWorker(
            self.source_file,
            output_file,
            target_label,
            archive_sources,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.thread_finished)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.running = True
        self.convert_button.setText("Cancel")
        self.status_label.setText("Converting...")
        self.progress_bar.setRange(0, 0)
        self.set_controls_enabled(False)
        try:
            self.worker_thread.start()
        except Exception:
            failed_worker = self.worker
            failed_thread = self.worker_thread
            if failed_worker is not None:
                failed_worker.cancel()
            thread_stopped = True
            if failed_thread is not None:
                failed_thread.requestInterruption()
                failed_thread.quit()
                thread_stopped = failed_thread.wait(1000)
            self.output_file = None
            self.open_folder_button.setEnabled(False)
            if not thread_stopped:
                self.convert_button.setText("Stopping...")
                self.convert_button.setEnabled(False)
                self.status_label.setText("Stopping after start failure")
                self.append_log(
                    "The conversion worker reported a start failure after launching. "
                    "Waiting for it to stop safely."
                )
                return
            self.worker = None
            self.worker_thread = None
            self.running = False
            for qt_object in (failed_worker, failed_thread):
                if qt_object is not None:
                    try:
                        delete_qt_object(qt_object)
                    except RuntimeError:
                        pass
            self.convert_button.setText("Convert")
            self.convert_button.setEnabled(True)
            self.set_controls_enabled(True)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.status_label.setText("Conversion could not start")
            self.append_log(
                "The conversion worker could not start. No output was changed."
            )

    def set_controls_enabled(self, enabled: bool):
        self.file_browse_button.setEnabled(enabled)
        self.output_browse_button.setEnabled(enabled)
        self.category_dropdown.setEnabled(enabled)
        self.format_dropdown.setEnabled(
            enabled
            and not (
                self.category_dropdown.currentText() == "Scripts"
                and self.source_file is None
            )
        )
        self.convert_button.setEnabled(True)

    def cancel_conversion(self):
        if not self.running or self.worker is None:
            return
        self.status_label.setText("Stopping...")
        self.convert_button.setEnabled(False)
        self.worker.cancel()

    @Slot(int)
    def update_progress(self, value: int):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)

    @Slot(str, str)
    def conversion_finished(self, state: str, message: str):
        self.progress_bar.setRange(0, 100)
        if state == "success" and self.output_file is not None and self.output_file.is_file():
            self.progress_bar.setValue(100)
            self.status_label.setText("Done")
            self.append_log(message)
            self.append_log("Finished successfully.")
            self.open_folder_button.setEnabled(True)
        elif state == "cancelled":
            self.progress_bar.setValue(0)
            self.status_label.setText("Cancelled")
            self.append_log(message)
        else:
            self.progress_bar.setValue(0)
            self.status_label.setText("Failed")
            self.append_log(message or "The conversion failed.")

    def thread_finished(self):
        self.running = False
        self.worker = None
        self.worker_thread = None
        self.convert_button.setText("Convert")
        self.convert_button.setEnabled(True)
        self.set_controls_enabled(True)

    def clear_log(self):
        self.log_box.clear()
        self.last_log_message = ""
        if not self.running:
            self.status_label.setText("Ready")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def append_log(self, message: str):
        message = str(message).strip()
        if not message or message == self.last_log_message:
            return
        self.last_log_message = message
        self.log_box.append(message)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def open_output_folder(self):
        folder = (
            self.output_file.parent
            if self.output_file is not None
            else self.output_folder
        )
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def dragEnterEvent(self, event: QDragEnterEvent):
        urls = event.mimeData().urls()
        if urls and all(url.isLocalFile() for url in urls):
            paths = [Path(url.toLocalFile()) for url in urls]
            if all(path.is_file() or path.is_dir() for path in paths):
                if (
                    len(paths) > 1
                    or paths[0].is_dir()
                    or self.category_dropdown.currentText() == "Archives"
                    or extension_for_path(paths[0]) in SUPPORTED_EXTENSIONS
                ):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
            current_category = self.category_dropdown.currentText()
            if (
                len(paths) == 1
                and paths[0].is_file()
                and extension_for_path(paths[0]) in ARCHIVE_EXTENSIONS
            ):
                self.set_source_file(paths[0])
            elif (
                len(paths) > 1
                or (paths and paths[0].is_dir())
                or current_category == "Archives"
                or (
                    paths
                    and extension_for_path(paths[0]) not in SUPPORTED_EXTENSIONS
                )
            ):
                self.set_archive_sources(paths)
            elif paths:
                self.set_source_file(paths[0])
            event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent):
        if self.running:
            QMessageBox.information(
                self,
                "Conversion in progress",
                "Wait for the current conversion to finish before closing the app.",
            )
            event.ignore()
            return
        self.category_dropdown.hide_popup()
        self.format_dropdown.hide_popup()
        event.accept()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        raise SystemExit(run_self_test(Path(sys.argv[2]).resolve()))

    if os.name != "nt":
        show_native_setup_error("File Converter supports 64-bit Windows only.")
        raise SystemExit(1)
    if not acquire_app_mutex():
        show_native_setup_error("File Converter is already open.")
        raise SystemExit(1)
    if SETUP_LOCK_DIR.is_dir():
        show_native_setup_error(
            "File Converter setup is currently running.\n\n"
            "Let Installer.bat finish, then open the app again."
        )
        raise SystemExit(1)

    sys.excepthook = handle_unhandled_exception
    threading.excepthook = handle_unhandled_thread_exception
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("Fleece")
    app.setStyle("Fusion")
    window = FileConverter()
    window.show()
    raise SystemExit(app.exec())
