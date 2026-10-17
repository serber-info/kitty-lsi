"""Cache behavior through real CLI invocations and terminal output."""
import base64
import io
import os
from pathlib import Path
import re
import tempfile
import struct
import unittest

from PIL import Image
from test_steps import Session


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / ".cache"
        self.base.mkdir(mode=0o700)
        self.image = self.root / "photo.jpg"
        Image.new("RGB", (1200, 800), "red").save(self.image)

    def run_image(self, *args):
        session = Session(self.root, (*args, "photo.jpg"), env_extra={
            "XDG_CACHE_HOME": str(self.base), "LSI_TEST_CACHE_DIR": str(self.base)})
        self.addCleanup(session.close)
        code, errors = session.finish()
        self.assertEqual(code, 0, errors)
        self.last_plain = session.plain()
        chunks = re.findall(rb"\x1b_G[^;]*;([^\x1b]*)\x1b\\", session.raw)
        self.assertTrue(chunks)
        return base64.b64decode(b"".join(chunks))

    def entries(self):
        return sorted((self.base / "kitty-lsi").glob("*.thumb"))

    def test_cache_is_private_enabled_by_default_and_reused(self):
        first = self.run_image()
        entries = self.entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual((self.base / "kitty-lsi").stat().st_mode & 0o777, 0o700)
        self.assertEqual(entries[0].stat().st_mode & 0o777, 0o600)
        old = entries[0].stat().st_mtime_ns
        self.assertEqual(self.run_image(), first)
        self.assertEqual(entries[0].stat().st_mtime_ns, old)

    def test_no_cache_bypasses_both_reads_and_writes(self):
        self.run_image("--no-cache")
        self.assertFalse((self.base / "kitty-lsi").exists())
        self.run_image()
        entry = self.entries()[0]
        # A valid alternate cached thumbnail proves the hit path is actually used.
        blue = io.BytesIO()
        Image.new("RGBA", (8, 8), "blue").save(blue, format="PNG")
        cached = entry.read_bytes()[:16] + blue.getvalue()
        entry.write_bytes(cached)
        with Image.open(io.BytesIO(self.run_image())) as image:
            self.assertEqual(image.getpixel((0, 0)), (0, 0, 255, 255))
        with Image.open(io.BytesIO(self.run_image("--no-cache"))) as image:
            self.assertGreater(image.getpixel((0, 0))[0], 200)
        self.assertEqual(entry.read_bytes(), cached)

    def test_source_changes_and_geometry_invalidate_without_losing_original_dimensions(self):
        self.run_image("-1")
        self.assertIn("1200 × 800", self.last_plain)
        self.run_image("-1")
        self.assertIn("1200 × 800", self.last_plain)
        self.assertEqual(len(self.entries()), 1)
        self.run_image("--width", "20")
        self.assertEqual(len(self.entries()), 2)
        Image.new("RGB", (1200, 800), "blue").save(self.image)
        with Image.open(io.BytesIO(self.run_image())) as image:
            self.assertGreater(image.getpixel((0, 0))[2], 200)
        self.assertEqual(len(self.entries()), 3)

    def test_corrupt_and_excessive_cached_headers_recover(self):
        self.run_image()
        entry = self.entries()[0]
        valid = entry.read_bytes()
        variants = [b"", b"not a cache", valid[:16],
                    valid[:32] + struct.pack(">I", 2**31) + valid[36:],
                    valid[:8] + b"\xff" * 8 + valid[16:],
                    valid[:-12]]  # Missing PNG IEND: rejected in the worker.
        for data in variants:
            with self.subTest(size=len(data)):
                entry.write_bytes(data)
                self.run_image()
                self.assertEqual(entry.read_bytes()[:8], b"LSIC0001")
                self.assertGreater(entry.stat().st_size, 40)

    def test_cache_symlinks_and_fifos_are_not_followed_or_overwritten(self):
        self.run_image()
        entry = self.entries()[0]
        sentinel = self.base / "sentinel"
        sentinel.write_bytes(b"do not change")
        entry.unlink()
        entry.symlink_to(sentinel)
        self.run_image()
        self.assertTrue(entry.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b"do not change")
        entry.unlink()
        os.mkfifo(entry, mode=0o600)
        self.run_image()
        import stat
        self.assertTrue(stat.S_ISFIFO(entry.lstat().st_mode))

    def test_unsafe_cache_directory_falls_back_without_changing_it(self):
        target = self.base / "target"
        target.mkdir(mode=0o700)
        cache = self.base / "kitty-lsi"
        cache.symlink_to("target", target_is_directory=True)
        self.run_image()
        self.assertEqual(list(target.iterdir()), [])
        self.assertTrue(cache.is_symlink())
        cache.unlink()
        cache.mkdir(mode=0o777)
        cache.chmod(0o777)
        self.run_image()
        self.assertEqual(list(cache.iterdir()), [])
        self.assertEqual(cache.stat().st_mode & 0o777, 0o777)

    def test_cache_eviction_limits_bytes_and_preserves_unrelated_files(self):
        self.run_image()
        cache = self.base / "kitty-lsi"
        header = self.entries()[0].read_bytes()[:16]
        sentinel = cache / "keep-me.txt"
        sentinel.write_bytes(b"unrelated")
        for index in range(33):
            path = cache / f"v1-{index:08x}.thumb"
            with path.open("xb") as file:
                file.write(header)
                file.truncate(8 * 1024 * 1024)  # Sparse: no 264 MiB allocation.
            path.chmod(0o600)
            os.utime(path, (1, 1))
        self.run_image()
        self.assertLessEqual(sum(p.stat().st_size for p in self.entries()), 256 * 1024 * 1024)
        self.assertEqual(sentinel.read_bytes(), b"unrelated")

    def test_invalid_managed_files_cannot_bypass_the_cache_budget(self):
        cache = self.base / "kitty-lsi"
        cache.mkdir(mode=0o700)
        # Invalid sparse files already exceed the budget. Do not delete these
        # unknown contents, but do not add another thumbnail to the full cache.
        for index in range(33):
            path = cache / f"v1-{index:08x}.thumb"
            with path.open("xb") as file:
                file.write(b"BADMAGIC")
                file.truncate(8 * 1024 * 1024)
            path.chmod(0o600)
        before = {p.name: p.stat().st_size for p in self.entries()}
        self.run_image()
        self.assertEqual({p.name: p.stat().st_size for p in self.entries()}, before)
        self.assertEqual(self.entries()[0].read_bytes()[:8], b"BADMAGIC")

    def test_invalid_entries_also_count_towards_the_file_limit(self):
        cache = self.base / "kitty-lsi"
        cache.mkdir(mode=0o700)
        for index in range(4097):
            path = cache / f"v1-{index:08x}.thumb"
            with path.open("xb") as file:
                file.write(b"BADMAGIC")
            path.chmod(0o600)
        self.run_image()
        self.assertEqual(len(self.entries()), 4097)

    def test_locked_cache_falls_back_without_waiting(self):
        import fcntl
        self.run_image()
        lock = self.base / "kitty-lsi" / ".lock"
        with lock.open("rb") as file:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_image()

    def test_directory_and_symlink_icons_do_not_create_cache_entries(self):
        self.image.unlink()
        self.image.mkdir()
        self.run_image("-d")
        self.assertFalse((self.base / "kitty-lsi").exists())
        self.image.rmdir()
        self.image.symlink_to("missing.jpg")
        self.run_image()
        self.assertFalse((self.base / "kitty-lsi").exists())
