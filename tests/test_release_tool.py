from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.release import build, export


class ReleaseToolTests(unittest.TestCase):
    def fixture(self, parent: Path) -> Path:
        root = parent / "source"
        root.mkdir()
        (root / "skills/hanos").mkdir(parents=True)
        files = {"VERSION": "0.1.0-preview.1\n", "LICENSE": "fixture license\n",
                 "skills/hanos/LICENSE": "fixture license\n"}
        source_core = Path(__file__).resolve().parents[1] / "skills/hanos"
        for name in ("template-lock.json", "scripts/generate_html.py", "scripts/star_layout.py"):
            files[f"skills/hanos/{name}"] = (source_core / name).read_text(encoding="utf-8")
        names = sorted([*files, "release-files.txt", ".gitignore"])
        files["release-files.txt"] = "\n".join(names) + "\n"
        files[".gitignore"] = "*\n!skills/\n!skills/hanos/\n!skills/hanos/scripts/\n" + "\n".join("!" + p for p in names) + "\n"
        for name, content in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(content, encoding="utf-8")
        for command in (["git", "init", "-q"], ["git", "add", "--", *names],
                        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                         "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"]):
            subprocess.run(command, cwd=root, check=True, capture_output=True)
        return root

    def test_export_excludes_private_files_and_has_no_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = self.fixture(parent)
            (root / "private.md").write_text("Private fixture, never export.")
            result = export(root, parent / "public")
            self.assertFalse((result / "private.md").exists())
            self.assertFalse((result / ".git").exists())
            self.assertEqual((root / "private.md").read_text(), "Private fixture, never export.")

    def test_release_refuses_changed_template_before_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = self.fixture(parent)
            layout = root / "skills/hanos/scripts/star_layout.py"
            layout.write_text(layout.read_text(encoding="utf-8") + "\n# unexpected change\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TEMPLATE_PACKAGE_INVALID"):
                export(root, parent / "public")
            self.assertFalse((parent / "public").exists())

    def test_archives_are_reproducible_and_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = self.fixture(parent)
            first, second = build(root, parent / "a"), build(root, parent / "b")
            filename = "hanos-0.1.0-preview.1.zip"
            self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            manifest = json.loads((first / "source-manifest.json").read_text())
            with zipfile.ZipFile(first / filename) as archive:
                self.assertEqual(set(archive.namelist()), {"hanos-0.1.0-preview.1/" + p for p in manifest})
                for path, checksum in manifest.items():
                    self.assertEqual(hashlib.sha256(archive.read("hanos-0.1.0-preview.1/" + path)).hexdigest(), checksum)

    def test_dirty_checkout_and_existing_destination_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = self.fixture(parent)
            existing = parent / "existing"
            existing.mkdir()
            (existing / "owner.txt").write_text("keep")
            with self.assertRaises(ValueError):
                export(root, existing)
            (root / "VERSION").write_text("0.1.1\n")
            with self.assertRaises(ValueError):
                build(root, parent / "archive")
            self.assertFalse((parent / "archive").exists())
            self.assertEqual((existing / "owner.txt").read_text(), "keep")

    def test_escape_symlink_and_source_destination_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            root = self.fixture(parent)
            with self.assertRaises(ValueError):
                export(root, root / "output")
            (root / "LICENSE").unlink()
            (parent / "outside.txt").write_text("outside")
            (root / "LICENSE").symlink_to(parent / "outside.txt")
            with self.assertRaises(ValueError):
                export(root, parent / "output")
            self.assertFalse((parent / "output").exists())
            (root / "release-files.txt").write_text("../outside.txt\n")
            with self.assertRaises(ValueError):
                export(root, parent / "output")


if __name__ == "__main__":
    unittest.main()
