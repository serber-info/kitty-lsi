"""Acceptance tests of the Rust CLI; Python/Pillow are developer fixture tools only."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
from acceptance_support import CommandTests

BINARY = Path(os.environ.get("LSI_BINARY", ROOT / "rust/target/debug/lsi")).resolve()


class RustCommandTests(CommandTests):
    def command(self, *args):
        return subprocess.run([str(BINARY), *args], cwd=self.root,
                              capture_output=True, text=True, timeout=20,
                              env={**os.environ, "LC_ALL": "C", "TZ": "UTC"})

    def test_grid_centers_only_directory_labels(self):
        names = {"git": 3, "Música": 6, "照片": 4, "e\u0301": 1}
        for name in names:
            (self.root / name).mkdir()
        for width in (14, 15, 20):
            for name, cells in names.items():
                with self.subTest(width=width, name=name):
                    code, raw, plain, errors = self.terminal_command(
                        "--width", str(width), "-d", name)
                    self.assertEqual(code, 0, errors)
                    self.assertIn("a=T,f=100", raw)
                    padding = width - cells
                    expected = " " * (padding // 2) + name + " " * (padding - padding // 2)
                    self.assertIn(expected, plain.splitlines())

        code, _, plain, errors = self.terminal_command("--width", "14", "-dF", "git")
        self.assertEqual(code, 0, errors)
        self.assertIn("     git/     ", plain.splitlines())

        # Long names still truncate to the same cell width.
        (self.root / "abcdefghijklmnop").mkdir()
        code, _, plain, errors = self.terminal_command("-d", "abcdefghijklmnop")
        self.assertEqual(code, 0, errors)
        self.assertIn("abcdefghijklm…", plain.splitlines())

    def test_centering_does_not_change_files_links_rows_or_plain_output(self):
        from PIL import Image
        (self.root / "git").mkdir()
        (self.root / "link").symlink_to("git", target_is_directory=True)
        Image.new("RGB", (10, 10)).save(self.root / "a.png")
        for name in ("small.txt", "a.png", "link"):
            code, _, plain, errors = self.terminal_command("-d", name)
            self.assertEqual(code, 0, errors)
            self.assertIn(name.ljust(14), plain.splitlines())
        code, _, plain, errors = self.terminal_command("-d", "git", "small.txt", columns=40)
        self.assertEqual(code, 0, errors)
        self.assertIn("     git      " + "   " + "small.txt     ", plain.splitlines())
        code, _, plain, errors = self.terminal_command("-d", "git", columns=12)
        self.assertEqual(code, 0, errors)
        self.assertEqual(plain.splitlines(), ["git"])
        for flag in ("-l", "-1"):
            code, _, plain, errors = self.terminal_command("-d", flag, "git")
            self.assertEqual(code, 0, errors)
            self.assertIn("▧" * 14 + "  git", plain.splitlines())
        for args in (("-d", "git"), ("--no-images", "-d", "git")):
            self.assertEqual(self.command(*args).stdout, "git\n")

    def test_grid_directory_inode_is_above_the_centered_name(self):
        names = {"Mi_carpeta": 10, "Música": 6, "照片": 4}
        for name in names:
            (self.root / name).mkdir()
        for width in (14, 20):
            for name, cells in names.items():
                with self.subTest(width=width, name=name):
                    inode = str((self.root / name).stat().st_ino)
                    code, _, plain, errors = self.terminal_command(
                        "-id", "--width", str(width), name)
                    self.assertEqual(code, 0, errors)
                    padding = width - cells
                    expected = " " * (padding // 2) + name + " " * (padding - padding // 2)
                    lines = plain.splitlines()
                    index = lines.index(expected)
                    self.assertEqual(lines[index - 1], inode.center(width))
                    self.assertEqual(len(lines), 8)  # Image, inode, name, blank.
        name = "abcdefghijklmnop"
        (self.root / name).mkdir()
        code, _, plain, errors = self.terminal_command("-id", name)
        self.assertEqual(code, 0, errors)
        self.assertIn("abcdefghijklm…", plain.splitlines())

    def test_grid_inode_mixed_row_preserves_file_and_other_modes(self):
        (self.root / "git").mkdir()
        inode = str((self.root / "git").stat().st_ino)
        file_inode = str((self.root / "small.txt").stat().st_ino)
        label = file_inode + " small.txt"
        file_label = (label[:13] + "…") if len(label) > 14 else label.ljust(14)
        code, _, plain, errors = self.terminal_command(
            "-id", "git", "small.txt", columns=40)
        self.assertEqual(code, 0, errors)
        lines = plain.splitlines()
        self.assertEqual(lines[5], inode.center(14) + "   " + " " * 14)
        self.assertEqual(lines[6], "     git      " + "   " + file_label)
        code, _, plain, errors = self.terminal_command("-id", "small.txt")
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(plain.splitlines()), 7)  # Files keep a single label.
        self.assertIn(file_label, plain.splitlines())
        for args in (("-id", "git"), ("--no-images", "-id", "git")):
            self.assertEqual(self.command(*args).stdout, inode + " git\n")
        code, _, plain, errors = self.terminal_command("-lid", "git")
        self.assertEqual(code, 0, errors)
        self.assertIn("▧" * 14 + "  git", plain.splitlines())
        self.assertTrue(any(inode in line and "drwx" in line for line in plain.splitlines()))












    def test_lli_is_the_long_listing_entrypoint(self):
        alias = self.root / "lli"
        alias.symlink_to(BINARY)
        result = subprocess.run([str(alias), "-h", "small.txt"], cwd=self.root,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^-rw-.*1\.5K.*small.txt")


    def test_hidden_files_and_directory_traversal(self):
        (self.root / ".secret.png").touch()
        (self.root / "folder").mkdir()
        (self.root / "folder" / "nested.txt").touch()
        self.assertNotIn(".secret.png", self.command().stdout)
        almost = self.command("-A")
        self.assertEqual(almost.returncode, 0, almost.stderr)
        self.assertEqual(almost.stdout.splitlines(), ["folder", ".secret.png", "small.txt"])
        self.assertEqual(self.command("-a").stdout.splitlines()[:2], [".", ".."])
        self.assertEqual(self.command("-d", "folder").stdout, "folder\n")
        recursive = self.command("-Ra")
        self.assertEqual(recursive.returncode, 0, recursive.stderr)
        self.assertEqual(recursive.stdout.count("nested.txt"), 1)
        self.assertIn("folder:", recursive.stdout)


    def test_corrupt_preview_keeps_other_files_and_returns_error(self):
        # Run this malformed-image case only in the isolated security harness.
        from PIL import Image
        (self.root / "bad.png").write_bytes(b"bad PNG")
        Image.new("RGB", (10, 10), "red").save(self.root / "good.png")
        code, raw, plain, errors = self.terminal_command()
        self.assertEqual(code, 1)
        self.assertIn("good.png", plain)
        self.assertIn("bad.png", plain)
        self.assertNotIn("[unreadable]", plain)
        self.assertIn("a=T,f=100", raw)
        self.assertIn("bad.png", errors)
        self.assertNotIn("Traceback", errors)
        # The first raster is the amber warning icon, not a fake thumbnail.
        import base64
        import io
        import re
        payload = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)[0]
        with Image.open(io.BytesIO(base64.b64decode(payload))) as icon:
            self.assertEqual(icon.size, (96, 80))
            self.assertEqual(icon.getpixel((40, 58)), (239, 167, 70, 255))


    def test_links_and_fifos_are_not_opened_or_followed(self):
        (self.root / "link.png").symlink_to("missing.png")
        os.mkfifo(self.root / "pipe.png")
        (self.root / "loop").symlink_to(".", target_is_directory=True)
        code, raw, plain, errors = self.terminal_command("-RF")
        self.assertEqual(code, 0, errors)
        self.assertIn("link.png@", plain)
        self.assertIn("pipe.png|", plain)
        self.assertIn("a=T,f=100", raw)  # Icons do not open their represented entry.
        self.assertNotIn("[link]", plain)
        self.assertNotIn("[file]", plain)


    def test_neutral_directory_icon_in_grid_and_long_modes(self):
        (self.root / "b-folder").mkdir()
        (self.root / "z-folder").mkdir()
        (self.root / "a-file.txt").touch()
        for flags in [[], ["-lh"]]:
            with self.subTest(flags=flags):
                code, raw, plain, errors = self.terminal_command(*flags)
                self.assertEqual(code, 0, errors)
                self.assertNotIn("[directory]", plain)
                self.assertNotIn("[dir]", plain)
                # Two folders render self-contained PNGs; no font glyph required.
                import re
                import base64
                import io
                from PIL import Image
                messages = re.findall(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\", raw)
                folder_pngs = [payload for control, payload in messages if "a=T" in control][:2]
                self.assertEqual(len(folder_pngs), 2)
                for payload in folder_pngs:
                    with Image.open(io.BytesIO(base64.b64decode(payload))) as icon:
                        self.assertEqual(icon.size, (96, 80))
                        self.assertEqual(icon.getpixel((48, 40)), (238, 190, 79, 255))
                        self.assertEqual(icon.getpixel((0, 0))[3], 0)
                self.assertLess(plain.index("b-folder"), plain.index("z-folder"))
                self.assertLess(plain.index("z-folder"), plain.index("a-file.txt"))
        plain = self.command().stdout
        self.assertNotIn("📁", plain)  # Pipes remain plain filenames/metadata.


    def test_all_entry_types_have_icons_without_text_placeholders(self):
        import base64
        import io
        import re
        import socket
        from PIL import Image
        (self.root / "folder").mkdir()
        (self.root / "file-link").symlink_to("small.txt")
        (self.root / "folder-link").symlink_to("folder")
        (self.root / "broken-link").symlink_to("missing")
        (self.root / "run").touch(mode=0o755)
        os.mkfifo(self.root / "pipe")
        endpoint = socket.socket(socket.AF_UNIX)
        self.addCleanup(endpoint.close)
        socket_available = True
        try:
            endpoint.bind(str(self.root / "socket"))
        except PermissionError:
            socket_available = False
        icons = {}
        for name in ["folder", "small.txt", "file-link", "folder-link",
                     "broken-link", "pipe", "socket", "run"]:
            if name == "socket" and not socket_available:
                with self.subTest(name=name):
                    self.skipTest("sandbox forbids creating a Unix socket fixture")
                continue
            for flags in [[], ["-lh"]]:
                with self.subTest(name=name, flags=flags):
                    code, raw, plain, errors = self.terminal_command("-d", *flags, name)
                    self.assertEqual(code, 0, errors)
                    for placeholder in ["[file]", "[link]", "[dir]", "[unreadable]"]:
                        self.assertNotIn(placeholder, plain)
                    chunks = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)
                    self.assertTrue(chunks, "entry must transmit an icon")
                    png = base64.b64decode("".join(chunks))
                    with Image.open(io.BytesIO(png)) as icon:
                        self.assertEqual(icon.size, (96, 80))
                        self.assertEqual(icon.getpixel((0, 0))[3], 0)
                    icons[name] = png
        self.assertEqual(icons["file-link"], icons["folder-link"])
        self.assertEqual(icons["file-link"], icons["broken-link"])
        distinct = ["folder", "small.txt", "file-link", "pipe", "run"]
        if socket_available:
            distinct.append("socket")
        self.assertEqual(len({icons[name] for name in distinct}), len(distinct))
        for flags in [[], ["--no-images"], ["-lh"]]:
            result = self.command(*flags)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("\x1b", result.stdout)
            self.assertIn("small.txt", result.stdout)



    def test_extension_icons_are_distinct_case_insensitive_and_do_not_open_content(self):
        import base64
        import io
        import re
        from PIL import Image
        extensions = [
            "mp4", "mkv", "avi", "mov", "webm",
            "mp3", "wav", "flac", "aac", "ogg", "m4a", "svg",
            "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tar.gz", "tar.xz",
            "pdf", "doc", "docx", "odt", "rtf", "txt", "md",
            "xls", "xlsx", "ods", "csv", "ppt", "pptx", "odp",
            "exe", "msi", "bat", "sh", "py", "js", "iso", "img",
            "html", "css", "json", "xml", "yaml", "sql",
        ]
        def png_for(name, flags=()):
            code, raw, plain, errors = self.terminal_command(*flags, name)
            self.assertEqual(code, 0, errors)
            for placeholder in ["[file]", "[link]", "[dir]", "[unreadable]"]:
                self.assertNotIn(placeholder, plain)
            chunks = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)
            self.assertTrue(chunks)
            return base64.b64decode("".join(chunks))
        icons = {}
        for extension in extensions:
            with self.subTest(extension=extension):
                name = "x." + extension
                path = self.root / name
                path.write_bytes(b"not interpreted, rendered, executed or decompressed")
                path.chmod(0)  # Only metadata is needed for non-image icons.
                self.addCleanup(path.chmod, 0o600)
                png = png_for(name)
                self.assertEqual(png, png_for(name, ("-lh",)))
                with Image.open(io.BytesIO(png)) as icon:
                    self.assertEqual(icon.size, (96, 80))
                    self.assertEqual(icon.getpixel((0, 0))[3], 0)
                icons[extension] = png
        self.assertEqual(len(set(icons.values())), len(extensions))
        for suffix, equivalent in [("PDF", "pdf"), ("TAR.GZ", "tar.gz"),
                                   ("TAR.XZ", "tar.xz"), ("yml", "yaml")]:
            name = "x." + suffix
            (self.root / name).touch()
            self.assertEqual(png_for(name), icons[equivalent])
        for name in ["unknown", "x.unknownextension"]:
            (self.root / name).touch()
        self.assertEqual(png_for("unknown"), png_for("x.unknownextension"))
        self.assertNotIn(png_for("unknown"), icons.values())
        # Unknown regular files stay generic even when their executable bit is set.
        for name in ["unknown-run", "run.unsupported"]:
            (self.root / name).touch(mode=0o755)
            self.assertEqual(png_for(name), png_for("unknown"))
        # Link classification wins over its apparent extension and target type.
        (self.root / "link.pdf").symlink_to("x.mp4")
        (self.root / "link").symlink_to("missing")
        self.assertEqual(png_for("link.pdf"), png_for("link"))
        Image.new("RGB", (20, 10), "blue").save(self.root / "real.PNG")
        with Image.open(io.BytesIO(png_for("real.PNG"))) as image:
            self.assertEqual(image.size, (20, 10))
            self.assertEqual(image.convert("RGB").getpixel((10, 5)), (0, 0, 255))


# Do not discover the imported reference class as an extra test suite.
del CommandTests

def _test_original_formats(self):
    import base64
    import io
    import re
    from PIL import Image
    for extension, codec in [("png", "PNG"), ("jpg", "JPEG"), ("gif", "GIF"),
                             ("webp", "WEBP"), ("bmp", "BMP"), ("tiff", "TIFF"),
                             ("ico", "ICO"), ("avif", "AVIF")]:
        with self.subTest(codec=codec):
            path = self.root / ("sample." + extension)
            Image.new("RGB", (64, 64), "red").save(path, format=codec)
            code, raw, plain, errors = self.terminal_command(path.name)
            self.assertEqual(code, 0, errors)
            self.assertIn("a=T,f=100", raw)
            chunks = re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", raw)
            with Image.open(io.BytesIO(base64.b64decode("".join(chunks)))) as preview:
                self.assertEqual(preview.format, "PNG")
                r, g, b, a = preview.convert("RGBA").getpixel((32, 32))
                self.assertGreater(r, 200)
                self.assertLess(g, 40)
                self.assertLess(b, 40)
                self.assertEqual(a, 255)

RustCommandTests.test_all_original_raster_formats = _test_original_formats
