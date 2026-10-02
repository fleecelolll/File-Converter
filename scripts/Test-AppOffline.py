r"""Offline backend/UI regression tests; all outputs use a disposable TEMP tree.

Run with .runtime\python\python.exe -I scripts\Test-AppOffline.py
An optional --report PATH saves JSON evidence. No installers or network are used.
"""
import argparse
import io
import json
import linecache
import os
import runpy
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP = Path(__file__).resolve().parents[1] / "File Converter.pyw"
API = runpy.run_path(str(APP), run_name="offline_audit")
if "--baseline" in sys.argv:
    baseline = subprocess.run(["git", "-C", str(APP.parent), "show", "HEAD:" + APP.name], capture_output=True, check=True, timeout=15)
    API = {"__file__": str(APP), "__name__": "offline_audit_baseline"}
    baseline_filename = str(APP) + " (Git HEAD baseline)"
    linecache.cache[baseline_filename] = (len(baseline.stdout), None, baseline.stdout.decode("utf-8").splitlines(keepends=True), baseline_filename)
    exec(compile(baseline.stdout, baseline_filename, "exec"), API)
GLOBALS = API["convert_file"].__globals__
APPLICATION = API["QApplication"].instance() or API["QApplication"]([])
MEASUREMENTS = []


class OfflineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fleece-converter-offline-")
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.original_runtime = GLOBALS["RUNTIME_DIR"]
        self.original_work = GLOBALS["ARCHIVE_WORK_ROOT"]
        GLOBALS["RUNTIME_DIR"] = self.runtime
        GLOBALS["ARCHIVE_WORK_ROOT"] = self.runtime / "work"
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.running = False
            self.window.close()
            APPLICATION.processEvents()
        GLOBALS["RUNTIME_DIR"] = self.original_runtime
        GLOBALS["ARCHIVE_WORK_ROOT"] = self.original_work
        self.temp.cleanup()

    def window_and_source(self):
        self.window = API["FileConverter"]()
        source = self.root / "source.py"
        source.write_bytes(b"print('synthetic')\n")
        self.window.set_source_file(source)
        return source

    def test_invalid_replacement_clears_stale_source(self):
        self.window_and_source()
        self.window.set_source_file(self.root / "missing.png")
        self.assertIsNone(self.window.source_file)
        self.assertEqual(self.window.archive_sources, [])
        self.assertIsNone(self.window.output_file)

    def test_running_job_cannot_change_selection(self):
        source = self.window_and_source()
        self.window.running = True
        other = self.root / "other.py"
        other.write_bytes(b"return\n")
        self.window.set_source_file(other)
        self.window.set_archive_sources([other])
        self.assertEqual(self.window.source_file, source)
        self.assertEqual(self.window.archive_sources, [])

    def test_log_is_literal_and_bounded(self):
        self.window_and_source()
        self.window.clear_log()
        self.window.append_log("<b>literal</b>")
        self.assertEqual(self.window.log_box.toPlainText(), "<b>literal</b>")
        self.window.append_log("x" * 100000)
        self.assertLessEqual(len(self.window.last_log_message), 12000)
        for index in range(350):
            self.window.append_log(f"bounded {index}")
        self.assertLessEqual(self.window.log_box.document().blockCount(), 300)

    def test_cancel_tolerates_process_race(self):
        worker = API["ConversionWorker"](None, self.root / "out.zip", "ZIP archive (.zip)")
        class ExitedProcess:
            def poll(self):
                return None
            def kill(self):
                raise OSError("synthetic process exited concurrently")
        worker.set_process(ExitedProcess())
        worker.cancel()
        self.assertTrue(worker.cancel_event.is_set())

    def test_script_roundtrip_cancel_and_atomic_failure(self):
        source = self.root / "source.py"
        source.write_bytes(b"# synthetic\r\nprint('ok')\n\x00")
        output = self.root / "output.pyw"
        API["convert_file"](source, output, "Python window script (.pyw)")
        self.assertEqual(output.read_bytes(), source.read_bytes())
        output.write_bytes(b"existing-output")
        event = threading.Event()
        event.set()
        with self.assertRaises(API["ConversionCancelled"]):
            API["convert_file"](source, output, "Python window script (.pyw)", event)
        self.assertEqual(output.read_bytes(), b"existing-output")
        with patch.object(GLOBALS["os"], "replace", side_effect=OSError("synthetic full disk")):
            with self.assertRaises(OSError):
                API["convert_file"](source, output, "Python window script (.pyw)")
        self.assertEqual(output.read_bytes(), b"existing-output")
        self.assertEqual(list(self.root.glob(".*")), [])

    def test_invalid_image_preserves_output_and_source(self):
        source = self.root / "invalid.png"
        source.write_bytes(b"not an image")
        output = self.root / "existing.jpg"
        output.write_bytes(b"existing")
        with self.assertRaises(ValueError):
            API["convert_file"](source, output, "JPG image (.jpg)")
        self.assertEqual(source.read_bytes(), b"not an image")
        self.assertEqual(output.read_bytes(), b"existing")
        self.assertEqual(list(self.root.glob(".*")), [])

    def test_archive_unsafe_names_links_and_bombs(self):
        for index, name in enumerate(("../escape", "/absolute", "C:/escape", "AUX.txt", "name. ", "data:stream")):
            source = self.root / f"unsafe-{index}.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(name, b"synthetic")
            output = self.root / f"unsafe-{index}.tar"
            with self.assertRaises(ValueError):
                API["convert_file"](source, output, "TAR archive (.tar)")
            self.assertFalse(output.exists())
        source = self.root / "link.zip"
        with zipfile.ZipFile(source, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../escape")
        with self.assertRaises(ValueError):
            API["convert_file"](source, self.root / "link.tar", "TAR archive (.tar)")
        source = self.root / "bomb.zip"
        with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("data", b"x" * 4096)
        original = GLOBALS["MAX_ARCHIVE_EXPANDED_BYTES"]
        GLOBALS["MAX_ARCHIVE_EXPANDED_BYTES"] = 1024
        try:
            with self.assertRaises(ValueError):
                API["convert_file"](source, self.root / "bomb.tar", "TAR archive (.tar)")
        finally:
            GLOBALS["MAX_ARCHIVE_EXPANDED_BYTES"] = original
        self.assertEqual(list((self.runtime / "work").iterdir()), [])

    def test_archive_contents_empty_directories_and_cancel(self):
        source = self.root / "contents.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("empty/", b"")
            archive.writestr("nested/data.txt", b"contents")
        tar = self.root / "output.tar"
        output = self.root / "roundtrip.zip"
        API["convert_file"](source, tar, "TAR archive (.tar)")
        API["convert_file"](tar, output, "ZIP archive (.zip)")
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.read("nested/data.txt"), b"contents")
            self.assertIn("empty/", archive.namelist())
        event = threading.Event()
        event.set()
        with self.assertRaises(API["ConversionCancelled"]):
            API["convert_file"](source, tar, "TAR archive (.tar)", event)
        self.assertEqual(list((self.runtime / "work").iterdir()), [])

    def test_same_source_and_nested_archive_output_rejected(self):
        source = self.root / "source.py"
        source.write_bytes(b"print('synthetic')")
        with self.assertRaises(ValueError):
            API["convert_file"](source, source, "Python script (.py)")
        with self.assertRaises(ValueError):
            API["create_archive_from_sources"]([self.root], self.root / "inside.zip", "ZIP archive (.zip)")
        self.assertEqual(source.read_bytes(), b"print('synthetic')")

    def test_representative_worker_responsiveness_and_cleanup(self):
        from PySide6.QtCore import QTimer
        import psutil
        self.window = API["FileConverter"]()
        API["load_image_backend"]()
        image_source = self.root / "large.png"
        GLOBALS["Image"].new("RGB", (2048, 2048), (23, 45, 67)).save(image_source)
        cases = [(image_source, "WEBP image (.webp)")]
        archive_source = self.root / "data.zip"
        with zipfile.ZipFile(archive_source, "w", zipfile.ZIP_DEFLATED) as archive:
            for index in range(64):
                archive.writestr(f"data/{index}.bin", bytes(range(256)) * 1024)
        cases.append((archive_source, "TAR archive (.tar)"))
        for source, label in cases:
            self.window.set_source_file(source)
            self.window.format_dropdown.select(label)
            self.window.output_folder = self.root / "outputs"
            ticks = []
            memory = []
            process = psutil.Process()
            timer = QTimer()
            timer.setInterval(10)
            timer.timeout.connect(lambda: (ticks.append(time.perf_counter()), memory.append(process.memory_info().rss)))
            start = time.perf_counter()
            baseline_rss = process.memory_info().rss
            timer.start()
            self.window.start_conversion()
            while self.window.running and time.perf_counter() - start < 30:
                APPLICATION.processEvents()
                time.sleep(0.001)
            timer.stop()
            elapsed = time.perf_counter() - start
            self.assertFalse(self.window.running, "bounded job did not finish")
            self.assertEqual(self.window.status_label.text(), "Done")
            self.assertIsNone(self.window.worker_thread)
            self.assertIsNone(self.window.worker)
            gaps = [b - a for a, b in zip([start] + ticks, ticks + [time.perf_counter()])]
            MEASUREMENTS.append({"case": label, "seconds": round(elapsed, 4), "timer_ticks": len(ticks), "max_event_gap_ms": round(max(gaps) * 1000, 3), "baseline_rss_bytes": baseline_rss, "sampled_peak_rss_bytes": max(memory or [baseline_rss])})
            self.assertGreater(len(ticks), 0)
            self.assertLess(max(gaps), 2.0)

    def test_actual_worker_cancel_cleans_thread_and_preserves_output(self):
        from PySide6.QtCore import QTimer
        source = self.window_and_source()
        self.window.output_folder = self.root / "outputs"
        original = GLOBALS["convert_file"]
        def synthetic_wait(source, output, label, cancel_event, *unused):
            deadline = time.perf_counter() + 2
            while time.perf_counter() < deadline:
                API["check_cancel"](cancel_event)
                time.sleep(0.002)
            raise RuntimeError("synthetic cancellation did not arrive")
        GLOBALS["convert_file"] = synthetic_wait
        try:
            self.window.start_conversion()
            QTimer.singleShot(10, self.window.cancel_conversion)
            deadline = time.perf_counter() + 3
            while self.window.running and time.perf_counter() < deadline:
                APPLICATION.processEvents()
                time.sleep(0.001)
        finally:
            GLOBALS["convert_file"] = original
        self.assertFalse(self.window.running)
        self.assertEqual(self.window.status_label.text(), "Cancelled")
        self.assertIsNone(self.window.worker_thread)
        self.assertIsNone(self.window.worker)
        self.assertFalse(self.window.output_file.exists())
        self.assertEqual(source.read_bytes(), b"print('synthetic')\n")

    def test_images_alpha_exif_orientation_and_frame_limits(self):
        API["load_image_backend"]()
        image_backend = GLOBALS["Image"]
        source = self.root / "alpha.png"
        image_backend.new("RGBA", (2, 2), (255, 0, 0, 0)).save(source)
        jpeg = self.root / "alpha.jpg"
        API["convert_file"](source, jpeg, "JPG image (.jpg)")
        with image_backend.open(jpeg) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        exif = image_backend.Exif()
        exif[274] = 6
        oriented = self.root / "oriented.jpg"
        image_backend.new("RGB", (8, 4), (10, 20, 30)).save(oriented, exif=exif)
        png = self.root / "oriented.png"
        API["convert_file"](oriented, png, "PNG image (.png)")
        with image_backend.open(png) as image:
            self.assertEqual(image.size, (4, 8))
            self.assertNotIn(274, image.getexif())
        frames = [image_backend.new("RGB", (8, 8), color) for color in ("red", "blue")]
        animated = self.root / "animated.gif"
        frames[0].save(animated, save_all=True, append_images=frames[1:], duration=[70, 130], loop=3)
        apng = self.root / "animated.png"
        API["convert_file"](animated, apng, "PNG image (.png)")
        with image_backend.open(apng) as image:
            self.assertEqual(image.n_frames, 2)
            self.assertEqual(image.info.get("loop"), 3)
            self.assertEqual(image.info.get("duration"), 70)
            image.seek(1)
            self.assertEqual(image.info.get("duration"), 130)
        original = GLOBALS["MAX_IMAGE_FRAMES"]
        GLOBALS["MAX_IMAGE_FRAMES"] = 1
        try:
            with self.assertRaises(ValueError):
                API["convert_file"](animated, self.root / "limited.png", "PNG image (.png)")
        finally:
            GLOBALS["MAX_IMAGE_FRAMES"] = original

    def test_invalid_media_and_stream_copy_decisions(self):
        source = self.root / "bad.wav"
        source.write_bytes(b"invalid synthetic media")
        output = self.root / "existing.mp3"
        output.write_bytes(b"existing")
        with self.assertRaises(RuntimeError):
            API["convert_file"](source, output, "MP3 audio (.mp3)")
        self.assertEqual(output.read_bytes(), b"existing")
        copy = API["stream_copy_arguments"]
        audio = {"streams": [{"codec_type": "audio", "codec_name": "aac"}]}
        self.assertIn("copy", copy("M4A audio (.m4a)", audio))
        self.assertIsNone(copy("MP3 audio (.mp3)", audio))
        self.assertIsNone(copy("WEBM video (.webm)", {"streams": [{"codec_type": "video", "codec_name": "h264"}]}))

    def test_precancelled_invalid_media_reports_cancel(self):
        source = self.root / "bad.wav"
        source.write_bytes(b"invalid synthetic media")
        event = threading.Event()
        event.set()
        with self.assertRaises(API["ConversionCancelled"]):
            API["convert_file"](source, self.root / "out.mp3", "MP3 audio (.mp3)", event)

    def test_media_probe_can_be_cancelled_and_child_is_reaped(self):
        source = self.root / "source.wav"
        source.write_bytes(b"synthetic media fixture")
        event = threading.Event()
        children = []
        original_popen = subprocess.Popen
        def synthetic_probe_child(*unused, **kwargs):
            child = original_popen([sys.executable, "-I", "-c", "import time; time.sleep(10)"], **kwargs)
            children.append(child)
            return child
        timer = threading.Timer(0.05, event.set)
        start = time.perf_counter()
        timer.start()
        try:
            with patch.object(API["subprocess"], "Popen", side_effect=synthetic_probe_child):
                with self.assertRaises(API["ConversionCancelled"]):
                    API["convert_file"](source, self.root / "out.mp3", "MP3 audio (.mp3)", event)
        finally:
            timer.cancel()
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=5)
        self.assertLess(time.perf_counter() - start, 1.0)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", action="store_true", help="maintainer-only comparison against local Git HEAD")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(OfflineTests)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "seconds": round(time.perf_counter() - start, 4), "measurements": MEASUREMENTS, "failure_details": [text for _, text in result.failures + result.errors]}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
