"""Developer-only test: execute the release inside an otherwise empty filesystem.

bwrap and Python/Pillow belong to this test harness, NOT to the application.
Only the binary, generated pictures, /proc and /dev are mounted inside.
"""
import argparse
import base64
import errno
import fcntl
import io
import os
from pathlib import Path
import pty
import re
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time
from PIL import Image


def capture(command):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.PIPE)
    os.close(slave)
    data = bytearray()
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    break
                if not chunk:
                    break
                data.extend(chunk)
        else:
            raise RuntimeError("standalone command timed out")
        errors = process.communicate(timeout=2)[1].decode()
        if process.returncode:
            raise RuntimeError(errors)
        return bytes(data)
    finally:
        os.close(master)
        if process.poll() is None:
            process.kill()
        process.communicate()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    bwrap = shutil.which("bwrap")
    if not bwrap:
        parser.error("bwrap is required for this developer test")
    with tempfile.TemporaryDirectory(prefix="kitty-lsi-isolation-") as directory:
        root = Path(directory)
        formats = [("png", "PNG"), ("jpg", "JPEG"), ("gif", "GIF"), ("webp", "WEBP"),
                   ("bmp", "BMP"), ("tiff", "TIFF"), ("ico", "ICO"), ("avif", "AVIF")]
        for extension, codec in formats:
            Image.new("RGB", (64, 64), "red").save(root / ("sample."+extension), format=codec)
        command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                   "--ro-bind", str(binary), "/lsi", "--symlink", "/lsi", "/lli",
                   "--ro-bind", str(root), "/images", "--proc", "/proc", "--dev", "/dev",
                   "--tmpfs", "/tmp", "--clearenv", "--setenv", "PATH", "/no-programs",
                   "--setenv", "TERM", "xterm-kitty", "--setenv", "TZ", "UTC",
                   "--chdir", "/images"]
        for extension, codec in formats:
            output = capture([*command, "/lsi", "-1", "sample."+extension])
            chunks = re.findall(rb"\x1b_G[^;]*;([^\x1b]*)\x1b\\", output)
            if not chunks:
                raise RuntimeError(f"{codec}: no graphics transmission")
            with Image.open(io.BytesIO(base64.b64decode(b"".join(chunks)))) as preview:
                assert preview.format == "PNG"
                assert preview.size == (64, 64)
                assert preview.convert("RGB").getpixel((32, 32))[0] > 200
            print(f"PASS isolated decode + Kitty transmission: {codec}")
        plain = subprocess.run([*command, "/lli", "-h"], capture_output=True, text=True, timeout=10)
        if plain.returncode or "sample.png" not in plain.stdout or "-rw-" not in plain.stdout:
            raise RuntimeError(plain.stderr or plain.stdout)
        print("PASS lli alias and metadata without /etc/passwd or /etc/group (numeric fallback)")
        print("PASS: no /usr, /bin, /lib, Python, Cargo, icat or external codec tools mounted")


if __name__ == "__main__":
    main()
