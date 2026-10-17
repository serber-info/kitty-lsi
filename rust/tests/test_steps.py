"""Paging through the executable and a real bidirectional PTY, not a pager mock."""
import errno
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
BINARY = Path(os.environ.get("LSI_BINARY", ROOT / "rust/target/debug/lsi")).resolve()
PROMPT = b"Press ENTER to continue..."


class Session:
    def __init__(self, root, args, stdin_tty=True, env_extra=None):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 1000, 600))
        env = {**os.environ, "TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1",
               "HOME": str(root), "XDG_CACHE_HOME": str(root / ".cache")}
        env.update(env_extra or {})
        env.pop("TMUX", None)
        env.pop("STY", None)
        self.process = subprocess.Popen(
            [str(BINARY), *args], cwd=root, env=env,
            stdin=slave if stdin_tty else subprocess.DEVNULL,
            stdout=slave, stderr=subprocess.PIPE)
        os.close(slave)
        self.raw = b""

    def read(self, timeout=0.1):
        if select.select([self.master], [], [], timeout)[0]:
            try:
                data = os.read(self.master, 65536)
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                return False
            self.raw += data
            return bool(data)
        return True

    def until_prompt(self, count):
        deadline = time.monotonic() + 10
        while self.raw.count(PROMPT) < count:
            if time.monotonic() >= deadline:
                raise AssertionError("paging prompt did not arrive")
            if not self.read():
                raise AssertionError("process exited before the paging prompt: " +
                                     self.process.communicate(timeout=2)[1].decode())
        # Give an incorrectly eager implementation time to emit the next page.
        end = time.monotonic() + 0.1
        while time.monotonic() < end:
            self.read(0.01)

    def finish(self):
        deadline = time.monotonic() + 10
        while self.read():
            if time.monotonic() >= deadline:
                raise AssertionError("paging command did not finish")
        _, errors = self.process.communicate(timeout=2)
        return self.process.returncode, errors.decode()

    def plain(self):
        text = self.raw.decode()
        text = re.sub(r"\x1b_G.*?\x1b\\", "", text, flags=re.S)
        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.communicate()
        os.close(self.master)


class StepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def files(self, count):
        for i in range(count):
            (self.root / f"entry{i:02}.txt").touch()

    def session(self, *args, **kwargs):
        session = Session(self.root, args, **kwargs)
        self.addCleanup(session.close)
        return session

    def test_short_step_waits_after_five_entries_in_grid_and_long_modes(self):
        self.files(12)
        for flags in [("-s",), ("-ls",)]:
            with self.subTest(flags=flags):
                s = self.session(*flags)
                for page in (1, 2):
                    s.until_prompt(page)
                    names = re.findall(r"entry\d\d\.txt", s.plain())
                    self.assertEqual(names, [f"entry{i:02}.txt" for i in range(page * 5)])
                    self.assertEqual(s.raw.count(b"a=T,f=100"), page * 5)
                    self.assertIsNone(s.process.poll())
                    os.write(s.master, b"\n")
                code, errors = s.finish()
                self.assertEqual(code, 0, errors)
                self.assertEqual(s.raw.count(PROMPT), 2)
                self.assertEqual(re.findall(r"entry\d\d\.txt", s.plain()),
                                 [f"entry{i:02}.txt" for i in range(12)])

    def test_custom_step_takes_precedence_and_has_no_final_prompt(self):
        self.files(26)
        for flags in [("-s", "--step=25"), ("-ls", "--step=25")]:
            with self.subTest(flags=flags):
                s = self.session(*flags)
                s.until_prompt(1)
                self.assertEqual(len(re.findall(r"entry\d\d\.txt", s.plain())), 25)
                os.write(s.master, b"\n")
                code, errors = s.finish()
                self.assertEqual(code, 0, errors)
                self.assertEqual(s.raw.count(PROMPT), 1)
                self.assertIn("entry25.txt", s.plain())

    def test_short_exact_and_empty_listings_do_not_prompt(self):
        for count, args in [(0, ("-ls",)), (3, ("-ls",)),
                            (3, ("--step=25",)), (5, ("-s",)),
                            (5, ("-ls",)), (50, ("--step=50",))]:
            with self.subTest(count=count, args=args):
                self.files(count)
                s = self.session(*args)
                code, errors = s.finish()
                self.assertEqual(code, 0, errors)
                self.assertNotIn(PROMPT, s.raw)
                self.assertEqual(len(re.findall(r"entry\d\d\.txt", s.plain())), count)

    def test_no_paging_is_automatic_even_with_more_than_fifty_images(self):
        from PIL import Image
        for i in range(51):
            Image.new("RGB", (2, 2)).save(self.root / f"image{i:02}.png")
        s = self.session("--no-images")
        code, errors = s.finish()
        self.assertEqual(code, 0, errors)
        self.assertNotIn(PROMPT, s.raw)
        self.assertNotIn(b"More than 50", s.raw)
        self.assertEqual(len(re.findall(r"image\d\d\.png", s.plain())), 51)

    def test_noninteractive_input_or_output_never_waits(self):
        self.files(12)
        s = self.session("-ls", stdin_tty=False)
        code, errors = s.finish()
        self.assertEqual(code, 0, errors)
        self.assertNotIn(PROMPT, s.raw)
        self.assertEqual(len(re.findall(r"entry\d\d\.txt", s.plain())), 12)
        master, slave = pty.openpty()
        try:
            result = subprocess.run([str(BINARY), "-ls"], cwd=self.root,
                                    stdin=slave, capture_output=True, timeout=10)
        finally:
            os.close(slave)
            os.close(master)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(PROMPT, result.stdout)
        self.assertEqual(result.stdout.count(b"entry"), 12)

    def test_eof_stops_without_rendering_the_next_page(self):
        self.files(12)
        s = self.session("-ls")
        s.until_prompt(1)
        os.write(s.master, b"\x04")
        code, errors = s.finish()
        self.assertEqual(code, 0, errors)
        self.assertEqual(s.raw.count(b"a=T,f=100"), 5)
        self.assertNotIn("entry05.txt", s.plain())

    def test_interrupt_stops_without_rendering_the_next_page(self):
        self.files(12)
        s = self.session("-s")
        s.until_prompt(1)
        s.process.send_signal(signal.SIGINT)
        code, _ = s.finish()
        self.assertIn(code, (-signal.SIGINT, 128 + signal.SIGINT))
        self.assertNotIn("entry05.txt", s.plain())

    def test_directories_count_as_entries_and_keep_their_order(self):
        self.files(3)
        for i in range(3):
            (self.root / f"folder{i}").mkdir()
        s = self.session("-s")
        s.until_prompt(1)
        names = re.findall(r"folder\d|entry\d\d\.txt", s.plain())
        self.assertEqual(names, ["folder0", "folder1", "folder2", "entry00.txt", "entry01.txt"])
        os.write(s.master, b"\n")
        code, errors = s.finish()
        self.assertEqual(code, 0, errors)
        self.assertIn("entry02.txt", s.plain())
