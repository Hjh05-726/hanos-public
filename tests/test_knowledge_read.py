"""Synthetic read/query evidence: AC-07 through AC-12 and AC-17 read boundary."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/hanos/scripts"
sys.path.insert(0, str(SCRIPTS))
from knowledge_read import Knowledge, KnowledgeError  # noqa: E402


class KnowledgeReadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "home"
        for directory in (".hanos", "project-a", "project-b"):
            (self.root / directory).mkdir(parents=True)
        self.registry = self.root / ".hanos/repositories.json"
        self.registry.write_text(json.dumps({"version": 1, "repositories": [
            {"id": "a", "name": "Project A", "aliases": ["Alpha"], "type": "project", "path": "project-a"},
            {"id": "b", "name": "Project B", "type": "project", "path": "project-b"},
        ]}))
        self.config = self.base / "config.json"
        self.config.write_text(json.dumps({"knowledge_home": str(self.root)}))
        self.knowledge = Knowledge(self.config, "Alpha")

    def note(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def snapshot(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob("*") if path.is_file() and not path.is_symlink()}

    def assert_status(self, status, callback):
        with self.assertRaises(KnowledgeError) as caught:
            callback()
        self.assertEqual(caught.exception.status, status)

    def test_ac07_names_aliases_and_filename_before_keywords(self):
        self.note("project-a/method.md", "---\naliases: [方法, Alpha]\n---\n# Learning\nEvidence\n")
        self.note("project-a/other.md", "# Other\nLearning appears only as a keyword.")
        for term in ("Learning", "method", "method.md", "方法", "Alpha", "project-a/method.md"):
            result = self.knowledge.query(term)
            self.assertEqual(result["status"], "ok", term)
            self.assertEqual(result["hits"][0]["path"], "project-a/method.md")
            self.assertIn("Evidence", result["hits"][0]["excerpt"])
        self.assertEqual(self.knowledge.scope_id, "a")

    def test_ac07_duplicate_titles_and_overlapping_aliases_remain_ambiguous(self):
        self.note("project-a/one.md", "---\naliases:\n  - shared\n---\n# Same\none")
        self.note("project-a/two.md", "---\naliases: shared\n---\n# Same\ntwo")
        for term in ("Same", "shared"):
            result = self.knowledge.query(term)
            self.assertEqual(result["status"], "ambiguous")
            self.assertEqual(len(result["hits"]), 2)
        self.assertEqual(self.knowledge.query("one.md")["status"], "ok")

    def test_ac08_scope_filters_unknown_properties_and_unsupported_yaml(self):
        original = "---\nstatus: current\ntags: [book, 中文]\ncustom: hand-kept\nnested:\n  object: remains\nmultiline: |\n  unchanged\n---\n# Topic\nshared evidence\n"
        path = self.note("project-a/topic.md", original)
        self.note("project-b/topic.md", "---\nstatus: current\n---\n# Topic\noutside shared evidence")
        before = self.snapshot()
        result = self.knowledge.query("shared", {"tags": "中文", "custom": "hand-kept"})
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["scope"]["id"], "a")
        self.assertTrue(any("Unsupported property nested" in warning for warning in result["warnings"]))
        self.assertEqual(self.knowledge.query("shared", {"status": "old"})["status"], "not_found")
        self.assert_status("unsupported_filter", lambda: self.knowledge.query("shared", {"nested": {"object": "x"}}))
        self.assertEqual(path.read_text(), original)
        self.assertEqual(before, self.snapshot())

    def test_ac09_exact_section_version_position_and_crlf(self):
        text = "---\ncustom: untouched\n---\n# Long\nIntro\n## Claim\nOriginal evidence\n### Detail\nA qualification\n## Next\nOther\n".replace("\n", "\r\n")
        path = self.note("project-a/long.md", text)
        result = self.knowledge.read("project-a/long.md", "Claim")
        self.assertEqual((result["start_line"], result["end_line"]), (6, 9))
        self.assertEqual(result["excerpt"], "".join(text.splitlines(keepends=True)[5:9]))
        self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_bytes(("Prefix\r\n" + text).encode())
        updated = self.knowledge.read("project-a/long.md", "Claim")
        self.assertEqual(updated["start_line"], 7)
        self.assertNotEqual(updated["sha256"], result["sha256"])
        self.assert_status("section_not_found", lambda: self.knowledge.read("project-a/long.md", "Absent"))

    def test_ac09_repeated_sections_cannot_choose_arbitrarily(self):
        self.note("project-a/note.md", "# Note\n## Same\none\n## Same\ntwo")
        self.assert_status("ambiguous_section", lambda: self.knowledge.read("project-a/note.md", "Same"))

    def test_ac09_source_snapshot_requires_explicit_control_and_never_scans(self):
        self.note(".hanos/sources/a/version/raw.txt", "A preserved source")
        self.note(".hanos/operations/a/backup.md", "A preserved source")
        self.assertEqual(self.knowledge.read(".hanos/sources/a/version/raw.txt", control=True)["excerpt"], "A preserved source")
        self.assert_status("unsafe_path", lambda: self.knowledge.read(".hanos/sources/a/version/raw.txt"))
        self.assert_status("unsafe_path", lambda: self.knowledge.read(".hanos/operations/a/backup.md", control=True))
        self.assertEqual(self.knowledge.query("preserved")["status"], "not_found")

    def test_ac10_real_links_positions_sections_broken_ambiguous_and_code(self):
        self.note("project-a/target.md", "---\naliases: [Alias]\n---\n# Target\n## Detail\nbody")
        self.note("project-a/dupe1.md", "# Duplicate")
        self.note("project-a/dupe2.md", "# Duplicate")
        text = "# Referrer\n## Links\n[[Target#Detail|Label]]\n[relative](target.md#detail)\n[[Alias]]\n[[Missing]]\n[[Duplicate]]\n[[Target#Absent]]\n`[[Target]]` and ``[code](target.md)``\n```md\n[[Target]]\n```\n~~~md\n[code](target.md)\n~~~\n    [[Target]]\n<!-- [[Target]] -->\nTarget is only a word.\n"
        self.note("project-a/ref.md", text)
        before = self.snapshot()
        result = self.knowledge.backlinks("Target")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([hit["start_line"] for hit in result["hits"]], [3, 4, 5])
        self.assertTrue(all(hit["section"] == "Links" for hit in result["hits"]))
        self.assertEqual({issue["status"] for issue in result["link_issues"]}, {"broken", "ambiguous", "broken_section"})
        for hit in result["hits"]:
            self.assertEqual(hit["excerpt"], text.splitlines(keepends=True)[hit["start_line"] - 1])
        self.assertEqual(before, self.snapshot())

    def test_ac10_quoted_fences_are_code_not_backlinks(self):
        self.note("project-a/target.md", "# Target")
        text = "# Ref\n> ```md\n> [[Target]]\n> [code](target.md)\n> ```\n[[Target]]\n> > ~~~\n> > [[Target]]\n> > ~~~\n[real](target.md)\n"
        self.note("project-a/ref.md", text)
        result = self.knowledge.backlinks("Target")
        self.assertEqual([h["start_line"] for h in result["hits"]], [6, 10])
        for hit in result["hits"]:
            self.assertEqual(hit["excerpt"], text.splitlines(keepends=True)[hit["start_line"] - 1])

    def test_ac10_nested_relative_links_and_outside_scope(self):
        self.note("project-a/target.md", "# Target")
        self.note("project-b/outside.md", "# Outside")
        self.note("project-a/sub/ref.md", "[ok](../target.md)\n[outside](../../project-b/outside.md)\n[[project-a/target]]")
        result = self.knowledge.backlinks("Target")
        self.assertEqual(len(result["hits"]), 2)
        self.assertEqual(result["link_issues"][0]["status"], "unsafe")

    def test_ac11_no_result_and_conflicts_are_evidence_candidates(self):
        self.note("project-a/one.md", "# Source One\nlaunch date is Monday")
        self.note("project-a/two.md", "# Source Two\nlaunch date is Friday")
        self.note("project-b/secret.md", "# Outside\nunique-outside")
        for term in ("absent", "unique-outside"):
            result = self.knowledge.query(term)
            self.assertEqual(result["status"], "not_found")
            self.assertIn("selected scope", result["warnings"][-1])
        result = self.knowledge.query("launch date")
        self.assertEqual(result["status"], "candidates")
        self.assertEqual(len(result["hits"]), 2)
        self.assertTrue(any("Monday" in hit["excerpt"] for hit in result["hits"]))
        self.assertTrue(any("Friday" in hit["excerpt"] for hit in result["hits"]))

    def test_ac12_readonly_and_external_update_is_visible_next_query(self):
        path = self.note("project-a/fresh.md", "# Fresh\nold evidence")
        before = self.snapshot()
        first = self.knowledge.query("Fresh")
        self.knowledge.backlinks("Fresh")
        self.assertEqual(before, self.snapshot())
        path.write_text("# Fresh\nnew evidence")
        second = self.knowledge.query("Fresh")
        self.assertIn("new evidence", second["hits"][0]["excerpt"])
        self.assertNotEqual(first["hits"][0]["sha256"], second["hits"][0]["sha256"])
        self.assertFalse(any(path.name == "index.json" for path in self.root.rglob("*")))

    def test_ac17_traversal_hidden_control_and_symlink_boundaries(self):
        decoy = self.note("project-b/decoy.md", "Do not read")
        self.note("project-a/.private/secret.md", "hidden")
        (self.root / "project-a/link.md").symlink_to(decoy)
        (self.root / "project-a/linked-dir").symlink_to(self.root / "project-b", target_is_directory=True)
        for path in ("../outside.md", "project-a/../project-b/decoy.md", "project-b/decoy.md", "project-a/link.md", "project-a/linked-dir/decoy.md", "project-a/.private/secret.md"):
            self.assert_status("unsafe_path", lambda p=path: self.knowledge.read(p))
        for path in (".hanos/sources/b/raw.md", ".hanos/operations/a/raw.md", ".hanos/sources/a/.secret/raw.md"):
            self.assert_status("unsafe_path", lambda p=path: self.knowledge.safe(p, control=True))
        self.assertEqual(self.knowledge.query("Do not read")["status"], "not_found")
        self.assertEqual(self.knowledge.query("hidden")["status"], "not_found")

    def test_ac17_snapshot_directory_symlink_and_scope_replacement_rejected(self):
        sources = self.root / ".hanos/sources"
        sources.symlink_to(self.base, target_is_directory=True)
        self.assert_status("unsafe_path", lambda: self.knowledge.safe(".hanos/sources/a/raw.md", control=True))
        (self.root / "project-a").rmdir()
        (self.root / "project-a").symlink_to(self.root / "project-b", target_is_directory=True)
        self.assert_status("unsafe_path", lambda: self.knowledge.query("anything"))

    def test_all_active_entries_validated_before_selecting_good_one(self):
        document = json.loads(self.registry.read_text())
        document["repositories"][1]["path"] = "missing"
        self.registry.write_text(json.dumps(document))
        self.assert_status("invalid_registry", lambda: Knowledge(self.config, "a"))

    def test_invalid_registry_alias_type_and_deleted_entry_are_explicit(self):
        document = json.loads(self.registry.read_text())
        document["repositories"][1]["aliases"] = 0
        self.registry.write_text(json.dumps(document))
        self.assert_status("invalid_registry", lambda: Knowledge(self.config, "a"))
        document["repositories"][1]["aliases"] = []
        entry = self.note("project-a/index.md", "# Index")
        document["repositories"][0]["path"] = "project-a/index.md"
        self.registry.write_text(json.dumps(document))
        knowledge = Knowledge(self.config, "a")
        entry.unlink()
        self.assert_status("unsafe_path", lambda: knowledge.query("Index"))

    def test_malformed_untrusted_urls_are_data_and_dotted_wiki_paths_work(self):
        self.note("project-a/v1.2.md", "# Version")
        self.note("project-a/ref.md", "[[project-a/v1.2]]\n[[//[bad]]\n")
        result = self.knowledge.backlinks("Version")
        self.assertEqual(len(result["hits"]), 1)

    def test_repository_alias_collision_and_entry_file_scope(self):
        document = json.loads(self.registry.read_text())
        document["repositories"][1]["aliases"] = ["alpha"]
        self.registry.write_text(json.dumps(document))
        self.assert_status("ambiguous_scope", lambda: Knowledge(self.config, "a"))
        document["repositories"][1]["aliases"] = []
        self.note("project-a/index.md", "# Index")
        self.note("project-a/linked.md", "# Linked")
        document["repositories"][0]["path"] = "project-a/index.md"
        self.registry.write_text(json.dumps(document))
        knowledge = Knowledge(self.config, "a")
        self.assertEqual(knowledge.scope, (self.root / "project-a").resolve())
        self.assertEqual(knowledge.query("Linked")["status"], "ok")


if __name__ == "__main__":
    unittest.main()
