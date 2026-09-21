from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "skills/hanos"

REQUIRED_FILES = {
    line.strip() for line in (ROOT / "release-files.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.startswith("#") and line.strip() != ".gitignore"
}


def directory_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(file_path.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_installer(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "install.py"), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def normalize_generation_time(rendered: str) -> str:
    payload = json.loads(re.search(
        r'<script type="application/json" id="hanos-overview-data">(.*?)</script>',
        rendered, re.DOTALL,
    ).group(1))
    timestamp = payload["generated_at"]
    normalized = rendered.replace(
        f'"generated_at":"{timestamp}"', '"generated_at":"<generation-time>"', 1,
    )
    header, body = normalized.split("</header>", 1)
    header = header.replace(f"生成于 {timestamp}", "生成于 <generation-time>", 1)
    return header + "</header>" + body


class CrossAgentPackageTests(unittest.TestCase):
    def test_generation_time_normalization_preserves_matching_note_timestamps(self) -> None:
        modified = "2026-01-01T00:00:00+00:00"
        later = "2026-01-01T00:00:01+00:00"

        def example(generated_at: str, source_time: str) -> str:
            data = json.dumps({"generated_at": generated_at, "latest_modified": source_time,
                               "notes": [{"modified": source_time}]}, separators=(",", ":"))
            return (f'<header id="page-header">生成于 {generated_at}</header>'
                    f'<script type="application/json" id="hanos-overview-data">{data}</script>')

        first = normalize_generation_time(example(modified, modified))
        second = normalize_generation_time(example(later, modified))
        self.assertEqual(first, second)
        self.assertIn(f'"modified":"{modified}"', first)
        self.assertNotEqual(second, normalize_generation_time(example(later, later)))

    def test_every_client_installs_the_same_standalone_atlas(self) -> None:
        # A new user's installed entry point must reproduce the public renderer,
        # without the developer's paths, fonts, cache, or adjacent asset files.
        for agent in ("codex", "claude-code", "cursor", "copilot", "gemini-cli"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                home, knowledge = root / "new-user", root / "知识空间"
                installed = run_installer(
                    "--agent", agent, "--home", str(home),
                    "--knowledge-home", str(knowledge), "--display-name", "Atlas", "--yes",
                )
                self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
                canonical = home / ".agents/skills/hanos"
                self.assertEqual((canonical / "template-lock.json").read_bytes(),
                                 (CORE / "template-lock.json").read_bytes())
                for name in ("generate_html.py", "star_layout.py"):
                    self.assertEqual(
                        (canonical / "scripts" / name).read_bytes(),
                        (CORE / "scripts" / name).read_bytes(),
                    )
                (knowledge / "global/星图.md").write_text(
                    "# 一位新用户的知识星图 / A different user's atlas\n\n"
                    "独立安装的笔记。[[尚未记录的灵感]] #研究\n", encoding="utf-8",
                )
                outputs = []
                complete_outputs = []
                for index, script in enumerate((CORE / "scripts/generate_html.py",
                                                canonical / "scripts/generate_html.py")):
                    output = root / f"standalone-{index}.html"
                    generated = subprocess.run(
                        [sys.executable, str(script), "--config",
                         str(home / ".config/hanos/config.json"), "--output", str(output)],
                        cwd=root, capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(generated.returncode, 0, generated.stderr)
                    verified = subprocess.run(
                        [sys.executable, str(script), "--config",
                         str(home / ".config/hanos/config.json"), "--verify-output", str(output)],
                        cwd=root, capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(verified.returncode, 0, verified.stderr)
                    self.assertIn("HANOS_HTML_VERIFY=PASS", verified.stdout)
                    rendered = output.read_text(encoding="utf-8")
                    complete_outputs.append(normalize_generation_time(rendered))
                    self.assertIn('data-theme="midnight-atlas"', rendered)
                    self.assertIn("一位新用户的知识星图", rendered)
                    self.assertNotRegex(rendered, r'<(?:script|link|img)\b[^>]*(?:src|href)=')
                    self.assertNotIn(str(ROOT), rendered)
                    # Generation timestamps may differ; compare shipped visuals
                    # and the executable UI, not wall-clock metadata.
                    outputs.append(re.findall(
                        r"<style>(.*?)</style>|<script>(.*?)</script>", rendered, re.DOTALL,
                    ))
                self.assertEqual(outputs[0], outputs[1])
                self.assertEqual(complete_outputs[0], complete_outputs[1])

    def test_installer_rejects_renderer_drift_before_creating_a_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "distribution"
            shutil.copytree(CORE, source / "skills/hanos")
            shutil.copy2(ROOT / "install.py", source / "install.py")
            shutil.copy2(ROOT / "VERSION", source / "VERSION")
            generator = source / "skills/hanos/scripts/generate_html.py"
            generator.write_text(generator.read_text().replace("--paper:#080f1c", "--paper:#ffffff"))
            home = root / "new-home"
            rejected = subprocess.run(
                [sys.executable, str(source / "install.py"), "--agent", "codex",
                 "--home", str(home), "--knowledge-home", str(root / "knowledge"),
                 "--display-name", "Atlas", "--yes"],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("TEMPLATE_PACKAGE_INVALID", rejected.stderr)
            self.assertFalse(home.exists())

    def test_html_runtime_cache_does_not_block_doctor_or_reinstall(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home, knowledge = root / "home", root / "knowledge"
            arguments = ("--agent", "codex", "--home", str(home),
                         "--knowledge-home", str(knowledge), "--display-name", "Atlas", "--yes")
            installed = run_installer(*arguments)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            canonical = home / ".agents/skills/hanos"
            # Start from the exact current installed payload, without inherited caches.
            self.assertFalse(list(canonical.rglob("*.pyc")))
            environment = os.environ.copy()
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            generated = subprocess.run(
                [sys.executable, "-X", "pycache_prefix=", str(canonical / "scripts/generate_html.py"),
                 "--config", str(home / ".config/hanos/config.json")],
                env=environment, capture_output=True, text=True, check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            # Simulate caches left by an older runtime; the locked renderer no
            # longer creates or loads a layout cache itself.
            cached = subprocess.run(
                [sys.executable, "-X", "pycache_prefix=", "-c",
                 "import py_compile, sys; py_compile.compile(sys.argv[1], doraise=True)",
                 str(canonical / "scripts/star_layout.py")],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(cached.returncode, 0, cached.stderr)
            self.assertTrue(list(canonical.rglob("*.pyc")))
            doctor = run_installer("--doctor", "--home", str(home))
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            updated = run_installer(*arguments)
            self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
            with (canonical / "SKILL.md").open("a", encoding="utf-8") as handle:
                handle.write("\nUnowned source change\n")
            rejected = run_installer(*arguments)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CORE_DRIFT", rejected.stdout)

    def test_shared_clients_receive_a_validated_config_locator(self) -> None:
        for agent in ("copilot", "gemini-cli"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                home, knowledge = root / "home", root / "knowledge"
                installed = run_installer(
                    "--agent", agent, "--home", str(home), "--knowledge-home", str(knowledge),
                    "--display-name", "Atlas", "--yes",
                )
                self.assertEqual(installed.returncode, 0, installed.stderr)
                locator_path = home / ".agents/skills/hanos/installation.json"
                self.assertTrue(locator_path.is_file(), "shared core needs a config locator")
                locator = json.loads(locator_path.read_text(encoding="utf-8"))
                self.assertEqual(locator["config_path"], str(home / ".config/hanos/config.json"))
                self.assertEqual(locator["version"], 1)
                doctor = run_installer("--doctor", "--home", str(home))
                self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
                locator_path.unlink()
                invalid = run_installer("--doctor", "--home", str(home))
                self.assertNotEqual(invalid.returncode, 0)
                self.assertIn("INSTALLATION_LOCATOR", invalid.stdout)

    def test_doctor_rejects_config_name_out_of_sync_with_recorded_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            installed = run_installer("--agent", "codex", "--home", str(home),
                                      "--knowledge-home", str(root / "knowledge"),
                                      "--display-name", "Atlas", "--yes")
            self.assertEqual(installed.returncode, 0, installed.stderr)
            config_path = home / ".config/hanos/config.json"
            config = json.loads(config_path.read_text())
            config["identity"]["display_name"] = "Different name"
            config_path.write_text(json.dumps(config))
            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("CODEX_ADAPTER", doctor.stdout)

    def test_known_legacy_install_upgrades_without_losing_source_drift_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            arguments = ("--agent", "codex", "--home", str(home),
                         "--knowledge-home", str(root / "knowledge"), "--display-name", "Atlas", "--yes")
            initial = run_installer(*arguments)
            self.assertEqual(initial.returncode, 0, initial.stderr)
            canonical = home / ".agents/skills/hanos"
            (canonical / "installation.json").unlink()
            cache = canonical / "scripts/__pycache__/legacy.pyc"
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(b"legacy install-time bytecode")
            marker_path = canonical / ".hanos-install.json"
            marker = json.loads(marker_path.read_text())
            marker.pop("payload_hash_version", None)
            marker_path.unlink()
            marker["payload_hash"] = directory_digest(canonical)
            marker_path.write_text(json.dumps(marker))
            manifest_path = home / ".config/hanos/install-manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for field in ("installation_locator_version", "codex_adapter_hash", "codex_adapter_display_name"):
                manifest.pop(field, None)
            manifest_path.write_text(json.dumps(manifest))
            migrated = run_installer(*arguments)
            self.assertEqual(migrated.returncode, 0, migrated.stdout + migrated.stderr)
            self.assertTrue((canonical / "installation.json").is_file())
            self.assertFalse(list(canonical.rglob("*.pyc")))
            with (canonical / "SKILL.md").open("a") as handle:
                handle.write("\nUnowned change\n")
            rejected = run_installer(*arguments)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CORE_DRIFT", rejected.stdout)

    def test_codex_template_upgrade_preserves_owner_rules_and_rejects_local_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            release = root / "release"
            for relative in REQUIRED_FILES:
                target = release / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            home, knowledge = root / "home", root / "knowledge"
            command = [sys.executable, str(release / "install.py"), "--agent", "codex",
                       "--home", str(home), "--knowledge-home", str(knowledge),
                       "--display-name", "Atlas", "--yes"]
            first = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            instructions = home / ".codex/AGENTS.md"
            owner_prefix, owner_suffix = "# Owner instructions\nKeep these.\n\n", "\nOwner footer.\n"
            instructions.write_text(owner_prefix + instructions.read_text() + owner_suffix)
            template = release / "adapters/codex/AGENTS.md.template"
            template.write_text(template.read_text().replace(
                "<!-- HANOS_ADAPTER:END -->",
                "- Updated public adapter guidance.\n<!-- HANOS_ADAPTER:END -->",
            ))
            upgraded = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(upgraded.returncode, 0, upgraded.stdout + upgraded.stderr)
            updated = instructions.read_text()
            self.assertTrue(updated.startswith(owner_prefix))
            self.assertTrue(updated.endswith(owner_suffix))
            self.assertIn("Updated public adapter guidance.", updated)
            instructions.write_text(updated.replace("Updated public adapter guidance.", "Local override."))
            before_rejection = directory_digest(home)
            rejected = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("CODEX_ADAPTER_DRIFT", rejected.stdout)
            self.assertEqual(directory_digest(home), before_rejection)

    def test_failed_rollback_preserves_owner_file_and_recoverable_backup(self) -> None:
        specification = importlib.util.spec_from_file_location("hanos_double_failure", ROOT / "install.py")
        installer = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            arguments = argparse.Namespace(agent="codex", home=root / "home",
                                           knowledge_home=root / "knowledge", display_name="Atlas", yes=True)
            with contextlib.redirect_stdout(io.StringIO()):
                installer.install(arguments)
            instructions = arguments.home / ".codex/AGENTS.md"
            original = "# Owner rules\nPreserve this.\n\n" + instructions.read_text()
            instructions.write_text(original)
            snapshots = []
            real_snapshot, real_atomic, real_copy = (
                installer.snapshot_install_artifacts, installer.atomic_write, installer.shutil.copy2,
            )

            def snapshot(paths):
                result = real_snapshot(paths)
                snapshots.append(result)
                self.addCleanup(shutil.rmtree, result[0], True)
                return result

            def fail_manifest(path, text):
                if path == arguments.home / ".config/hanos/install-manifest.json":
                    raise OSError("injected manifest write failure")
                return real_atomic(path, text)

            def fail_restore(source, destination, *args, **kwargs):
                if snapshots and any(path == instructions and backup == Path(source)
                                     for path, _kind, backup in snapshots[0][1]):
                    raise PermissionError("injected owner restore failure")
                return real_copy(source, destination, *args, **kwargs)

            arguments.display_name = "Updated"
            with mock.patch.object(installer, "snapshot_install_artifacts", side_effect=snapshot), \
                    mock.patch.object(installer, "atomic_write", side_effect=fail_manifest), \
                    mock.patch.object(installer.shutil, "copy2", side_effect=fail_restore), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(installer.InstallerError) as failed:
                    installer.install(arguments)
            backup_root, entries = snapshots[0]
            self.assertTrue(instructions.is_file(), "failed restore must not first delete owner rules")
            self.assertIn("# Owner rules", instructions.read_text())
            self.assertTrue(backup_root.is_dir(), "retain backups after incomplete rollback")
            self.assertIn(str(backup_root), str(failed.exception))
            backup = next(backup for path, _kind, backup in entries if path == instructions)
            self.assertEqual(backup.read_text(), original)
            recovery = json.loads((backup_root / "restore-manifest.json").read_text())
            self.assertTrue(any(item["path"] == str(instructions) for item in recovery["artifacts"]))

    def test_required_public_files_exist(self) -> None:
        missing = sorted(path for path in REQUIRED_FILES if not (ROOT / path).is_file())
        self.assertEqual(missing, [])

    def test_noncommercial_license_travels_with_installed_core(self) -> None:
        license_bytes = (ROOT / "LICENSE").read_bytes()
        self.assertIn(b"PolyForm Noncommercial License 1.0.0", license_bytes)
        self.assertEqual((CORE / "LICENSE").read_bytes(), license_bytes)
        self.assertIn("license: PolyForm-Noncommercial-1.0.0",
                      (CORE / "SKILL.md").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_installer("--agent", "all", "--home", str(root / "home"),
                                   "--knowledge-home", str(root / "knowledge"),
                                   "--display-name", "Atlas", "--yes")
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = root / "home/.agents/skills/hanos/LICENSE"
            self.assertEqual(installed.read_bytes(), license_bytes)

    def test_core_is_the_only_authoritative_hanos_skill(self) -> None:
        self.assertTrue((CORE / "SKILL.md").is_file())
        self.assertFalse((ROOT / "skill/hanos/SKILL.md").exists())
        self.assertFalse((CORE / "agents").exists())

    def test_core_frontmatter_is_standard_and_agent_neutral(self) -> None:
        text = (CORE / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---\n", 2)[1]
        keys = {
            line.partition(":")[0].strip()
            for line in frontmatter.splitlines()
            if line and not line.startswith(" ") and ":" in line
        }
        self.assertEqual(keys, {"name", "description", "license", "compatibility"})
        self.assertIn("name: hanos", frontmatter)

        banned = (
            "Codex",
            "~/.codex",
            "AGENTS.md",
            "agents/openai.yaml",
            "/" + "Users/",
        )
        for marker in banned:
            self.assertNotIn(marker, text)

        for required_boundary in (
            "**Explicit invocation**",
            "**Adaptive invocation**",
            "**Explicit write**",
            "**Automatic capture**",
            "Explicit confirmation remains required",
            "knowledge home",
            "python3 install.py --doctor",
            "--display-name",
        ):
            self.assertIn(required_boundary, text)

        diary_reference = (CORE / "references/cyber-diary.md").read_text(encoding="utf-8")
        for diary_boundary in (
            "Cyber-diary mode",
            "原始日记是事实来源",
            "分析与低风险知识沉淀可以自动完成",
            "不做心理疾病诊断",
        ):
            self.assertIn(diary_boundary, diary_reference)

        repository_protocol = (CORE / "references/repository-protocol.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("directory or an entry file", repository_protocol)
        self.assertIn("Report the repository owner for every write", repository_protocol)

    def test_every_adapter_declares_capabilities_without_copying_core(self) -> None:
        expected = {"codex", "claude-code", "cursor", "copilot", "gemini-cli"}
        found = {path.parent.name for path in (ROOT / "adapters").glob("*/adapter.json")}
        self.assertEqual(found, expected)
        for adapter_id in expected:
            manifest = json.loads(
                (ROOT / f"adapters/{adapter_id}/adapter.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["id"], adapter_id)
            self.assertIn(manifest["native_runtime_test"], {"PASS", "NOT_TESTED"})
            self.assertFalse((ROOT / f"adapters/{adapter_id}/references").exists())

        codex_metadata = (ROOT / "adapters/codex/agents/openai.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("allow_implicit_invocation: true", codex_metadata)
        for wrapper in (
            ROOT / "adapters/claude-code/SKILL.md.template",
            ROOT / "adapters/cursor/SKILL.md.template",
        ):
            wrapper_text = wrapper.read_text(encoding="utf-8")
            self.assertNotIn("disable-model-invocation: true", wrapper_text)
            self.assertIn("{{CORE_SKILL_PATH}}", wrapper_text)
            self.assertIn("{{CONFIG_PATH}}", wrapper_text)
            self.assertIn("adaptive", wrapper_text)

    def test_public_package_contains_no_private_markers(self) -> None:
        private_markers = (
            "/" + "Users/",
            "C:" + "\\Users\\",
            "token" + "=",
            "api_key" + "=",
        )
        public_files = [
            ROOT / relative_path
            for relative_path in REQUIRED_FILES
        ]
        for path in public_files:
            content = path.read_bytes()
            for marker in private_markers:
                self.assertNotIn(marker.encode(), content, f"private marker in {path.relative_to(ROOT)}")

    def test_installer_is_idempotent_and_doctor_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge_home = temporary / "knowledge"
            arguments = (
                "--agent",
                "all",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge_home),
                "--display-name",
                "Atlas",
                "--yes",
            )

            first = run_installer(*arguments)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("HANOS_INSTALL=PASS", first.stdout)
            canonical = home / ".agents/skills/hanos"
            config = home / ".config/hanos/config.json"
            registry = knowledge_home / ".hanos/repositories.json"
            self.assertTrue((canonical / "SKILL.md").is_file())
            self.assertTrue((canonical / "agents/openai.yaml").is_file())
            self.assertTrue((home / ".claude/skills/hanos/SKILL.md").is_file())
            self.assertTrue((home / ".cursor/skills/hanos/SKILL.md").is_file())
            self.assertTrue(config.is_file())
            self.assertTrue(registry.is_file())
            self.assertIn(
                str(canonical / "SKILL.md"),
                (home / ".codex/AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(json.loads(config.read_text())["identity"]["display_name"], "Atlas")
            self.assertEqual(
                Path(json.loads(config.read_text())["knowledge_home"]),
                knowledge_home.resolve(),
            )

            first_digest = directory_digest(temporary)
            second = run_installer(*arguments)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(directory_digest(temporary), first_digest)

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            self.assertIn("HANOS_DOCTOR=PASS", doctor.stdout)

            with (canonical / "SKILL.md").open("a", encoding="utf-8") as handle:
                handle.write("\nlocal drift\n")
            drift = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(drift.returncode, 0)
            self.assertIn("CORE_DRIFT", drift.stdout)

    def test_onboarding_name_change_preserves_knowledge_and_installed_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home, knowledge_home = temporary / "home", temporary / "knowledge"
            for agent in ("codex", "cursor"):
                installed = run_installer(
                    "--agent", agent, "--home", str(home),
                    "--knowledge-home", str(knowledge_home),
                    "--display-name", "Atlas", "--yes",
                )
                self.assertEqual(installed.returncode, 0, installed.stderr)

            entry = knowledge_home / "global/README.md"
            with entry.open("a", encoding="utf-8") as handle:
                handle.write("\n## 关于你\n\n称呼：小舟。\n\n## 开始使用\n\n进行中；称呼已回答。\n")
            knowledge_before = directory_digest(knowledge_home)
            manifest_path = home / ".config/hanos/install-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            installer = Path(manifest["source_root"]) / "install.py"
            self.assertEqual(installer, ROOT / "install.py")
            renamed = subprocess.run(
                [sys.executable, str(installer), "--agent", manifest["agents"][0],
                 "--home", str(home), "--knowledge-home", str(knowledge_home),
                 "--display-name", "回声", "--yes"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(renamed.returncode, 0, renamed.stderr)
            self.assertIn("HANOS_DOCTOR=PASS", renamed.stdout)
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            config = json.loads((home / ".config/hanos/config.json").read_text(encoding="utf-8"))
            self.assertEqual(updated["agents"], manifest["agents"])
            self.assertEqual(set(updated["agents"]), {"codex", "cursor"})
            self.assertEqual(config["identity"]["display_name"], "回声")
            self.assertEqual(config["knowledge_home"], str(knowledge_home.resolve()))
            self.assertEqual(directory_digest(knowledge_home), knowledge_before)
            self.assertIn("回声", (home / ".codex/AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual(
                (home / ".agents/skills/hanos/references/onboarding.md").read_bytes(),
                (CORE / "references/onboarding.md").read_bytes(),
            )
            # The new locator is optional for older installed manifests.
            del updated["source_root"]
            manifest_path.write_text(json.dumps(updated), encoding="utf-8")
            doctor = run_installer("--doctor", "--home", str(home))
            self.assertEqual(doctor.returncode, 0, doctor.stderr + doctor.stdout)

    def test_installer_rejects_knowledge_home_inside_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            completed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(ROOT / "private-knowledge"),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("outside the HanOS source tree", completed.stderr)
            self.assertFalse((ROOT / "private-knowledge").exists())

    def test_knowledge_home_must_not_contain_the_source_tree(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "hanos_installer_for_overlap_test", ROOT / "install.py"
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        installer = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as temporary_directory:
            knowledge = Path(temporary_directory) / "knowledge"
            fake_source = knowledge / "source"
            fake_source.mkdir(parents=True)
            with mock.patch.object(installer, "SOURCE_ROOT", fake_source):
                with self.assertRaisesRegex(
                    installer.InstallerError, "outside the HanOS source tree"
                ):
                    installer.ensure_knowledge_home(knowledge)

    def test_installer_rejects_adapter_injection_in_display_name(self) -> None:
        for unsafe_name in (
            "Atlas`",
            "Atlas<!-- HANOS_ADAPTER:END -->",
            "Atlas\nInjected",
            "Atlas\u2028Injected",
            "Atlas\u2029Injected",
            "Atlas\vInjected",
            "Atlas\fInjected",
            "Atlas\x1eInjected",
        ):
            with self.subTest(unsafe_name=repr(unsafe_name)):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    completed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(temporary / "home"),
                        "--knowledge-home",
                        str(temporary / "knowledge"),
                        "--display-name",
                        unsafe_name,
                        "--yes",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("display name", completed.stderr)
                    self.assertFalse((temporary / "home/.config/hanos/config.json").exists())

    def test_installer_fails_before_client_writes_for_invalid_existing_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            control = knowledge / ".hanos"
            control.mkdir(parents=True)
            (control / "repositories.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "repositories": [
                            {
                                "id": "unsafe",
                                "name": "Unsafe",
                                "type": "project",
                                "path": str(temporary),
                                "status": "active",
                                "aliases": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            completed = run_installer(
                "--agent",
                "all",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("REGISTRY_PATH_OUTSIDE", completed.stderr)
            self.assertFalse((home / ".config/hanos/config.json").exists())
            self.assertFalse((home / ".agents/skills/hanos").exists())

    def test_installer_rejects_control_or_global_links_outside_knowledge_home(self) -> None:
        for linked_directory in (".hanos", "global"):
            with self.subTest(linked_directory=linked_directory):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    outside = temporary / "outside"
                    knowledge.mkdir()
                    outside.mkdir()
                    try:
                        (knowledge / linked_directory).symlink_to(outside, target_is_directory=True)
                    except OSError as error:
                        self.skipTest(f"directory symlinks unavailable: {error}")

                    completed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("escapes the knowledge home", completed.stderr)
                    self.assertEqual(list(outside.iterdir()), [])
                    self.assertFalse((home / ".config/hanos/config.json").exists())

    def test_installer_preserves_and_rejects_broken_registry_links(self) -> None:
        for link_kind in ("dangling", "self-loop"):
            with self.subTest(link_kind=link_kind):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    control = knowledge / ".hanos"
                    control.mkdir(parents=True)
                    registry = control / "repositories.json"
                    link_target = "missing.json" if link_kind == "dangling" else registry.name
                    registry.symlink_to(link_target)

                    completed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertTrue(registry.is_symlink())
                    self.assertEqual(os.readlink(registry), link_target)
                    self.assertFalse((home / ".config/hanos/config.json").exists())

    def test_installer_structures_symbolic_link_loops(self) -> None:
        for loop_kind in ("config", "agents", "knowledge-control"):
            with self.subTest(loop_kind=loop_kind):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    home.mkdir()
                    if loop_kind == "config":
                        (home / ".config").symlink_to(".config", target_is_directory=True)
                    elif loop_kind == "agents":
                        (home / ".agents").symlink_to(".agents", target_is_directory=True)
                    else:
                        knowledge.mkdir()
                        (knowledge / ".hanos").symlink_to(".hanos", target_is_directory=True)

                    completed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn("Traceback", completed.stderr)
                    if loop_kind in ("config", "agents"):
                        self.assertFalse(knowledge.exists(), "preflight must reject before knowledge writes")
                        self.assertFalse((home / ".config/hanos/config.json").exists())
                    self.assertTrue(
                        (home / f".{loop_kind.split('-')[0]}").is_symlink()
                        if loop_kind != "knowledge-control"
                        else (knowledge / ".hanos").is_symlink()
                    )

    @unittest.skipUnless(os.name == "posix", "requires POSIX directory permissions")
    def test_installer_rejects_inaccessible_parent_before_writes(self) -> None:
        for directory in (".config", ".agents"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home, knowledge = root / "home", root / "knowledge"
                blocked = home / directory
                blocked.mkdir(parents=True)
                blocked.chmod(0)
                try:
                    if os.access(blocked, os.X_OK):
                        self.skipTest("current user bypasses directory permissions")
                    completed = run_installer(
                        "--agent", "codex", "--home", str(home),
                        "--knowledge-home", str(knowledge), "--display-name", "Atlas", "--yes",
                    )
                    self.assertEqual(completed.returncode, 2)
                    self.assertNotIn("Traceback", completed.stderr)
                    self.assertFalse(knowledge.exists())
                finally:
                    blocked.chmod(0o700)
                self.assertFalse((home / ".config/hanos/config.json").exists())

    def test_installer_structures_unknown_user_path_expansion(self) -> None:
        unknown = "~hanos-user-that-does-not-exist-92741/path"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            cases = (
                ("doctor-home", ("--doctor", "--home", unknown)),
                (
                    "install-home",
                    (
                        "--agent",
                        "codex",
                        "--home",
                        unknown,
                        "--knowledge-home",
                        str(temporary / "knowledge-a"),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    ),
                ),
                (
                    "knowledge-home",
                    (
                        "--agent",
                        "codex",
                        "--home",
                        str(temporary / "home-b"),
                        "--knowledge-home",
                        unknown,
                        "--display-name",
                        "Atlas",
                        "--yes",
                    ),
                ),
            )
            for label, arguments in cases:
                with self.subTest(label=label):
                    completed = run_installer(*arguments)
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertNotIn("Traceback", completed.stderr)
                    if label == "doctor-home":
                        self.assertIn("HANOS_DOCTOR=FAIL", completed.stdout)

    def test_multi_client_conflict_is_preflighted_before_any_install_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            unmanaged = home / ".claude/skills/hanos"
            unmanaged.mkdir(parents=True)
            (unmanaged / "SKILL.md").write_text("user-owned", encoding="utf-8")

            completed = run_installer(
                "--agent",
                "all",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("unmanaged directory", completed.stderr)
            self.assertEqual((unmanaged / "SKILL.md").read_text(), "user-owned")
            self.assertFalse((home / ".config/hanos/config.json").exists())
            self.assertFalse((home / ".agents/skills/hanos").exists())
            self.assertFalse(knowledge.exists())

    def test_reinstall_refuses_an_unowned_manifest_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            config = home / ".config/hanos/config.json"
            manifest = home / ".config/hanos/install-manifest.json"
            config.parent.mkdir(parents=True)
            original_config = '{"private":"user-owned"}\n'
            original_manifest = '{"version":1,"managed_by":"someone-else","agents":[]}\n'
            config.write_text(original_config, encoding="utf-8")
            manifest.write_text(original_manifest, encoding="utf-8")

            completed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to replace invalid existing installation", completed.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), original_config)
            self.assertEqual(manifest.read_text(encoding="utf-8"), original_manifest)
            self.assertFalse((home / ".agents/skills/hanos").exists())
            self.assertFalse(knowledge.exists())

    def test_first_install_refuses_an_unowned_codex_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            instructions = home / ".codex/AGENTS.md"
            instructions.parent.mkdir(parents=True)
            original = (
                "user instructions\n"
                "<!-- HANOS_ADAPTER:BEGIN -->\n"
                "unowned HanOS block\n"
                "<!-- HANOS_ADAPTER:END -->\n"
            )
            instructions.write_text(original, encoding="utf-8")

            completed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to replace invalid existing installation", completed.stderr)
            self.assertEqual(instructions.read_text(encoding="utf-8"), original)
            self.assertFalse((home / ".config/hanos/config.json").exists())
            self.assertFalse((home / ".agents/skills/hanos").exists())
            self.assertFalse(knowledge.exists())

    def test_installer_and_doctor_reject_authority_links_outside_knowledge_home(self) -> None:
        for authority_path in ("00_Agent_Entry.md", "HanOS Rules.md", "global/README.md"):
            with self.subTest(authority_path=authority_path, phase="install"):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    outside = temporary / "outside.md"
                    knowledge.mkdir()
                    outside.write_text("external instructions", encoding="utf-8")
                    authority = knowledge / authority_path
                    authority.parent.mkdir(parents=True, exist_ok=True)
                    authority.symlink_to(outside)

                    completed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("KNOWLEDGE_PATH_OUTSIDE", completed.stderr)
                    self.assertEqual(outside.read_text(encoding="utf-8"), "external instructions")
                    self.assertFalse((home / ".config/hanos/config.json").exists())

            with self.subTest(authority_path=authority_path, phase="doctor"):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    installed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertEqual(installed.returncode, 0, installed.stderr)
                    authority = knowledge / authority_path
                    outside = temporary / "outside.md"
                    outside.write_text("external instructions", encoding="utf-8")
                    authority.unlink()
                    authority.symlink_to(outside)

                    doctor = run_installer("--doctor", "--home", str(home))
                    self.assertNotEqual(doctor.returncode, 0)
                    self.assertIn("KNOWLEDGE_PATH_OUTSIDE", doctor.stdout)
                    self.assertIn("HANOS_DOCTOR=FAIL", doctor.stdout)

    def test_doctor_structures_invalid_utf8_at_every_read_boundary(self) -> None:
        for target_name in ("config", "manifest", "core-marker", "codex-adapter", "registry"):
            with self.subTest(target_name=target_name):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    installed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertEqual(installed.returncode, 0, installed.stderr)
                    targets = {
                        "config": home / ".config/hanos/config.json",
                        "manifest": home / ".config/hanos/install-manifest.json",
                        "core-marker": home / ".agents/skills/hanos/.hanos-install.json",
                        "codex-adapter": home / ".codex/AGENTS.md",
                        "registry": knowledge / ".hanos/repositories.json",
                    }
                    targets[target_name].write_bytes(b"\xff")

                    doctor = run_installer("--doctor", "--home", str(home))
                    self.assertNotEqual(doctor.returncode, 0)
                    self.assertIn("HANOS_DOCTOR=FAIL", doctor.stdout)
                    self.assertNotIn("Traceback", doctor.stderr)

    def test_doctor_structures_a_nul_knowledge_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            installed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(temporary / "knowledge"),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            config_path = home / ".config/hanos/config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["knowledge_home"] = "/bad\0path"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("CONFIG_KNOWLEDGE_HOME_INVALID", doctor.stdout)
            self.assertIn("HANOS_DOCTOR=FAIL", doctor.stdout)
            self.assertNotIn("Traceback", doctor.stderr)

    def test_reinstall_cleans_a_previous_directory_after_cleanup_failure(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "hanos_installer_for_backup_cleanup_test", ROOT / "install.py"
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        installer = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(installer)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            initial = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(initial.returncode, 0, initial.stderr)
            original_digest = directory_digest(home / ".agents/skills/hanos")
            arguments = argparse.Namespace(
                agent="all",
                doctor=False,
                home=home,
                knowledge_home=knowledge,
                display_name="Atlas",
                yes=True,
            )
            real_rmtree = installer.shutil.rmtree
            failure_injected = False

            def fail_first_previous(path: object, *args: object, **kwargs: object) -> None:
                nonlocal failure_injected
                candidate = Path(path)
                if candidate.name == ".hanos.previous" and not failure_injected:
                    failure_injected = True
                    raise OSError("injected previous cleanup failure")
                real_rmtree(candidate, *args, **kwargs)

            with mock.patch.object(installer.shutil, "rmtree", side_effect=fail_first_previous):
                with self.assertRaises(OSError):
                    installer.install(arguments)

            self.assertTrue(failure_injected)
            self.assertFalse((home / ".agents/skills/.hanos.previous").exists())
            self.assertEqual(directory_digest(home / ".agents/skills/hanos"), original_digest)
            self.assertEqual(installer.doctor(home), 0)

    def test_install_rolls_back_after_a_late_adapter_write_failure(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "hanos_installer_for_rollback_test", ROOT / "install.py"
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        installer = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(installer)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            arguments = argparse.Namespace(
                agent="all",
                doctor=False,
                home=home,
                knowledge_home=knowledge,
                display_name="Atlas",
                yes=True,
            )
            real_install = installer.install_managed_directory
            call_count = 0

            def fail_second_directory(*args: object, **kwargs: object) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    raise OSError("injected late adapter failure")
                real_install(*args, **kwargs)

            with mock.patch.object(
                installer, "install_managed_directory", side_effect=fail_second_directory
            ):
                with self.assertRaises(OSError):
                    installer.install(arguments)

            self.assertFalse((home / ".config/hanos/config.json").exists())
            self.assertFalse((home / ".config/hanos/install-manifest.json").exists())
            self.assertFalse((home / ".agents/skills/hanos").exists())
            self.assertFalse((home / ".claude/skills/hanos").exists())
            self.assertFalse(knowledge.exists())

    def test_doctor_rejects_unsupported_config_and_registry_schema(self) -> None:
        cases = (
            ("config.json", "version", 999, "CONFIG_VERSION_UNSUPPORTED"),
            ("config.json", "invocation", {}, "CONFIG_INVOCATION_INVALID"),
            ("repositories.json", "version", 999, "REGISTRY_VERSION_UNSUPPORTED"),
            ("repositories.json", "type", "unsupported", "REGISTRY_TYPE_UNSUPPORTED"),
        )
        for file_name, field, value, expected_error in cases:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    temporary = Path(temporary_directory)
                    home = temporary / "home"
                    knowledge = temporary / "knowledge"
                    installed = run_installer(
                        "--agent",
                        "codex",
                        "--home",
                        str(home),
                        "--knowledge-home",
                        str(knowledge),
                        "--display-name",
                        "Atlas",
                        "--yes",
                    )
                    self.assertEqual(installed.returncode, 0, installed.stderr)
                    path = (
                        home / ".config/hanos/config.json"
                        if file_name == "config.json"
                        else knowledge / ".hanos/repositories.json"
                    )
                    document = json.loads(path.read_text(encoding="utf-8"))
                    if field == "type":
                        document["repositories"][0][field] = value
                    else:
                        document[field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")

                    doctor = run_installer("--doctor", "--home", str(home))
                    self.assertNotEqual(doctor.returncode, 0)
                    self.assertIn(expected_error, doctor.stdout)

    def test_doctor_requires_the_declared_codex_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            installed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(temporary / "knowledge"),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            (home / ".codex/AGENTS.md").unlink()

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("CODEX_ADAPTER_MISSING", doctor.stdout)

    def test_doctor_rejects_installed_artifacts_resolving_outside_home(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            installed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(temporary / "knowledge"),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            outside_agents = temporary / "outside-agents"
            os.replace(home / ".agents", outside_agents)
            (home / ".agents").symlink_to(outside_agents, target_is_directory=True)

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("INSTALL_PATH_OUTSIDE:canonical-core", doctor.stdout)

    def test_doctor_rejects_duplicate_active_repository_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            installed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            registry_path = knowledge / ".hanos/repositories.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["repositories"].append(dict(registry["repositories"][0]))
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("REGISTRY_ID_DUPLICATE:global", doctor.stdout)

    def test_doctor_reports_malformed_registry_path_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            home = temporary / "home"
            knowledge = temporary / "knowledge"
            installed = run_installer(
                "--agent",
                "codex",
                "--home",
                str(home),
                "--knowledge-home",
                str(knowledge),
                "--display-name",
                "Atlas",
                "--yes",
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            registry_path = knowledge / ".hanos/repositories.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["repositories"][0]["path"] = "invalid\x00path"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            doctor = run_installer("--doctor", "--home", str(home))
            self.assertNotEqual(doctor.returncode, 0)
            self.assertIn("REGISTRY_PATH_INVALID:global", doctor.stdout)
            self.assertIn("HANOS_DOCTOR=FAIL", doctor.stdout)
            self.assertNotIn("Traceback", doctor.stderr)

    def test_native_eval_requires_structured_evidence_and_a_core_read_event(self) -> None:
        native = runpy.run_path(str(ROOT / "tests/behavioral-evals/run_native.py"))
        self.assertNotIn("const", json.dumps(native["RESULT_SCHEMA"]))
        expected_core = "/tmp/eval/.agents/skills/hanos/SKILL.md"
        keyword_only = "Orbit Garden is not CONFIRMED_LOCAL; production may be NOT_PROVEN."
        free_text_trace = json.dumps(
            {"type": "item.completed", "item": {"type": "reasoning", "text": expected_core}}
        )
        with self.assertRaises(RuntimeError):
            native["validate_result"](keyword_only)
        with self.assertRaises(RuntimeError):
            native["validate_codex_core_read"](free_text_trace, expected_core)

        valid_trace = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": f"sed -n '1,120p' {expected_core}",
                    "exit_code": 0,
                    "aggregated_output": (CORE / "SKILL.md").read_text(encoding="utf-8"),
                },
            }
        )
        native["validate_codex_core_read"](valid_trace, expected_core)
        relative_trace = valid_trace.replace(
            expected_core, ".agents/skills/hanos/SKILL.md"
        )
        native["validate_codex_core_read"](relative_trace, expected_core)
        with self.assertRaises(RuntimeError):
            native["validate_codex_evidence_reads"](relative_trace, Path("/tmp/eval"))
        registry_trace = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "sed -n '1,200p' knowledge/.hanos/repositories.json",
                    "exit_code": 0,
                    "aggregated_output": (
                        '"id": "orbit-garden"\n'
                        '"path": "/tmp/eval/knowledge/projects/orbit-garden"\n'
                    ),
                },
            }
        )
        authority_trace = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": (
                        "sed -n '1,200p' "
                        "knowledge/projects/orbit-garden/00_Overview.md"
                    ),
                    "exit_code": 0,
                    "aggregated_output": (
                        "Status: `CONFIRMED_LOCAL`\n"
                        "Deployment and current production health are `NOT_PROVEN`.\n"
                    ),
                },
            }
        )
        native["validate_codex_evidence_reads"](
            "\n".join((relative_trace, registry_trace, authority_trace)),
            Path("/tmp/eval"),
        )
        registry_nonce = "registry-nonce-not-in-schema"
        authority_nonce = "authority-nonce-not-in-schema"
        registry_event = json.loads(registry_trace)
        registry_event["item"]["aggregated_output"] += registry_nonce
        authority_event = json.loads(authority_trace)
        authority_event["item"]["aggregated_output"] += authority_nonce
        native["validate_codex_evidence_reads"](
            "\n".join(
                (
                    relative_trace,
                    json.dumps(registry_event),
                    json.dumps(authority_event),
                )
            ),
            Path("/tmp/eval"),
            registry_nonce,
            authority_nonce,
        )
        joined_registry_event = json.loads(json.dumps(registry_event))
        joined_registry_event["item"]["command"] = (
            "python3 -c 'from pathlib import Path; "
            'p=Path("knowledge").resolve(); '
            'print((p/".hanos/repositories.json").read_text())' + "'"
        )
        joined_trace = "\n".join(
            (relative_trace, json.dumps(joined_registry_event), json.dumps(authority_event))
        )
        native["validate_codex_evidence_reads"](
            joined_trace, Path("/tmp/eval"), registry_nonce, authority_nonce
        )
        joined_authority_event = json.loads(json.dumps(authority_event))
        joined_authority_event["item"]["command"] = (
            'python3 -c \'from pathlib import Path; p=Path("knowledge"); '
            'print((p/"projects/orbit-garden/00_Overview.md").read_text())\''
        )
        joined_both = "\n".join((relative_trace, json.dumps(joined_registry_event),
                                  json.dumps(joined_authority_event)))
        native["validate_codex_evidence_reads"](
            joined_both, Path("/tmp/eval"), registry_nonce, authority_nonce
        )
        for invalid_authority_nonce in (None, "wrong-authority-nonce"):
            with self.assertRaises(RuntimeError):
                native["validate_codex_evidence_reads"](
                    joined_both, Path("/tmp/eval"), registry_nonce, invalid_authority_nonce
                )
        for missing_or_wrong_nonce in (None, "wrong-registry-nonce"):
            with self.subTest(registry_nonce=missing_or_wrong_nonce):
                with self.assertRaises(RuntimeError):
                    native["validate_codex_evidence_reads"](
                        joined_trace, Path("/tmp/eval"), missing_or_wrong_nonce, authority_nonce
                    )
        native["validate_result"](
            json.dumps(
                {
                    "project_name": "Orbit Garden",
                    "local_status": "CONFIRMED_LOCAL",
                    "production_status": "NOT_PROVEN",
                    "evidence_path": "projects/orbit-garden/00_Overview.md",
                }
            )
        )
        native["validate_result"](
            json.dumps(
                {
                    "project_name": "Orbit Garden",
                    "local_status": "CONFIRMED_LOCAL",
                    "production_status": "NOT_PROVEN",
                    "evidence_path": "projects/orbit-garden/00_Overview.md",
                    "registry_nonce": registry_nonce,
                    "authority_nonce": authority_nonce,
                }
            ),
            {
                "project_name": "Orbit Garden",
                "local_status": "CONFIRMED_LOCAL",
                "production_status": "NOT_PROVEN",
                "evidence_path": "projects/orbit-garden/00_Overview.md",
                "registry_nonce": registry_nonce,
                "authority_nonce": authority_nonce,
            },
        )

    def test_native_eval_refuses_nonempty_workspace_and_escapes_json_paths(self) -> None:
        native = runpy.run_path(str(ROOT / "tests/behavioral-evals/run_native.py"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "user-owned.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                native["require_empty_workspace"](workspace)
            self.assertEqual((workspace / "user-owned.txt").read_text(), "keep")

        for demo_root in (
            "C:" + "\\Users\\Atlas\\demo",
            '/tmp/demo"quoted',
        ):
            with self.subTest(demo_root=demo_root):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    registry = Path(temporary_directory) / "repositories.json"
                    registry.write_text(
                        json.dumps(
                            {
                                "version": 1,
                                "repositories": [
                                    {"path": "{{DEMO_ROOT}}/projects/orbit-garden"}
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    native["materialize_demo_registry"](registry, demo_root)
                    loaded = json.loads(registry.read_text(encoding="utf-8"))
                    self.assertEqual(
                        loaded["repositories"][0]["path"],
                        f"{demo_root}/projects/orbit-garden",
                    )

    def test_native_eval_binds_and_records_client_identity(self) -> None:
        native = runpy.run_path(str(ROOT / "tests/behavioral-evals/run_native.py"))
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory)
            workspace = temporary / "workspace"
            workspace.mkdir()
            executable = Path(sys.executable).resolve()
            with mock.patch.object(native["shutil"], "which", return_value=str(executable)):
                identity = native["client_identity"]("codex", workspace)
            self.assertEqual(identity["client"], "codex")
            self.assertEqual(identity["executable"], str(executable))
            self.assertTrue(identity["version"])
            self.assertEqual(identity["sha256"], hashlib.sha256(executable.read_bytes()).hexdigest())

            workspace_shim = workspace / "codex"
            shutil.copy2(executable, workspace_shim)
            with mock.patch.object(native["shutil"], "which", return_value=str(workspace_shim)):
                with self.assertRaisesRegex(RuntimeError, "inside the evaluation workspace"):
                    native["client_identity"]("codex", workspace)

    def test_demo_behavior_cases_cover_the_safety_contract(self) -> None:
        cases = json.loads(
            (ROOT / "tests/behavioral-evals/cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {case["id"] for case in cases},
            {
                "activate-established-home",
                "activate-and-read",
                "open-knowledge-interface",
                "explicit-obsidian-view",
                "explicit-read",
                "explicit-write",
                "global-or-project",
                "create-project-repository",
                "ambiguous-no-write",
                "correction-supersedes",
                "privacy-no-leak",
                "no-background-service",
                "no-parallel-knowledge-base",
            },
        )
        self.assertTrue(all(case["knowledge_base"] == "demo" for case in cases))
        for case in cases:
            self.assertEqual(set(case), {"id", "knowledge_base", "prompt", "expected"})
            self.assertIsInstance(case["prompt"], str)
            self.assertTrue(case["prompt"].strip())
            self.assertIsInstance(case["expected"], list)
            self.assertTrue(case["expected"])
            self.assertTrue(
                all(isinstance(item, str) and item.strip() for item in case["expected"])
            )


if __name__ == "__main__":
    unittest.main()
