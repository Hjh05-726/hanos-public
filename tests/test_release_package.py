from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_cross_agent_package import REQUIRED_FILES, ROOT, run_installer


PUBLIC_DIRECTORIES = {
    ".github",
    ".github/ISSUE_TEMPLATE",
    ".github/workflows",
    "Templates",
    "Templates/global",
    "Templates/project",
    "adapters",
    "adapters/claude-code",
    "adapters/codex",
    "adapters/codex/agents",
    "adapters/copilot",
    "adapters/cursor",
    "adapters/gemini-cli",
    "docs",
    "docs/assets",
    "examples",
    "examples/demo-knowledge-base",
    "examples/demo-knowledge-base/.hanos",
    "examples/demo-knowledge-base/global",
    "examples/demo-knowledge-base/projects",
    "examples/demo-knowledge-base/projects/orbit-garden",
    "scripts",
    "skills",
    "skills/hanos",
    "skills/hanos/references",
    "skills/hanos/scripts",
    "tests",
    "tests/behavioral-evals",
}


PRIVATE_MARKERS = (
    ("macOS user path", ("/" + "Users" + "/").encode()),
    ("Windows user path", ("C:" + "\\" + "Users" + "\\").encode()),
    ("token assignment", ("to" + "ken" + "=").encode()),
    ("API key assignment", ("api_" + "key=").encode()),
    ("API key assignment", ("api-" + "key=").encode()),
    ("password assignment", ("pass" + "word=").encode()),
    ("secret assignment", ("se" + "cret=").encode()),
    ("client secret assignment", ("client_" + "se" + "cret=").encode()),
    ("access token assignment", ("access_" + "to" + "ken" + "=").encode()),
    ("bearer authorization", ("Authorization:" + " Bearer ").encode()),
    ("GitHub token prefix", ("ghp" + "_").encode()),
    ("GitHub token prefix", ("github_" + "pat_").encode()),
    ("private key block", ("-----BEGIN " + "PRIVATE KEY-----").encode()),
    ("private key block", ("-----BEGIN " + "OPENSSH PRIVATE KEY-----").encode()),
    ("private key block", ("-----BEGIN " + "RSA PRIVATE KEY-----").encode()),
)
PRIVATE_PATTERNS = (
    (
        "token assignment",
        re.compile(rb"\btoken[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE),
    ),
    (
        "API key assignment",
        re.compile(
            rb"\b(?:[a-z0-9]+_)*api_key[\"']?\s*[:=]\s*[\"']?\S+",
            re.IGNORECASE,
        ),
    ),
    (
        "password assignment",
        re.compile(rb"\bpassword[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE),
    ),
    (
        "secret assignment",
        re.compile(rb"\bsecret[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE),
    ),
    (
        "client secret assignment",
        re.compile(rb"\bclient_secret[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE),
    ),
    (
        "access token assignment",
        re.compile(rb"\baccess_token[\"']?\s*[:=]\s*[\"']?\S+", re.IGNORECASE),
    ),
    (
        "bearer authorization",
        re.compile(rb"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    ),
    (
        "cloud secret assignment",
        re.compile(
            rb"\b(?:aws_)?secret_access_key[\"']?\s*[:=]\s*[\"']?\S+",
            re.IGNORECASE,
        ),
    ),
    (
        "secret token prefix",
        re.compile(rb"\bsk-(?:proj-)?[a-z0-9_-]{8,}", re.IGNORECASE),
    ),
)


def git_environment(repository: Path, index_file: Path | None) -> dict[str, str]:
    environment = os.environ.copy()
    if index_file is not None:
        object_directory = index_file.with_name(f"{index_file.name}.objects")
        object_directory.mkdir(exist_ok=True)
        git_objects = subprocess.run(
            ["git", "rev-parse", "--git-path", "objects"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        alternate_objects = Path(git_objects)
        if not alternate_objects.is_absolute():
            alternate_objects = (repository / alternate_objects).resolve()
        environment["GIT_INDEX_FILE"] = str(index_file)
        environment["GIT_OBJECT_DIRECTORY"] = str(object_directory)
        environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(alternate_objects)
    return environment


def run_git(
    repository: Path,
    arguments: list[str],
    index_file: Path | None = None,
    *,
    text: bool = False,
) -> subprocess.CompletedProcess[bytes] | subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        env=git_environment(repository, index_file),
        check=False,
        capture_output=True,
        text=text,
    )


def create_release_candidate_index(repository: Path, index_file: Path) -> None:
    for arguments in (("read-tree", "HEAD"), ("add", "-A", "--", ".")):
        completed = run_git(repository, list(arguments), index_file, text=True)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr)


def git_index_paths(repository: Path, index_file: Path | None) -> set[str]:
    completed = run_git(
        repository, ["ls-files", "--cached", "-z"], index_file, text=True
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return {path for path in completed.stdout.split("\0") if path}


def git_index_entries(repository: Path, index_file: Path | None) -> bytes:
    completed = run_git(repository, ["ls-files", "--stage", "-z"], index_file)
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode(errors="replace"))
    return completed.stdout


def private_marker_names(content: bytes) -> list[str]:
    normalized = content.lower()
    names = {name for name, marker in PRIVATE_MARKERS if marker.lower() in normalized}
    names.update(name for name, pattern in PRIVATE_PATTERNS if pattern.search(content))
    return sorted(names)


def scan_git_index(repository: Path, index_file: Path | None) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in sorted(git_index_paths(repository, index_file)):
        blob = run_git(repository, ["show", f":{path}"], index_file)
        if blob.returncode != 0:
            raise AssertionError(f"cannot read index blob: {path}")
        findings.extend((path, name) for name in private_marker_names(blob.stdout))
    return findings


class ReleasePackageTests(unittest.TestCase):
    def test_default_deny_allowlist_names_every_public_file(self) -> None:
        lines = {
            line.strip()
            for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("*", lines)
        self.assertEqual(
            {line for line in lines if line.startswith("!")},
            {f"!{path}" for path in REQUIRED_FILES | {".gitignore"}}
            | {f"!{path}/" for path in PUBLIC_DIRECTORIES},
        )
        self.assertFalse(
            any("*" in line[1:] for line in lines if line.startswith("!")),
            "public allowlist must name files and directories explicitly",
        )

    def test_private_vault_examples_remain_ignored(self) -> None:
        for relative_path in (
            "HanOS Rules.md",
            ".hanos/config.yaml",
            ".hanos/repositories.yaml",
            "01_Projects/private-project/00_Overview.md",
            "06_Goals/Active/private-goal.md",
            ".obsidian/workspace.json",
        ):
            completed = subprocess.run(
                ["git", "check-ignore", "-q", relative_path],
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, relative_path)

    def test_public_worktree_is_exactly_the_release_allowlist(self) -> None:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        exposed = {
            path
            for path in completed.stdout.split("\0")
            if path and (ROOT / path).is_file()
        }
        self.assertEqual(exposed, REQUIRED_FILES | {".gitignore"})

    def test_release_candidate_index_is_exact_and_private_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate_index = Path(temporary_directory) / "release.index"
            create_release_candidate_index(ROOT, candidate_index)
            self.assertEqual(
                git_index_paths(ROOT, candidate_index), REQUIRED_FILES | {".gitignore"}
            )
            self.assertEqual(scan_git_index(ROOT, candidate_index), [])

    def test_actual_index_is_head_or_the_complete_release_candidate(self) -> None:
        cached_diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "HEAD", "--"],
            cwd=ROOT,
            check=False,
        )
        if cached_diff.returncode == 0:
            return
        self.assertEqual(cached_diff.returncode, 1)
        with tempfile.TemporaryDirectory() as temporary_directory:
            candidate_index = Path(temporary_directory) / "release.index"
            create_release_candidate_index(ROOT, candidate_index)
            self.assertEqual(
                git_index_entries(ROOT, None), git_index_entries(ROOT, candidate_index)
            )

    def test_every_release_worktree_file_is_scanned_for_private_markers(self) -> None:
        findings = []
        for relative_path in sorted(REQUIRED_FILES | {".gitignore"}):
            for marker_name in private_marker_names((ROOT / relative_path).read_bytes()):
                findings.append((relative_path, marker_name))
        self.assertEqual(findings, [])

    def test_private_marker_catalog_covers_common_secret_formats(self) -> None:
        samples = (
            ("password assignment", ("pass" + "word=example").encode()),
            ("password assignment", ("pass" + "word = example").encode()),
            ("API key assignment", ('"api_' + 'key": "example"').encode()),
            ("API key assignment", ("OPENAI_" + "API_" + "KEY = example").encode()),
            (
                "cloud secret assignment",
                ("AWS_" + "SECRET_" + "ACCESS_" + "KEY=example").encode(),
            ),
            ("secret token prefix", ("sk-" + "proj-examplevalue").encode()),
            ("bearer authorization", ("Authorization:" + " Bearer example").encode()),
            ("bearer authorization", ("Authorization:" + "Bearer example").encode()),
            ("private key block", ("-----BEGIN " + "OPENSSH PRIVATE KEY-----").encode()),
            ("private key block", ("-----BEGIN " + "RSA PRIVATE KEY-----").encode()),
        )
        for expected_marker, sample in samples:
            with self.subTest(expected_marker=expected_marker, sample=sample):
                self.assertIn(expected_marker, private_marker_names(sample))

    def test_index_scanner_reads_a_staged_blob_after_worktree_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            subprocess.run(
                ["git", "config", "user.email", "fixture@example.invalid"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "HanOS fixture"],
                cwd=repository,
                check=True,
            )
            safe = repository / "safe.txt"
            safe.write_text("public fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "safe.txt"], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)

            private = repository / "private.txt"
            private.write_text("home=/{}/alice/private\n".format("Users"), encoding="utf-8")
            subprocess.run(["git", "add", "private.txt"], cwd=repository, check=True)
            private.unlink()

            self.assertIn(
                ("private.txt", "macOS user path"), scan_git_index(repository, None)
            )

    def test_public_json_documents_are_valid(self) -> None:
        for path in (
            ROOT / "Templates/config.example.json",
            ROOT / "Templates/repositories.example.json",
            ROOT / "examples/demo-knowledge-base/.hanos/repositories.json",
            ROOT / "tests/behavioral-evals/cases.json",
            *(ROOT / "adapters").glob("*/adapter.json"),
        ):
            json.loads(path.read_text(encoding="utf-8"))

    def test_core_links_every_behavior_reference(self) -> None:
        core = (ROOT / "skills/hanos/SKILL.md").read_text(encoding="utf-8")
        references = {
            path.name for path in (ROOT / "skills/hanos/references").glob("*.md")
        }
        self.assertEqual(
            {name for name in references if f"references/{name}" in core}, references
        )

    def test_adapters_are_thin_and_do_not_fork_protocols(self) -> None:
        for path in (ROOT / "adapters").glob("*/SKILL.md.template"):
            text = path.read_text(encoding="utf-8")
            self.assertLess(len(text), 700)
            self.assertIn("{{CORE_SKILL_PATH}}", text)
            self.assertNotIn("references/", text)
        adapter_markdown = list((ROOT / "adapters").glob("*/*.template"))
        self.assertEqual(
            {path.relative_to(ROOT).as_posix() for path in adapter_markdown},
            {
                "adapters/codex/AGENTS.md.template",
                "adapters/claude-code/SKILL.md.template",
                "adapters/cursor/SKILL.md.template",
            },
        )
        codex_adapter = (ROOT / "adapters/codex/AGENTS.md.template").read_text(
            encoding="utf-8"
        )
        self.assertIn("{{CORE_SKILL_PATH}}", codex_adapter)
        self.assertIn("MUST read the exact canonical core", codex_adapter)

    def test_installer_supports_each_agent_without_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for agent in ("codex", "claude-code", "cursor", "copilot", "gemini-cli"):
                with self.subTest(agent=agent):
                    home = root / f"home-{agent}"
                    knowledge = root / f"knowledge-{agent}"
                    completed = run_installer(
                        "--agent",
                        agent,
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertIn("HANOS_INSTALL=PASS", completed.stdout)

    def test_installer_help_and_syntax(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(ROOT / "install.py"), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        for agent in ("codex", "claude-code", "cursor", "copilot", "gemini-cli", "all"):
            self.assertIn(agent, help_result.stdout)
        source = (ROOT / "install.py").read_text(encoding="utf-8")
        for forbidden in ("requests", "subprocess.Popen", "launchd", "systemd", "sqlite3"):
            self.assertNotIn(forbidden, source)

        harness = subprocess.run(
            [sys.executable, str(ROOT / "tests/behavioral-evals/run_native.py"), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(harness.returncode, 0, harness.stderr)
        self.assertIn("codex", harness.stdout)
        self.assertIn("claude-code", harness.stdout)


if __name__ == "__main__":
    unittest.main()
