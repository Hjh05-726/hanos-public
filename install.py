#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


SOURCE_ROOT = Path(__file__).resolve().parent
CORE_SOURCE = SOURCE_ROOT / "skills/hanos"
ADAPTERS_ROOT = SOURCE_ROOT / "adapters"
TEMPLATES_ROOT = SOURCE_ROOT / "Templates"
SUPPORTED_AGENTS = ("codex", "claude-code", "cursor", "copilot", "gemini-cli")
MANAGED_BY = "hanos-install.py-v1"
PAYLOAD_MARKER = ".hanos-install.json"
ADAPTER_BEGIN = "<!-- HANOS_ADAPTER:BEGIN -->"
ADAPTER_END = "<!-- HANOS_ADAPTER:END -->"
CLIENT_COMMANDS = {
    "codex": ("codex",),
    "claude-code": ("claude",),
    "cursor": ("cursor",),
    "copilot": ("code",),
    "gemini-cli": ("gemini",),
}
KNOWLEDGE_AUTHORITIES = (
    (Path("00_Agent_Entry.md"), "agent-entry"),
    (Path("HanOS Rules.md"), "rules"),
    (Path("global/README.md"), "global-readme"),
)


class InstallerError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install the Agent-neutral HanOS Skill and selected client adapters."
    )
    parser.add_argument("--version", action="version",
                        version="HanOS " + (SOURCE_ROOT / "VERSION").read_text(encoding="utf-8").strip())
    parser.add_argument("--agent", choices=(*SUPPORTED_AGENTS, "all"))
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--knowledge-home", type=Path)
    parser.add_argument("--display-name")
    parser.add_argument("--yes", action="store_true", help="Use supplied values without prompts")
    return parser.parse_args()


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def payload_digest(root: Path, *, include_runtime: bool = False) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative == PAYLOAD_MARKER:
            continue
        if not include_runtime and (
            "__pycache__" in path.relative_to(root).parts or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise InstallerError(f"{label} is unreadable: {path}: {error}") from error


def read_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(read_text(path, label))
    except json.JSONDecodeError as error:
        raise InstallerError(f"{label} is unreadable: {path}: {error}") from error
    if not isinstance(value, dict):
        raise InstallerError(f"{label} must be a JSON object: {path}")
    return value


def validate_managed_directory(destination: Path) -> dict[str, object]:
    marker_path = destination / PAYLOAD_MARKER
    if not marker_path.is_file():
        raise InstallerError(
            f"refusing to overwrite unmanaged directory: {destination}; move it or run doctor"
        )
    marker = read_json(marker_path, "install marker")
    if marker.get("managed_by") != MANAGED_BY:
        raise InstallerError(f"unknown install owner for {destination}")
    expected = marker.get("payload_hash")
    if marker.get("payload_hash_version") not in (None, 2):
        raise InstallerError(f"unsupported payload hash version: {destination}")
    actual = payload_digest(destination)
    # Older installations may have included bytecode already present at install time.
    # Accept their exact legacy hash, but never ignore an unverified source change.
    if expected != actual and marker.get("payload_hash_version") is None:
        actual = payload_digest(destination, include_runtime=True)
    if expected != actual:
        raise InstallerError(f"CORE_DRIFT at {destination}; preserve or remove local edits first")
    return marker


def install_managed_directory(destination: Path, source: Path, metadata: dict[str, object]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.new-", dir=destination.parent))
    backup: Path | None = None
    try:
        shutil.copytree(source, temporary, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        payload_hash = payload_digest(temporary)
        marker = {"managed_by": MANAGED_BY, "payload_hash": payload_hash,
                  "payload_hash_version": 2, **metadata}
        atomic_write(temporary / PAYLOAD_MARKER, json_text(marker))

        if destination.exists():
            current = validate_managed_directory(destination)
            if current == marker:
                shutil.rmtree(temporary)
                return
            backup = destination.with_name(f".{destination.name}.previous")
            if backup.exists():
                raise InstallerError(f"stale installer backup requires review: {backup}")
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except BaseException:
            if backup is not None and backup.exists() and not destination.exists():
                os.replace(backup, destination)
            raise
        if backup is not None:
            shutil.rmtree(backup)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def make_rendered_wrapper(template: Path, core_path: Path, config_path: Path) -> Path:
    temporary_root = Path(tempfile.mkdtemp(prefix="hanos-wrapper-"))
    rendered = template.read_text(encoding="utf-8")
    rendered = rendered.replace("{{CORE_SKILL_PATH}}", str(core_path / "SKILL.md"))
    rendered = rendered.replace("{{CONFIG_PATH}}", str(config_path))
    atomic_write(temporary_root / "SKILL.md", rendered)
    return temporary_root


def render_codex_adapter(display_name: str, config_path: Path, core_path: Path) -> str:
    template = (ADAPTERS_ROOT / "codex/AGENTS.md.template").read_text(encoding="utf-8")
    return (
        template.replace("{{DISPLAY_NAME}}", display_name)
        .replace("{{CONFIG_PATH}}", str(config_path))
        .replace("{{CORE_SKILL_PATH}}", str(core_path / "SKILL.md"))
    )


def extract_managed_block(path: Path) -> str:
    if not path.is_file():
        raise InstallerError(f"CODEX_ADAPTER_MISSING:{path}")
    text = read_text(path, "Codex adapter")
    if text.count(ADAPTER_BEGIN) != 1 or text.count(ADAPTER_END) != 1:
        raise InstallerError(f"CODEX_ADAPTER_MARKERS_INVALID:{path}")
    begin = text.index(ADAPTER_BEGIN)
    end = text.index(ADAPTER_END, begin) + len(ADAPTER_END)
    return text[begin:end]


def merge_managed_block(path: Path, rendered_block: str) -> None:
    if rendered_block.count(ADAPTER_BEGIN) != 1 or rendered_block.count(ADAPTER_END) != 1:
        raise InstallerError("client adapter template has invalid managed markers")
    existing = read_text(path, "client instruction file") if path.exists() else ""
    begin_count = existing.count(ADAPTER_BEGIN)
    end_count = existing.count(ADAPTER_END)
    if begin_count != end_count or begin_count > 1:
        raise InstallerError(f"client instruction file has invalid HanOS markers: {path}")
    if begin_count == 1:
        prefix, remainder = existing.split(ADAPTER_BEGIN, 1)
        _old, suffix = remainder.split(ADAPTER_END, 1)
        updated = f"{prefix}{rendered_block.rstrip()}{suffix}"
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = f"{existing}{separator}{rendered_block.rstrip()}\n"
    atomic_write(path, updated)


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def paths_overlap(first: Path, second: Path) -> bool:
    return is_within(first, second) or is_within(second, first)


def safe_resolve(path: Path, label: str, *, strict: bool = False) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=strict)
        if not strict:
            # Python 3.13 non-strict resolution suppresses symlink-loop errors.
            # Allow missing installation targets, but inspect their ancestors
            # with stat(), which still reports loops and inaccessible paths.
            for candidate in (resolved, *resolved.parents):
                try:
                    candidate.stat()
                    break
                except FileNotFoundError:
                    continue
        return resolved
    except (OSError, RuntimeError, ValueError) as error:
        raise InstallerError(f"{label} cannot be resolved: {path}: {error}") from error


def install_path_outside_issue(path: Path, home: Path, label: str) -> str | None:
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        if path.exists() or path.is_symlink():
            return f"INSTALL_PATH_INVALID:{label}:{error}"
        return None
    if not is_within(resolved, home):
        return f"INSTALL_PATH_OUTSIDE:{label}"
    return None


def validate_display_name(value: str) -> str:
    if len(value.splitlines()) != 1:
        raise InstallerError("display name must be one non-empty line")
    normalized = value.strip()
    if (
        not normalized
        or "`" in normalized
        or ADAPTER_BEGIN in normalized
        or ADAPTER_END in normalized
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized)
    ):
        raise InstallerError("display name must be one non-empty line")
    return normalized


def preflight_file_target(path: Path, home: Path, label: str) -> None:
    if not is_within(safe_resolve(path.parent, f"{label} parent"), home):
        raise InstallerError(f"{label} escapes the install home: {path}")
    if path.is_symlink():
        raise InstallerError(f"{label} must not be a symbolic link: {path}")
    if path.exists() and not path.is_file():
        raise InstallerError(f"{label} must be a regular file: {path}")


def preflight_managed_directory(destination: Path, home: Path) -> None:
    if not is_within(
        safe_resolve(destination.parent, "managed directory parent"), home
    ):
        raise InstallerError(f"managed directory escapes the install home: {destination}")
    if destination.is_symlink():
        raise InstallerError(f"managed directory must not be a symbolic link: {destination}")
    if destination.exists():
        validate_managed_directory(destination)
    backup = destination.with_name(f".{destination.name}.previous")
    if backup.exists() or backup.is_symlink():
        raise InstallerError(f"stale installer backup requires review: {backup}")


def preflight_managed_block(path: Path, home: Path) -> None:
    preflight_file_target(path, home, "client instruction file")
    if not path.exists():
        return
    existing = read_text(path, "client instruction file")
    begin_count = existing.count(ADAPTER_BEGIN)
    end_count = existing.count(ADAPTER_END)
    if begin_count != end_count or begin_count > 1:
        raise InstallerError(f"client instruction file has invalid HanOS markers: {path}")


def preflight_install_targets(home: Path, agents: Iterable[str]) -> None:
    preflight_file_target(home / ".config/hanos/config.json", home, "config")
    preflight_file_target(
        home / ".config/hanos/install-manifest.json", home, "install manifest"
    )
    preflight_managed_directory(home / ".agents/skills/hanos", home)
    if "claude-code" in agents:
        preflight_managed_directory(home / ".claude/skills/hanos", home)
    if "cursor" in agents:
        preflight_managed_directory(home / ".cursor/skills/hanos", home)
    if "codex" in agents:
        preflight_managed_block(home / ".codex/AGENTS.md", home)


def remove_exact_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def snapshot_install_artifacts(
    paths: Iterable[Path],
) -> tuple[Path, list[tuple[Path, str | None, Path | None]]]:
    backup_root = Path(tempfile.mkdtemp(prefix="hanos-install-rollback-"))
    snapshots: list[tuple[Path, str | None, Path | None]] = []
    try:
        for index, path in enumerate(paths):
            if path.is_dir():
                backup = backup_root / str(index)
                shutil.copytree(path, backup)
                snapshots.append((path, "directory", backup))
            elif path.is_file():
                backup = backup_root / str(index)
                shutil.copy2(path, backup)
                snapshots.append((path, "file", backup))
            else:
                snapshots.append((path, None, None))
        atomic_write(backup_root / "restore-manifest.json", json_text({
            "version": 1,
            "artifacts": [
                {"path": str(path), "kind": kind,
                 "backup": backup.name if backup is not None else None}
                for path, kind, backup in snapshots
            ],
        }))
    except BaseException:
        shutil.rmtree(backup_root)
        raise
    return backup_root, snapshots


def restore_install_artifacts(
    snapshots: Iterable[tuple[Path, str | None, Path | None]],
) -> None:
    for path, kind, backup in reversed(list(snapshots)):
        if kind is None or backup is None:
            remove_exact_path(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "directory":
            temporary = Path(tempfile.mkdtemp(prefix=f".{path.name}.restore-", dir=path.parent))
            try:
                shutil.copytree(backup, temporary, dirs_exist_ok=True)
                remove_exact_path(path)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.restore-", dir=path.parent)
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                shutil.copy2(backup, temporary)
                os.replace(temporary, path)
            finally:
                if temporary.exists():
                    temporary.unlink()


def remove_new_files(paths: Iterable[Path], existed_before: dict[Path, bool]) -> None:
    for path in paths:
        if not existed_before[path]:
            remove_exact_path(path)


def remove_new_empty_directories(
    paths: Iterable[Path], existed_before: dict[Path, bool]
) -> None:
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        if not existed_before[path] and path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def choose_agents(requested: str, prior: Iterable[str]) -> list[str]:
    selected = set(SUPPORTED_AGENTS if requested == "all" else (requested,))
    selected.update(agent for agent in prior if agent in SUPPORTED_AGENTS)
    return sorted(selected, key=SUPPORTED_AGENTS.index)


def detect_clients() -> dict[str, bool]:
    return {
        agent: any(shutil.which(command) is not None for command in commands)
        for agent, commands in CLIENT_COMMANDS.items()
    }


def knowledge_authority_issue(path: Path, knowledge_home: Path, label: str) -> str | None:
    if not (path.exists() or path.is_symlink()):
        return f"KNOWLEDGE_AUTHORITY_MISSING:{label}"
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        return f"KNOWLEDGE_AUTHORITY_INVALID:{label}:{error}"
    if not is_within(resolved, knowledge_home):
        return f"KNOWLEDGE_PATH_OUTSIDE:{label}"
    if not resolved.is_file():
        return f"KNOWLEDGE_AUTHORITY_INVALID:{label}"
    return None


def ensure_knowledge_home(knowledge_home: Path) -> Path:
    source = safe_resolve(SOURCE_ROOT, "HanOS source")
    resolved = safe_resolve(knowledge_home, "knowledge home")
    if paths_overlap(resolved, source):
        raise InstallerError("knowledge home must be outside the HanOS source tree")
    if resolved.exists() and not resolved.is_dir():
        raise InstallerError(f"knowledge home must be a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    control = resolved / ".hanos"
    global_root = resolved / "global"

    for child in (control, global_root):
        if child.is_symlink() or child.exists():
            try:
                child_target = safe_resolve(
                    child, "knowledge-home directory", strict=True
                )
            except InstallerError:
                raise
            if not is_within(child_target, resolved):
                raise InstallerError(f"{child} escapes the knowledge home")
            if not child_target.is_dir():
                raise InstallerError(f"knowledge-home directory is not a directory: {child}")

    registry_path = control / "repositories.json"
    if registry_path.exists() or registry_path.is_symlink():
        registry_issues = validate_registry(resolved)
        if registry_issues:
            raise InstallerError("; ".join(registry_issues))

    control.mkdir(parents=True, exist_ok=True)
    global_root.mkdir(parents=True, exist_ok=True)
    if not registry_path.exists():
        registry = {
            "version": 1,
            "repositories": [
                {
                    "id": "global",
                    "name": "Global knowledge",
                    "type": "global",
                    "path": str(global_root),
                    "status": "active",
                    "aliases": ["global", "shared knowledge"],
                }
            ],
        }
        atomic_write(registry_path, json_text(registry))
    else:
        read_json(registry_path, "repository registry")
    authority_contents = {
        Path("00_Agent_Entry.md"): (
            "# HanOS Agent Entry\n\nRead `.hanos/repositories.json`, then the selected scope's existing authority.\n"
        ),
        Path("HanOS Rules.md"): (
            "# HanOS Rules\n\n- Let the model capture clear, low-risk durable knowledge.\n- Confirm highly sensitive or ambiguous persistence.\n- Preserve superseded history.\n"
        ),
        Path("global/README.md"): (TEMPLATES_ROOT / "global/README.md").read_text(
            encoding="utf-8"
        ),
    }
    for relative_path, label in KNOWLEDGE_AUTHORITIES:
        authority = resolved / relative_path
        if authority.exists() or authority.is_symlink():
            issue = knowledge_authority_issue(authority, resolved, label)
            if issue:
                raise InstallerError(issue)
        else:
            atomic_write(authority, authority_contents[relative_path])
    return resolved


def commit_install(
    home: Path,
    knowledge_argument: Path,
    display_name: str,
    agents: list[str],
    config_path: Path,
    install_manifest_path: Path,
) -> int:
    knowledge_home = ensure_knowledge_home(knowledge_argument)
    registry_issues = validate_registry(knowledge_home)
    if registry_issues:
        raise InstallerError("; ".join(registry_issues))
    config = {
        "version": 1,
        "identity": {"technical_name": "hanos", "display_name": display_name},
        "knowledge_home": str(knowledge_home),
        "invocation": {"mode": "adaptive", "default_access": "read_and_capture"},
        "writing": {
            "automatic_capture": True,
            "confirm_sensitive": True,
            "update_existing_before_create": True,
            "preserve_superseded_history": True,
        },
        "safety": {
            "store_secrets": False,
            "modify_external_projects": False,
            "modify_cloud_resources": False,
            "modify_production_data": False,
        },
    }
    atomic_write(config_path, json_text(config))

    canonical = home / ".agents/skills/hanos"
    canonical_source = Path(tempfile.mkdtemp(prefix="hanos-core-"))
    try:
        shutil.copytree(CORE_SOURCE, canonical_source, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        atomic_write(canonical_source / "installation.json", json_text({
            "version": 1,
            "config_path": str(config_path),
            "canonical_skill_path": str(canonical),
        }))
        if "codex" in agents:
            metadata_target = canonical_source / "agents/openai.yaml"
            metadata_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ADAPTERS_ROOT / "codex/agents/openai.yaml", metadata_target)
        install_managed_directory(
            canonical,
            canonical_source,
            {"kind": "canonical-core", "agents": agents},
        )
    finally:
        shutil.rmtree(canonical_source)

    wrappers: dict[str, str] = {}
    for agent, relative_destination in (
        ("claude-code", Path(".claude/skills/hanos")),
        ("cursor", Path(".cursor/skills/hanos")),
    ):
        if agent not in agents:
            continue
        wrapper_source = make_rendered_wrapper(
            ADAPTERS_ROOT / agent / "SKILL.md.template", canonical, config_path
        )
        destination = home / relative_destination
        try:
            install_managed_directory(
                destination,
                wrapper_source,
                {"kind": "thin-wrapper", "agent": agent},
            )
        finally:
            shutil.rmtree(wrapper_source)
        wrappers[agent] = str(destination)

    if "codex" in agents:
        rendered = render_codex_adapter(display_name, config_path, canonical)
        merge_managed_block(home / ".codex/AGENTS.md", rendered)

    detected = detect_clients()
    adapter_artifacts: dict[str, dict[str, str]] = {}
    for agent in agents:
        if agent == "codex":
            adapter_artifacts[agent] = {
                "kind": "managed-block",
                "path": str(home / ".codex/AGENTS.md"),
            }
        elif agent in wrappers:
            adapter_artifacts[agent] = {
                "kind": "managed-directory",
                "path": wrappers[agent],
            }
        else:
            adapter_artifacts[agent] = {
                "kind": "shared-core",
                "path": str(canonical),
            }
    install_manifest = {
        "version": 1,
        "managed_by": MANAGED_BY,
        "operating_system": platform.system(),
        "agents": agents,
        "detected_clients": detected,
        "canonical_skill_path": str(canonical),
        "source_root": str(SOURCE_ROOT),
        "config_path": str(config_path),
        "knowledge_home": str(knowledge_home),
        "installation_locator_version": 1,
        "wrappers": wrappers,
        "adapters": adapter_artifacts,
    }
    if "codex" in agents:
        install_manifest["codex_adapter_hash"] = hashlib.sha256(
            extract_managed_block(home / ".codex/AGENTS.md").encode("utf-8")
        ).hexdigest()
        install_manifest["codex_adapter_display_name"] = display_name
    atomic_write(install_manifest_path, json_text(install_manifest))

    doctor_result = doctor(home)
    if doctor_result != 0:
        raise InstallerError("installation finished but doctor reported a failure")
    print(f"OPERATING_SYSTEM={platform.system()}")
    print("DETECTED_AGENTS=" + ",".join(agent for agent, present in detected.items() if present))
    print(f"CANONICAL_SKILL_PATH={canonical}")
    print(f"KNOWLEDGE_HOME={knowledge_home}")
    print("BACKGROUND_SERVICE_CREATED=NO")
    print("HANOS_INSTALL=PASS")
    return 0


def install(args: argparse.Namespace) -> int:
    if args.agent is None:
        raise InstallerError("--agent is required unless --doctor is used")

    checked = subprocess.run(
        [sys.executable, "-B", str(CORE_SOURCE / "scripts/generate_html.py"), "--check-template"],
        capture_output=True, text=True, check=False,
    )
    if checked.returncode != 0:
        raise InstallerError(f"TEMPLATE_PACKAGE_INVALID: {checked.stderr.strip()}")

    home = safe_resolve(args.home, "install home")
    config_dir = home / ".config/hanos"
    config_path = config_dir / "config.json"
    install_manifest_path = config_dir / "install-manifest.json"
    preflight_file_target(config_path, home, "config")
    preflight_file_target(install_manifest_path, home, "install manifest")
    config_exists = config_path.exists()
    manifest_exists = install_manifest_path.exists()
    if config_exists != manifest_exists:
        raise InstallerError("refusing to replace invalid existing installation")

    prior_manifest: dict[str, object] = {}
    prior_config: dict[str, object] = {}
    if manifest_exists:
        try:
            prior_manifest = read_json(install_manifest_path, "install manifest")
            prior_config = read_json(config_path, "HanOS config")
        except InstallerError as error:
            raise InstallerError(
                f"refusing to replace invalid existing installation: {error}"
            ) from error
        if doctor(home, allow_legacy=True) != 0:
            raise InstallerError("refusing to replace invalid existing installation")
    prior_agents = prior_manifest.get("agents", [])
    if not isinstance(prior_agents, list):
        raise InstallerError("install manifest agents must be a list")
    agents = choose_agents(args.agent, prior_agents)

    codex_instructions = home / ".codex/AGENTS.md"
    if "codex" in agents and codex_instructions.exists() and "codex" not in prior_agents:
        existing_instructions = read_text(codex_instructions, "client instruction file")
        if ADAPTER_BEGIN in existing_instructions or ADAPTER_END in existing_instructions:
            raise InstallerError("refusing to replace invalid existing installation")

    knowledge_argument = args.knowledge_home or (
        Path(str(prior_config["knowledge_home"])) if "knowledge_home" in prior_config else None
    )
    display_name = args.display_name or (
        str(prior_config.get("identity", {}).get("display_name"))
        if isinstance(prior_config.get("identity"), dict)
        else None
    )

    if knowledge_argument is None:
        if args.yes:
            raise InstallerError("--knowledge-home is required with --yes")
        knowledge_argument = Path(input("Private knowledge-home absolute path: ").strip())
    if not display_name:
        if args.yes:
            raise InstallerError("--display-name is required with --yes")
        display_name = input("Display name [Atlas]: ").strip() or "Atlas"
    display_name = validate_display_name(display_name)

    preflight_install_targets(home, agents)
    canonical = home / ".agents/skills/hanos"
    artifact_paths = [
        config_path,
        install_manifest_path,
        canonical,
        canonical.with_name(f".{canonical.name}.previous"),
    ]
    if "claude-code" in agents:
        destination = home / ".claude/skills/hanos"
        artifact_paths.extend(
            (destination, destination.with_name(f".{destination.name}.previous"))
        )
    if "cursor" in agents:
        destination = home / ".cursor/skills/hanos"
        artifact_paths.extend(
            (destination, destination.with_name(f".{destination.name}.previous"))
        )
    if "codex" in agents:
        artifact_paths.append(home / ".codex/AGENTS.md")

    knowledge_target = safe_resolve(knowledge_argument, "knowledge home")
    knowledge_files = [
        knowledge_target / ".hanos/repositories.json",
        knowledge_target / "global/README.md",
        knowledge_target / "00_Agent_Entry.md",
        knowledge_target / "HanOS Rules.md",
    ]
    directory_paths = [
        home,
        home / ".config",
        home / ".config/hanos",
        home / ".agents",
        home / ".agents/skills",
        home / ".claude",
        home / ".claude/skills",
        home / ".cursor",
        home / ".cursor/skills",
        home / ".codex",
        knowledge_target,
        knowledge_target / ".hanos",
        knowledge_target / "global",
    ]
    knowledge_file_state = {
        path: path.exists() or path.is_symlink() for path in knowledge_files
    }
    directory_state = {
        path: path.exists() or path.is_symlink() for path in directory_paths
    }
    backup_root, snapshots = snapshot_install_artifacts(artifact_paths)
    cleanup_backup = False
    try:
        result = commit_install(
            home,
            knowledge_argument,
            display_name,
            agents,
            config_path,
            install_manifest_path,
        )
        cleanup_backup = True
        return result
    except BaseException as error:
        try:
            restore_install_artifacts(snapshots)
            remove_new_files(knowledge_files, knowledge_file_state)
            remove_new_empty_directories(directory_paths, directory_state)
        except BaseException as rollback_error:
            raise InstallerError(
                f"installation failed and rollback was incomplete: {rollback_error}; "
                f"recovery backup and restore-manifest.json retained at {backup_root}"
            ) from error
        cleanup_backup = True
        raise
    finally:
        if cleanup_backup:
            shutil.rmtree(backup_root)


def validate_registry(knowledge_home: Path) -> list[str]:
    issues: list[str] = []
    registry_path = knowledge_home / ".hanos/repositories.json"
    if not registry_path.is_file():
        return [f"REGISTRY_MISSING:{registry_path}"]
    try:
        if not is_within(registry_path.resolve(strict=True), knowledge_home.resolve(strict=True)):
            return [f"REGISTRY_PATH_OUTSIDE:{registry_path}"]
    except (OSError, RuntimeError, ValueError) as error:
        return [f"REGISTRY_INVALID:{error}"]
    try:
        registry = read_json(registry_path, "repository registry")
    except InstallerError as error:
        return [f"REGISTRY_INVALID:{error}"]
    if registry.get("version") != 1:
        issues.append("REGISTRY_VERSION_UNSUPPORTED")
    repositories = registry.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        issues.append("REGISTRY_INVALID:repositories must be a non-empty list")
        return issues
    selectors: dict[str, str] = {}
    active_ids: dict[str, int] = {}
    for item_index, item in enumerate(repositories):
        if not isinstance(item, dict):
            issues.append("REGISTRY_INVALID:repository entry must be an object")
            continue
        status = item.get("status")
        if not isinstance(status, str) or not status.strip():
            issues.append("REGISTRY_INVALID:repository entry missing status")
            continue
        if status != "active":
            continue
        for key in ("id", "name", "type", "path"):
            if not isinstance(item.get(key), str) or not str(item[key]).strip():
                issues.append(f"REGISTRY_INVALID:active entry missing {key}")
        repository_id = item.get("id")
        if isinstance(repository_id, str) and repository_id.strip():
            normalized_id = repository_id.strip().casefold()
            previous_index = active_ids.setdefault(normalized_id, item_index)
            if previous_index != item_index:
                issues.append(f"REGISTRY_ID_DUPLICATE:{repository_id}")
        repository_type = item.get("type")
        if repository_type not in {"global", "project"}:
            issues.append(f"REGISTRY_TYPE_UNSUPPORTED:{item.get('id', '<unknown>')}")
        try:
            path = Path(str(item["path"]))
            resolved_path = path.resolve(strict=True)
        except (KeyError, OSError, RuntimeError, ValueError):
            issues.append(f"REGISTRY_PATH_INVALID:{item.get('id', '<unknown>')}")
            continue
        if not path.is_absolute() or not is_within(resolved_path, knowledge_home):
            issues.append(f"REGISTRY_PATH_OUTSIDE:{item.get('id', '<unknown>')}")
        aliases = item.get("aliases", [])
        if not isinstance(aliases, list):
            issues.append(f"REGISTRY_INVALID:aliases:{item.get('id', '<unknown>')}")
            continue
        owner = f"entry-{item_index}"
        for selector in (item.get("id"), item.get("name"), *aliases):
            if not isinstance(selector, str) or not selector.strip():
                issues.append(f"REGISTRY_INVALID:selector:{item.get('id', '<unknown>')}")
                continue
            normalized = selector.strip().casefold()
            previous_owner = selectors.setdefault(normalized, owner)
            if previous_owner != owner:
                issues.append(f"REGISTRY_SELECTOR_COLLISION:{selector}")
    return issues


def validate_config(config: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if config.get("version") != 1:
        issues.append("CONFIG_VERSION_UNSUPPORTED")

    identity = config.get("identity")
    if not isinstance(identity, dict) or identity.get("technical_name") != "hanos":
        issues.append("CONFIG_TECHNICAL_NAME_INVALID")
    else:
        display_name = identity.get("display_name")
        if not isinstance(display_name, str):
            issues.append("CONFIG_DISPLAY_NAME_INVALID")
        else:
            try:
                validate_display_name(display_name)
            except InstallerError:
                issues.append("CONFIG_DISPLAY_NAME_INVALID")

    if config.get("invocation") != {
        "mode": "adaptive",
        "default_access": "read_and_capture",
    }:
        issues.append("CONFIG_INVOCATION_INVALID")
    if config.get("writing") != {
        "automatic_capture": True,
        "confirm_sensitive": True,
        "update_existing_before_create": True,
        "preserve_superseded_history": True,
    }:
        issues.append("CONFIG_WRITING_POLICY_INVALID")
    if config.get("safety") != {
        "store_secrets": False,
        "modify_external_projects": False,
        "modify_cloud_resources": False,
        "modify_production_data": False,
    }:
        issues.append("CONFIG_SAFETY_POLICY_INVALID")
    if not isinstance(config.get("knowledge_home"), str) or not str(
        config.get("knowledge_home", "")
    ).strip():
        issues.append("CONFIG_KNOWLEDGE_HOME_INVALID")
    return issues


def doctor(home: Path, *, allow_legacy: bool = False) -> int:
    try:
        home = safe_resolve(home, "install home")
    except InstallerError as error:
        print(str(error))
        print("HANOS_DOCTOR=FAIL")
        return 1
    config_path = home / ".config/hanos/config.json"
    manifest_path = home / ".config/hanos/install-manifest.json"
    issues: list[str] = []
    if not config_path.is_file():
        issues.append(f"CONFIG_MISSING:{config_path}")
    if not manifest_path.is_file():
        issues.append(f"INSTALL_MANIFEST_MISSING:{manifest_path}")
    for label, path in (("config", config_path), ("install-manifest", manifest_path)):
        issue = install_path_outside_issue(path, home, label)
        if issue:
            issues.append(issue)
    if issues:
        for issue in issues:
            print(issue)
        print("HANOS_DOCTOR=FAIL")
        return 1

    try:
        config = read_json(config_path, "HanOS config")
        manifest = read_json(manifest_path, "install manifest")
        issues.extend(validate_config(config))
        knowledge_value = config.get("knowledge_home")
        knowledge_home: Path | None = None
        if isinstance(knowledge_value, str) and Path(knowledge_value).is_absolute():
            try:
                knowledge_home = Path(knowledge_value).resolve(strict=True)
                if not knowledge_home.is_dir():
                    issues.append("CONFIG_KNOWLEDGE_HOME_INVALID")
                elif paths_overlap(knowledge_home, SOURCE_ROOT.resolve()):
                    issues.append("KNOWLEDGE_HOME_OVERLAPS_SOURCE")
                else:
                    issues.extend(validate_registry(knowledge_home))
            except (OSError, RuntimeError, ValueError) as error:
                issues.append(f"CONFIG_KNOWLEDGE_HOME_INVALID:{error}")
        elif "CONFIG_KNOWLEDGE_HOME_INVALID" not in issues:
            issues.append("CONFIG_KNOWLEDGE_HOME_INVALID")

        if manifest.get("version") != 1:
            issues.append("INSTALL_MANIFEST_VERSION_UNSUPPORTED")
        if manifest.get("managed_by") != MANAGED_BY:
            issues.append("INSTALL_MANIFEST_OWNER_INVALID")
        agents = manifest.get("agents")
        if (
            not isinstance(agents, list)
            or not agents
            or len(set(str(agent) for agent in agents)) != len(agents)
            or any(agent not in SUPPORTED_AGENTS for agent in agents)
        ):
            issues.append("INSTALL_MANIFEST_AGENTS_INVALID")
            agents = []

        canonical = home / ".agents/skills/hanos"
        if manifest.get("canonical_skill_path") != str(canonical):
            issues.append("INSTALL_MANIFEST_CANONICAL_PATH_INVALID")
        if manifest.get("config_path") != str(config_path):
            issues.append("INSTALL_MANIFEST_CONFIG_PATH_INVALID")
        if knowledge_home is not None and manifest.get("knowledge_home") != str(knowledge_home):
            issues.append("INSTALL_MANIFEST_KNOWLEDGE_HOME_INVALID")
        canonical_path_issue = install_path_outside_issue(canonical, home, "canonical-core")
        canonical_backup = canonical.with_name(f".{canonical.name}.previous")
        if canonical_backup.exists() or canonical_backup.is_symlink():
            issues.append(f"STALE_INSTALL_BACKUP:{canonical_backup}")
        if canonical_path_issue:
            issues.append(canonical_path_issue)
        else:
            canonical_marker: dict[str, object] = {}
            try:
                canonical_marker = validate_managed_directory(canonical)
                if canonical_marker.get("kind") != "canonical-core" or canonical_marker.get(
                    "agents"
                ) != agents:
                    issues.append("CANONICAL_CORE_MARKER_INVALID")
            except InstallerError as error:
                issues.append(str(error))
            legacy_locator = (
                allow_legacy
                and "installation_locator_version" not in manifest
                and "payload_hash_version" not in canonical_marker
            )
            if not legacy_locator:
                locator_path = canonical / "installation.json"
                locator_issue = install_path_outside_issue(locator_path, home, "installation-locator")
                if locator_issue:
                    issues.append(locator_issue)
                else:
                    try:
                        locator = read_json(locator_path, "INSTALLATION_LOCATOR")
                        if manifest.get("installation_locator_version") != 1 or locator != {
                            "version": 1, "config_path": str(config_path),
                            "canonical_skill_path": str(canonical),
                        }:
                            issues.append("INSTALLATION_LOCATOR_INVALID")
                    except InstallerError as error:
                        issues.append(str(error))

        wrappers = manifest.get("wrappers", {})
        if not isinstance(wrappers, dict):
            issues.append("WRAPPER_MANIFEST_INVALID")
        else:
            expected_wrappers = {
                agent: str(home / relative)
                for agent, relative in (
                    ("claude-code", Path(".claude/skills/hanos")),
                    ("cursor", Path(".cursor/skills/hanos")),
                )
                if agent in agents
            }
            if wrappers != expected_wrappers:
                issues.append("WRAPPER_MANIFEST_INVALID")
            for agent, wrapper in expected_wrappers.items():
                wrapper_path = Path(wrapper)
                wrapper_backup = wrapper_path.with_name(f".{wrapper_path.name}.previous")
                if wrapper_backup.exists() or wrapper_backup.is_symlink():
                    issues.append(f"STALE_INSTALL_BACKUP:{wrapper_backup}")
                wrapper_path_issue = install_path_outside_issue(
                    wrapper_path, home, f"wrapper:{agent}"
                )
                if wrapper_path_issue:
                    issues.append(wrapper_path_issue)
                else:
                    try:
                        marker = validate_managed_directory(wrapper_path)
                        if marker.get("kind") != "thin-wrapper" or marker.get("agent") != agent:
                            issues.append(f"WRAPPER_MARKER_INVALID:{agent}")
                    except InstallerError as error:
                        issues.append(str(error))

        adapters = manifest.get("adapters")
        if not isinstance(adapters, dict) or set(adapters) != set(agents):
            issues.append("ADAPTER_MANIFEST_INVALID")
        else:
            for agent in agents:
                artifact = adapters.get(agent)
                if not isinstance(artifact, dict):
                    issues.append(f"ADAPTER_MANIFEST_INVALID:{agent}")
                    continue
                if agent == "codex":
                    expected_path = home / ".codex/AGENTS.md"
                    if artifact != {"kind": "managed-block", "path": str(expected_path)}:
                        issues.append("CODEX_ADAPTER_MANIFEST_INVALID")
                    adapter_path_issue = install_path_outside_issue(
                        expected_path, home, "adapter:codex"
                    )
                    if adapter_path_issue:
                        issues.append(adapter_path_issue)
                    else:
                        try:
                            identity = config.get("identity")
                            display_name = (
                                str(identity.get("display_name"))
                                if isinstance(identity, dict)
                                else ""
                            )
                            installed_block = extract_managed_block(expected_path)
                            expected_hash = manifest.get("codex_adapter_hash")
                            if expected_hash is not None:
                                valid_block = expected_hash == hashlib.sha256(
                                    installed_block.encode("utf-8")
                                ).hexdigest()
                                if manifest.get("codex_adapter_display_name") != display_name:
                                    issues.append("CODEX_ADAPTER_CONFIG_MISMATCH")
                            elif manifest.get("installation_locator_version") == 1:
                                valid_block = False
                            else:
                                # A legacy manifest has no recorded template identity.
                                # Bootstrap only from an exact known template match.
                                valid_block = installed_block == render_codex_adapter(
                                    display_name, config_path, canonical
                                ).rstrip()
                            if not valid_block:
                                issues.append("CODEX_ADAPTER_DRIFT")
                        except InstallerError as error:
                            issues.append(str(error))
                elif agent in {"claude-code", "cursor"}:
                    expected_path = Path(str(wrappers.get(agent, "")))
                    if artifact != {
                        "kind": "managed-directory",
                        "path": str(expected_path),
                    }:
                        issues.append(f"ADAPTER_MANIFEST_INVALID:{agent}")
                elif artifact != {"kind": "shared-core", "path": str(canonical)}:
                    issues.append(f"ADAPTER_MANIFEST_INVALID:{agent}")
        if knowledge_home is not None:
            for relative_path, label in KNOWLEDGE_AUTHORITIES:
                issue = knowledge_authority_issue(
                    knowledge_home / relative_path, knowledge_home, label
                )
                if issue:
                    issues.append(issue)
    except (InstallerError, OSError, UnicodeError, RuntimeError, ValueError) as error:
        issues.append(str(error))

    if issues:
        for issue in issues:
            print(issue)
        print("HANOS_DOCTOR=FAIL")
        return 1
    print("HANOS_DOCTOR=PASS")
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.doctor:
            return doctor(args.home)
        return install(args)
    except InstallerError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
