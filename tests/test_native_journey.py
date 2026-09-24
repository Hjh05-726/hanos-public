from __future__ import annotations

import os
import json
import runpy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
with mock.patch.object(sys, "path", [str(ROOT / "tests/behavioral-evals"), *sys.path]):
    JOURNEY = runpy.run_path(str(ROOT / "tests/behavioral-evals/run_journey.py"))


class NativeJourneyVerifierTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Native evaluator requires macOS or Linux")
    def test_timeout_retains_partial_native_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            trace, errors = root / "trace.jsonl", root / "stderr.txt"
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                JOURNEY["native"].execute_logged(
                    [sys.executable, "-u", "-c", "import time; print('partial evidence'); time.sleep(30)"],
                    root, trace, errors, 2,
                )
            self.assertIn("partial evidence", trace.read_text())
            self.assertTrue(errors.is_file())

    @unittest.skipUnless(os.name == "posix", "Native evaluator requires macOS or Linux")
    def test_timeout_stops_child_process_from_writing_later(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = "import time; from pathlib import Path; time.sleep(3); Path('late-write').write_text('unexpected')"
            parent = (
                "import subprocess,sys,time; "
                f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
                "print('child started', flush=True); time.sleep(30)"
            )
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                JOURNEY["native"].execute_logged(
                    [sys.executable, "-u", "-c", parent], root,
                    root / "trace.jsonl", root / "stderr.txt", 2,
                )
            self.assertIn("child started", (root / "trace.jsonl").read_text())
            time.sleep(1.5)
            self.assertFalse((root / "late-write").exists())

    def test_inserting_a_section_preserves_original_but_deleting_history_does_not(self) -> None:
        original = "# Project\n\nStatus: local\n\n## History\nOld observation\n"
        inserted = original.replace("## History", "## Plan\nNew observation\n\n## History")
        self.assertTrue(JOURNEY["preserves_original_lines"](original, inserted))
        self.assertFalse(JOURNEY["preserves_original_lines"](original, inserted.replace("Old observation", "")))
        self.assertFalse(JOURNEY["preserves_original_lines"](original, inserted.replace("Status: local", "Status: deployed")))
        truncated_correction = "tray_count=7\ntray_count=9\nNOT_PROVEN\nsuperseded\n"
        self.assertFalse(JOURNEY["preserves_original_lines"](original, truncated_correction))

    def test_runtime_exclusion_is_opt_in_and_does_not_ignore_source_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "module.py").write_text("print('fixture')\n")
            before = JOURNEY["files_digest"](root, ignore_runtime=True)
            (root / "__pycache__").mkdir()
            (root / "__pycache__/module.pyc").write_bytes(b"fixture")
            self.assertEqual(before, JOURNEY["files_digest"](root, ignore_runtime=True))
            self.assertNotEqual(before, JOURNEY["files_digest"](root))
            (root / "module.py").write_text("print('changed')\n")
            self.assertNotEqual(before, JOURNEY["files_digest"](root, ignore_runtime=True))

    def test_authority_write_requires_journal_and_rejects_other_knowledge_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / ".hanos/operations"
            logs.mkdir(parents=True)
            (logs / "operation.json").write_text(json.dumps({"status": "applied", "plan": {
                "root": str(root), "changes": [{"path": "authority.md",
                                                 "before_sha256": "old", "after_sha256": "new"}]}}))
            before = {"authority.md": "old"}
            after = {"authority.md": "new", ".hanos/operations/operation.json": "journal"}
            JOURNEY["require_authority_mutation"](root, before, after, "authority.md")
            for invalid in ({"authority.md": "new"},
                            {**after, "other-note.md": "unrelated"},
                            {**after, ".hanos/repositories.json": "changed"},
                            {"authority.md": "old", ".hanos/operations/operation.json": "journal"}):
                with self.assertRaises(RuntimeError):
                    JOURNEY["require_authority_mutation"](root, before, invalid, "authority.md")
