"""Public packaging CLI regressions; no binary execution or publication."""

import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleaseGateTests(unittest.TestCase):
    def command(self, repository, maintainer):
        with tempfile.TemporaryDirectory(prefix="lsi-release-gate-") as directory:
            out = pathlib.Path(directory) / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/build_release.py"),
                    "--binary",
                    str(ROOT / "LICENSE"),
                    "--out",
                    str(out),
                    "--release",
                    "--repository",
                    repository,
                    "--revision",
                    "1" * 40,
                    "--maintainer",
                    maintainer,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertFalse(out.exists(), "invalid release must create no output")
            self.assertNotEqual(result.returncode, 0)
            return result.stderr

    def test_release_rejects_placeholder_repository_before_building(self):
        error = self.command(
            "LOCAL-VALIDATION/NOT-PUBLISHED", "Maintainer <release@example.invalid>"
        )
        self.assertIn("placeholder repository", error)

    def test_release_rejects_reserved_maintainer_contact_before_building(self):
        error = self.command("actual-project/lsi", "UNCONFIGURED <noreply@example.invalid>")
        self.assertIn("reserved or placeholder maintainer", error)

    def test_invalid_elf_candidate_is_rejected_without_creating_output(self):
        with tempfile.TemporaryDirectory(prefix="lsi-release-elf-") as directory:
            out = pathlib.Path(directory) / "output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/build_release.py"),
                    "--binary",
                    str(ROOT / "LICENSE"),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ELF verification failed", result.stderr)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
