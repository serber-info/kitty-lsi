"""Acceptance tests through the installed command interface (no internal mocks)."""

import os
import base64
import io
import errno
import fcntl
import pty
import re
import select
import struct
import termios
import time
import zlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("LSI_BINARY", ROOT / "rust/target/debug/lsi")).resolve()


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "small.txt").write_bytes(b"x" * 1536)

    def command(self, *args):
        return subprocess.run(
            [str(BINARY), *args], cwd=self.root,
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        )

    def terminal_command(self, *args, columns=80, rows=24):
        """Actual PTY at the OS seam, not a mock of the renderer."""
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 800, 480))
        env = {**os.environ, "TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"}
        env.pop("TMUX", None)
        env.pop("STY", None)
        process = subprocess.Popen([str(BINARY), *args],
                                   cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                                   stdout=slave, stderr=subprocess.PIPE)
        os.close(slave)
        chunks = []
        deadline = time.monotonic() + 10
        try:
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
                    chunks.append(chunk)
            else:
                self.fail("terminal command did not finish")
            errors = process.communicate(timeout=2)[1].decode()
            output = b"".join(chunks).decode()
            plain = re.sub(r"\x1b_G.*?\x1b\\", "", output, flags=re.S)
            plain = re.sub(r"\x1b\[[0-9;]*m", "", plain)
            plain = re.sub("\U0010eeee[\u0300-\u036f]*", "▧", plain)
            return process.returncode, output, plain, errors
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_long_human_readable_listing(self):
        (self.root / "small.txt").chmod(0o640)
        result = self.command("-lh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^-rw-r-----\s+1\s+\S+\s+\S+\s+1\.5K\s+")
        self.assertTrue(result.stdout.rstrip().endswith("small.txt"))
        self.assertNotIn("\x1b", result.stdout)

    def test_sorting_matches_requested_order(self):
        (self.root / "large.png").write_bytes(b"x" * 3000)
        (self.root / "item2.jpg").touch()
        (self.root / "item10.jpg").touch()
        os.utime(self.root / "item2.jpg", (1, 1))
        cases = [
            (["-S"], ["large.png", "small.txt", "item10.jpg", "item2.jpg"]),
            (["-Sr"], ["item2.jpg", "item10.jpg", "small.txt", "large.png"]),
            (["-v"], ["item2.jpg", "item10.jpg", "large.png", "small.txt"]),
            (["-X"], ["item10.jpg", "item2.jpg", "large.png", "small.txt"]),
        ]
        for flags, expected in cases:
            with self.subTest(flags=flags):
                result = self.command(*flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(self.command("-t").stdout.splitlines()[-1], "item2.jpg")

    def test_hidden_files_and_directory_traversal(self):
        (self.root / ".secret.png").touch()
        (self.root / "folder").mkdir()
        (self.root / "folder" / "nested.txt").touch()
        self.assertNotIn(".secret.png", self.command().stdout)
        almost = self.command("-A")
        self.assertEqual(almost.returncode, 0, almost.stderr)
        self.assertEqual(almost.stdout.splitlines(), [".secret.png", "folder", "small.txt"])
        self.assertEqual(self.command("-a").stdout.splitlines()[:2], [".", ".."])
        self.assertEqual(self.command("-d", "folder").stdout, "folder\n")
        recursive = self.command("-Ra")
        self.assertEqual(recursive.returncode, 0, recursive.stderr)
        self.assertEqual(recursive.stdout.count("nested.txt"), 1)
        self.assertIn("folder:", recursive.stdout)

    def test_metadata_and_file_type_options(self):
        (self.root / "folder").mkdir()
        (self.root / "link").symlink_to("small.txt")
        (self.root / "run").touch(mode=0o755)
        result = self.command("-F", "--group-directories-first")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["folder/", "link@", "run*", "small.txt"])
        self.assertEqual(self.command("-p", "-d", "folder").stdout, "folder/\n")
        numeric = self.command("-ni", "small.txt")
        info = (self.root / "small.txt").stat()
        self.assertRegex(numeric.stdout, rf"^{info.st_ino}\s+-rw-r--r--\s+1\s+{info.st_uid}\s+{info.st_gid}\s+1536\s+")
        self.assertIn("1.5k", self.command("-l", "--si", "small.txt").stdout)
        self.assertIn("link -> small.txt", self.command("-l", "link").stdout)
        self.assertRegex(self.command("-l", "--full-time", "small.txt").stdout,
                         r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+0000")

    def test_grid_and_long_mode_in_a_real_pty(self):
        for name, color in [("alpha.png", "red"), ("beta.png", "blue")]:
            Image.new("RGB", (40, 20), color).save(self.root / name)
        code, raw, plain, errors = self.terminal_command("alpha.png", "beta.png")
        self.assertEqual(code, 0, errors)
        self.assertIn("U=1", raw)
        self.assertTrue(any("alpha.png" in line and "beta.png" in line for line in plain.splitlines()), plain)
        code, raw, plain, errors = self.terminal_command("-lh", "alpha.png", "beta.png")
        self.assertEqual(code, 0, errors)
        self.assertIn("-rw-", plain)
        self.assertFalse(any("alpha.png" in line and "beta.png" in line for line in plain.splitlines()))









    def test_empty_missing_and_multiple_operands(self):
        (self.root / "empty").mkdir()
        self.assertEqual(self.command("empty").stdout, "")
        result = self.command("missing", "small.txt")
        self.assertEqual(result.returncode, 1)
        self.assertIn("small.txt", result.stdout)
        self.assertIn("missing", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_flags_and_invalid_geometry_fail_cleanly(self):
        for flags in [("--not-real",), ("--width", "0"), ("--height", "17"), ("--width", "bad")]:
            with self.subTest(flags=flags):
                result = self.command(*flags)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)

    def test_help_and_version(self):
        self.assertIn("--human-readable", self.command("--help").stdout)
        self.assertEqual(self.command("--version").stdout, "kitty-lsi 0.1.0\n")

    def test_no_images_and_redirected_output_do_not_decode_corrupt_files(self):
        (self.root / "bad.png").write_bytes(b"bad PNG")
        piped = self.command()
        self.assertEqual(piped.returncode, 0, piped.stderr)
        self.assertNotIn("\x1b", piped.stdout)
        code, raw, plain, errors = self.terminal_command("--no-images")
        self.assertEqual(code, 0, errors)
        self.assertNotIn("\x1b", raw)
        self.assertIn("bad.png", plain)

    def test_corrupt_preview_keeps_other_files_and_returns_error(self):
        (self.root / "bad.png").write_bytes(b"bad PNG")
        Image.new("RGB", (10, 10), "red").save(self.root / "good.png")
        code, raw, plain, errors = self.terminal_command()
        self.assertEqual(code, 1)
        self.assertIn("good.png", plain)
        self.assertIn("bad.png", plain)
        self.assertIn("[unreadable]", plain)
        self.assertIn("bad.png", errors)
        self.assertNotIn("Traceback", errors)

    def test_links_and_fifos_are_not_opened_or_followed(self):
        (self.root / "link.png").symlink_to("missing.png")
        os.mkfifo(self.root / "pipe.png")
        (self.root / "loop").symlink_to(".", target_is_directory=True)
        code, raw, plain, errors = self.terminal_command("-RF")
        self.assertEqual(code, 0, errors)
        self.assertIn("link.png@", plain)
        self.assertIn("pipe.png|", plain)
        self.assertNotIn("\x1b_G", raw)

    def test_filename_cannot_inject_terminal_commands(self):
        name = "evil\x1b]52;c;test\x07\n\u202e.png"
        (self.root / name).write_bytes(b"invalid")
        result = self.command()
        for char in ("\x1b", "\x07", "\u202e"):
            self.assertNotIn(char, result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        code, raw, plain, errors = self.terminal_command()
        self.assertEqual(code, 1)
        self.assertNotIn("\x1b]52", raw + errors)

    def test_unicode_names_fit_grid_and_narrow_terminal_falls_back(self):
        Image.new("RGB", (40, 20)).save(self.root / "照片.png")
        code, raw, plain, errors = self.terminal_command("照片.png", columns=40)
        self.assertEqual(code, 0, errors)
        self.assertIn("照片.png", plain)
        code, raw, plain, errors = self.terminal_command("照片.png", columns=12)
        self.assertEqual(code, 0, errors)
        self.assertNotIn("\x1b_G", raw)
        self.assertIn("照片.png", plain)

    def test_one_column_preserves_previews(self):
        for name in ("alpha.png", "beta.png"):
            Image.new("RGB", (10, 10)).save(self.root / name)
        code, raw, plain, errors = self.terminal_command("-1", "alpha.png", "beta.png")
        self.assertEqual(code, 0, errors)
        self.assertEqual(raw.count("a=T,f=100"), 2)
        self.assertFalse(any("alpha.png" in line and "beta.png" in line for line in plain.splitlines()))

    def test_preview_png_is_bounded_and_exif_oriented(self):
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (640, 320), "red").save(self.root / "rotated.jpg", exif=exif)
        code, raw, plain, errors = self.terminal_command("-1", "rotated.jpg")
        self.assertEqual(code, 0, errors)
        self.assertIn("320 × 640", plain)
        chunks = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)
        with Image.open(io.BytesIO(base64.b64decode("".join(chunks)))) as image:
            self.assertEqual(image.format, "PNG")
            self.assertLess(image.width, image.height)
            self.assertLessEqual(max(image.size), 224)

    def test_gif_preview_is_first_frame(self):
        first = Image.new("RGB", (10, 10), "red")
        first.save(self.root / "animated.gif", save_all=True,
                   append_images=[Image.new("RGB", (10, 10), "blue")])
        code, raw, plain, errors = self.terminal_command("animated.gif")
        self.assertEqual(code, 0, errors)
        chunks = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)
        with Image.open(io.BytesIO(base64.b64decode("".join(chunks)))) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_no_owner_and_no_group(self):
        for flag in ("-g", "-o"):
            result = self.command(flag, "small.txt")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.split()), 8)

    def test_unsorted_mode_keeps_all_entries(self):
        (self.root / "z").touch()
        (self.root / "a").touch()
        result = self.command("-U")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(set(result.stdout.splitlines()), {"small.txt", "z", "a"})

    def test_oversized_images_are_rejected_before_decode(self):
        with (self.root / "large.png").open("wb") as file:
            file.seek(64 * 1024 * 1024)
            file.write(b"x")
        code, raw, plain, errors = self.terminal_command("large.png")
        self.assertEqual(code, 1)
        self.assertIn("64 MiB", errors)
        # A minimal PNG header can declare huge dimensions without a large file.
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
        ihdr = struct.pack(">IIBBBBB", 8000, 6000, 8, 2, 0, 0, 0)
        (self.root / "pixels.png").write_bytes(
            b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", b"") + chunk(b"IEND", b""))
        code, raw, plain, errors = self.terminal_command("pixels.png")
        self.assertEqual(code, 1)
        self.assertIn("40 megapixels", errors)
