from __future__ import annotations

import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
with mock.patch.object(sys, "path", [str(ROOT / "tests/behavioral-evals"), *sys.path]):
    JOURNEY = runpy.run_path(str(ROOT / "tests/behavioral-evals/run_journey.py"))


class NativeJourneyVerifierTests(unittest.TestCase):
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
