"""Run a benign image conversion through the exact released app backend."""

from __future__ import annotations

import hashlib
import runpy
import sys
import tempfile
from pathlib import Path

from PIL import Image


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: Test-RealConversion.py RELEASE_ROOT")
    root = Path(sys.argv[1]).resolve(strict=True)
    namespace = runpy.run_path(str(root / "File Converter.pyw"), run_name="fleece_release_workflow")
    with tempfile.TemporaryDirectory(prefix="real-smoke-", dir=root / ".runtime") as directory:
        folder = Path(directory)
        source = folder / "source.png"
        output = folder / "output.jpg"
        Image.new("RGB", (17, 13), (32, 96, 160)).save(source, format="PNG")
        source_hash = hashlib.sha256(source.read_bytes()).digest()
        message = namespace["convert_file"](source, output, "JPG image (.jpg)")
        if not output.is_file() or output.stat().st_size < 1:
            raise AssertionError("The released app produced no JPEG.")
        with Image.open(output) as converted:
            if converted.format != "JPEG" or converted.size != (17, 13):
                raise AssertionError("The released app produced an invalid JPEG.")
            converted.verify()
        if hashlib.sha256(source.read_bytes()).digest() != source_hash:
            raise AssertionError("The released app changed the source image.")
        print(f"Real image conversion passed: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
