#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEMO_SOURCE = ROOT / "examples/demo-knowledge-base"
EXPECTED_RESULT = {
    "project_name": "Orbit Garden",
    "local_status": "CONFIRMED_LOCAL",
    "production_status": "NOT_PROVEN",
    "evidence_path": "projects/orbit-garden/00_Overview.md",
}
RESULT_FIELDS = (*EXPECTED_RESULT, "registry_nonce", "authority_nonce")
RESULT_SCHEMA = {
    "type": "object",
    "properties": {key: {"type": "string"} for key in RESULT_FIELDS},
    "required": list(RESULT_FIELDS),
    "additionalProperties": False,
}
CORE_READ_SENTINELS = (
    "name: hanos",
    "**Explicit invocation**",
    "**Automatic capture**",
)
PROMPT = (
    "Read the Orbit Garden knowledge through HanOS. Report its current local status "
    "and whether production is verified. Do not modify any file. Return only a JSON "
    "object with project_name, local_status, production_status, and evidence_path. "
    "Copy only each source status label into the status fields, without explanation, "
    "express evidence_path relative to the knowledge home, and also return registry_nonce "
    "and authority_nonce copied from their respective source files."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one isolated native explicit-read evaluation for an installed client."
    )
    parser.add_argument("--client", choices=("codex", "claude-code"), required=True)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--keep-workspace", type=Path)
    return parser.parse_args()


def digest(root: Path) -> str:
    value = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        value.update(path.relative_to(root).as_posix().encode("utf-8"))
        value.update(b"\0")
        value.update(path.read_bytes())
        value.update(b"\0")
    return value.hexdigest()


def file_sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def client_identity(client: str, workspace: Path) -> dict[str, str]:
    command_name = "codex" if client == "codex" else "claude"
    discovered = shutil.which(command_name)
    if discovered is None:
        raise RuntimeError(f"{command_name} executable not found")
    executable = Path(discovered).resolve(strict=True)
    if not executable.is_file():
        raise RuntimeError(f"client executable is not a regular file: {executable}")
    if is_within(executable, workspace.resolve()) or is_within(executable, ROOT.resolve()):
        raise RuntimeError(f"client executable is inside the evaluation workspace or source: {executable}")
    version = subprocess.run(
        [str(executable), "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    version_text = (version.stdout.strip() or version.stderr.strip()).splitlines()
    if version.returncode != 0 or not version_text:
        raise RuntimeError(f"cannot identify client executable: {executable}")
    return {
        "client": client,
        "executable": str(executable),
        "version": version_text[-1],
        "sha256": file_sha256(executable),
    }


def require_empty_workspace(workspace: Path) -> None:
    if workspace.exists():
        if not workspace.is_dir() or any(workspace.iterdir()):
            raise RuntimeError(f"persistent workspace must be an empty directory: {workspace}")
    else:
        workspace.mkdir(parents=True)


def materialize_demo_registry(
    registry_path: Path, demo_root: str, registry_nonce: str | None = None
) -> None:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    repositories = registry.get("repositories")
    if not isinstance(repositories, list):
        raise RuntimeError("demo registry repositories must be a list")
    for repository in repositories:
        if not isinstance(repository, dict) or not isinstance(repository.get("path"), str):
            raise RuntimeError("demo registry entry must contain a string path")
        repository["path"] = repository["path"].replace("{{DEMO_ROOT}}", demo_root)
    if registry_nonce is not None:
        registry["evaluation_nonce"] = registry_nonce
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def json_events(trace: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in trace.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"native trace is not JSONL: {error}") from error
        if not isinstance(event, dict):
            raise RuntimeError("native trace event must be a JSON object")
        events.append(event)
    return events


def validate_codex_core_read(trace: str, expected_core: str) -> None:
    validate_codex_read(
        trace,
        "CORE_READ_NOT_PROVEN",
        (expected_core, ".agents/skills/hanos/SKILL.md"),
        CORE_READ_SENTINELS,
    )


def validate_codex_read(
    trace: str,
    error_label: str,
    expected_paths: tuple[str, ...],
    sentinels: tuple[str, ...],
) -> None:
    for event in json_events(trace):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, dict):
            continue
        if item.get("type") != "command_execution" or item.get("exit_code") != 0:
            continue
        command = item.get("command")
        output = item.get("aggregated_output")
        if (
            isinstance(command, str)
            and any(path in command for path in expected_paths)
            and isinstance(output, str)
            and all(sentinel in output for sentinel in sentinels)
        ):
            return
    raise RuntimeError(f"{error_label}:{expected_paths[0]}")


def validate_codex_evidence_reads(
    trace: str,
    workspace: Path,
    registry_nonce: str | None = None,
    authority_nonce: str | None = None,
) -> None:
    validate_codex_core_read(
        trace, str((workspace / ".agents/skills/hanos/SKILL.md").resolve())
    )
    validate_codex_read(
        trace,
        "REGISTRY_READ_NOT_PROVEN",
        (
            str((workspace / "knowledge/.hanos/repositories.json").resolve()),
            "knowledge/.hanos/repositories.json",
            # A pathlib read may join the home and registry suffix. Accept
            # that form only when this run's private nonce proves the source.
            *((".hanos/repositories.json",) if registry_nonce else ()),
        ),
        (
            '"id": "orbit-garden"',
            "knowledge/projects/orbit-garden",
            *((registry_nonce,) if registry_nonce is not None else ()),
        ),
    )
    validate_codex_read(
        trace,
        "PROJECT_AUTHORITY_READ_NOT_PROVEN",
        (
            str(
                (workspace / "knowledge/projects/orbit-garden/00_Overview.md").resolve()
            ),
            "knowledge/projects/orbit-garden/00_Overview.md",
            *(("projects/orbit-garden/00_Overview.md",) if authority_nonce else ()),
        ),
        (
            "Status: `CONFIRMED_LOCAL`",
            "current production health are `NOT_PROVEN`",
            *((authority_nonce,) if authority_nonce is not None else ()),
        ),
    )


def validate_claude_core_read(trace: str, expected_core: str) -> None:
    validate_claude_read(
        trace,
        "CORE_READ_NOT_PROVEN",
        (expected_core, ".agents/skills/hanos/SKILL.md"),
        CORE_READ_SENTINELS,
    )


def validate_claude_read(
    trace: str,
    error_label: str,
    expected_paths: tuple[str, ...],
    sentinels: tuple[str, ...],
) -> None:
    read_ids: set[str] = set()
    tool_results: dict[str, str] = {}
    for event in json_events(trace):
        message = event.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if not isinstance(block, dict):
                continue
            tool_input = block.get("input")
            if (
                block.get("type") == "tool_use"
                and block.get("name") == "Read"
                and isinstance(tool_input, dict)
                and tool_input.get("file_path") in expected_paths
                and isinstance(block.get("id"), str)
            ):
                read_ids.add(str(block["id"]))
            if block.get("type") == "tool_result" and isinstance(
                block.get("tool_use_id"), str
            ):
                tool_results[str(block["tool_use_id"])] = json.dumps(
                    block.get("content"), ensure_ascii=False
                )
    if any(
        all(sentinel in tool_results.get(read_id, "") for sentinel in sentinels)
        for read_id in read_ids
    ):
        return
    raise RuntimeError(f"{error_label}:{expected_paths[0]}")


def validate_claude_evidence_reads(
    trace: str,
    workspace: Path,
    registry_nonce: str | None = None,
    authority_nonce: str | None = None,
) -> None:
    validate_claude_core_read(
        trace, str((workspace / ".agents/skills/hanos/SKILL.md").resolve())
    )
    validate_claude_read(
        trace,
        "REGISTRY_READ_NOT_PROVEN",
        (
            str((workspace / "knowledge/.hanos/repositories.json").resolve()),
            "knowledge/.hanos/repositories.json",
        ),
        (
            '"id": "orbit-garden"',
            "knowledge/projects/orbit-garden",
            *((registry_nonce,) if registry_nonce is not None else ()),
        ),
    )
    validate_claude_read(
        trace,
        "PROJECT_AUTHORITY_READ_NOT_PROVEN",
        (
            str(
                (workspace / "knowledge/projects/orbit-garden/00_Overview.md").resolve()
            ),
            "knowledge/projects/orbit-garden/00_Overview.md",
        ),
        (
            "Status: `CONFIRMED_LOCAL`",
            "current production health are `NOT_PROVEN`",
            *((authority_nonce,) if authority_nonce is not None else ()),
        ),
    )


def validate_result(
    output: str, expected_result: dict[str, str] | None = None
) -> dict[str, str]:
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"STRUCTURED_RESULT_INVALID:{error}") from error
    expected = EXPECTED_RESULT if expected_result is None else expected_result
    if result != expected:
        raise RuntimeError(f"EVIDENCE_RESULT_MISMATCH:{result!r}")
    return result


def claude_result_from_trace(trace: str) -> str:
    for event in reversed(json_events(trace)):
        if event.get("type") != "result":
            continue
        structured = event.get("structured_output")
        if isinstance(structured, dict):
            return json.dumps(structured, ensure_ascii=False)
        result = event.get("result")
        if isinstance(result, str):
            return result
    raise RuntimeError("STRUCTURED_RESULT_MISSING")


def prepare(workspace: Path, client: str) -> tuple[Path, Path, dict[str, str]]:
    require_empty_workspace(workspace)
    knowledge = workspace / "knowledge"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "install.py"),
            "--agent",
            client,
            "--home",
            str(workspace),
            "--knowledge-home",
            str(knowledge),
            "--display-name",
            "Atlas",
            "--yes",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)

    shutil.copytree(DEMO_SOURCE, knowledge, dirs_exist_ok=True)
    registry_path = knowledge / ".hanos/repositories.json"
    registry_nonce = secrets.token_hex(16)
    authority_nonce = secrets.token_hex(16)
    materialize_demo_registry(registry_path, str(knowledge.resolve()), registry_nonce)
    authority_path = knowledge / "projects/orbit-garden/00_Overview.md"
    authority_path.write_text(
        authority_path.read_text(encoding="utf-8")
        + f"\nEvaluation nonce: `{authority_nonce}`\n",
        encoding="utf-8",
    )
    doctor = subprocess.run(
        [sys.executable, str(ROOT / "install.py"), "--doctor", "--home", str(workspace)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if doctor.returncode != 0:
        raise RuntimeError(doctor.stdout or doctor.stderr)

    if client == "codex":
        shutil.copy2(workspace / ".codex/AGENTS.md", workspace / "AGENTS.md")
    expected_result = {
        **EXPECTED_RESULT,
        "registry_nonce": registry_nonce,
        "authority_nonce": authority_nonce,
    }
    return knowledge, workspace / "native-result.txt", expected_result


def run_client(
    client: str,
    executable: Path,
    workspace: Path,
    output_path: Path,
    timeout: int,
) -> tuple[str, str]:
    if client == "codex":
        command = [
            str(executable),
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "--sandbox",
            "read-only",
            "--cd",
            str(workspace),
            "--output-last-message",
            str(output_path),
            "--output-schema",
            str(workspace / "native-result.schema.json"),
            f"Atlas, {PROMPT}",
        ]
        (workspace / "native-result.schema.json").write_text(
            json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            command,
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return output_path.read_text(encoding="utf-8"), completed.stdout

    completed = subprocess.run(
        [
            str(executable),
            f"/hanos {PROMPT}",
            "--print",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "Read,Glob,Grep",
            "--output-format",
            "stream-json",
            "--verbose",
            "--json-schema",
            json.dumps(RESULT_SCHEMA, separators=(",", ":")),
        ],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"claude exited {completed.returncode}: {completed.stderr or completed.stdout}"
        )
    return claude_result_from_trace(completed.stdout), completed.stdout


def evaluate(client: str, workspace: Path, timeout: int) -> int:
    knowledge, output_path, expected_result = prepare(workspace, client)
    identity = client_identity(client, workspace)
    (workspace / "native-client.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = digest(knowledge)
    output, trace = run_client(
        client, Path(identity["executable"]), workspace, output_path, timeout
    )
    (workspace / "native-trace.jsonl").write_text(trace, encoding="utf-8")
    after = digest(knowledge)
    if before != after:
        print("NO_UNREQUESTED_WRITE=FAIL")
        return 1
    if client == "codex":
        validate_codex_evidence_reads(
            trace,
            workspace,
            expected_result["registry_nonce"],
            expected_result["authority_nonce"],
        )
    else:
        validate_claude_evidence_reads(
            trace,
            workspace,
            expected_result["registry_nonce"],
            expected_result["authority_nonce"],
        )
    validate_result(output, expected_result)
    print(f"CLIENT={client}")
    print(f"CLIENT_EXECUTABLE={identity['executable']}")
    print(f"CLIENT_VERSION={identity['version']}")
    print(f"CLIENT_SHA256={identity['sha256']}")
    print("SKILL_DISCOVERY_AND_EXPLICIT_READ=PASS")
    print("NO_UNREQUESTED_WRITE=PASS")
    print("EVIDENCE_BOUNDARY=PASS")
    return 0


def main() -> int:
    args = parse_args()
    try:
        if args.keep_workspace is not None:
            workspace = args.keep_workspace.expanduser().resolve()
            return evaluate(args.client, workspace, args.timeout)
        with tempfile.TemporaryDirectory(prefix="hanos-native-eval-") as temporary:
            return evaluate(args.client, Path(temporary), args.timeout)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"NATIVE_EVAL_ERROR={error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
