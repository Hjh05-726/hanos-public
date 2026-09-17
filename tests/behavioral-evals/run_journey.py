#!/usr/bin/env python3
"""Opt-in native Codex journey on isolated, fictional knowledge only."""
from __future__ import annotations

import argparse
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

import run_native as native


def preserves_original_lines(original: str, updated: str) -> bool:
    remaining = iter(updated.splitlines())
    return all(any(candidate == line for candidate in remaining)
               for line in original.splitlines() if line.strip())


def files_digest(root: Path, *, ignore_runtime: bool = False) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): native.file_sha256(p)
            for p in root.rglob("*") if p.is_file()
            and not (ignore_runtime and ("__pycache__" in p.parts or p.suffix == ".pyc"))}


def run_step(executable: str, workspace: Path, name: str, prompt: str, timeout: int) -> str:
    output = workspace / f"{name}.answer.txt"
    command = [executable, "exec", "--ephemeral", "--skip-git-repo-check", "--json",
               "--sandbox", "workspace-write", "--cd", str(workspace),
               "--output-last-message", str(output),
               "This is an isolated fictional HanOS acceptance test. Use only this workspace's "
               "installed HanOS core, config and knowledge. Do not consult external knowledge "
               "or shared worklogs. Do not change the installed core, adapters, config or registry. "
               "Atlas, " + prompt]
    result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=timeout)
    (workspace / f"{name}.trace.jsonl").write_text(result.stdout, encoding="utf-8")
    (workspace / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"{name}: client exited {result.returncode}; inspect local trace")
    answer = output.read_text(encoding="utf-8")
    if not answer.strip():
        raise RuntimeError(f"{name}: no final answer")
    return answer


def evaluate(workspace: Path, timeout: int) -> None:
    knowledge, output, expected = native.prepare(workspace, "codex")
    identity = native.client_identity("codex", workspace)
    executable = identity["executable"]
    authority = knowledge / "projects/orbit-garden/00_Overview.md"
    original = authority.read_text(encoding="utf-8")
    protected = {path: files_digest(workspace / path, ignore_runtime=True)
                 for path in (".agents", ".codex", ".config")}
    registry_before = native.file_sha256(knowledge / ".hanos/repositories.json")
    report = {"client": identity, "source_core_sha256": native.file_sha256(native.ROOT / "skills/hanos/SKILL.md"),
              "scope": "six-step fictional journey; not all shared behavioral cases", "steps": []}
    (workspace / "journey-result.json").write_text(json.dumps(report, indent=2) + "\n")

    def passed(name: str) -> None:
        for path, before in protected.items():
            if files_digest(workspace / path, ignore_runtime=True) != before:
                raise RuntimeError(f"{name}: installed payload changed")
        if native.file_sha256(knowledge / ".hanos/repositories.json") != registry_before:
            raise RuntimeError(f"{name}: registry changed")
        report["steps"].append({"name": name, "status": "PASS"})
        (workspace / "journey-result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"{name}=PASS", flush=True)

    before = files_digest(knowledge)
    answer, trace = native.run_client("codex", Path(executable), workspace, output, timeout)
    (workspace / "read.trace.jsonl").write_text(trace, encoding="utf-8")
    native.validate_codex_evidence_reads(trace, workspace, expected["registry_nonce"], expected["authority_nonce"])
    native.validate_result(answer, expected)
    if files_digest(knowledge) != before:
        raise RuntimeError("read: unexpected knowledge write")
    passed("explicit-read")

    marker = "DEMO_PLAN_" + secrets.token_hex(8)
    old, new = f"{marker}: tray_count=7", f"{marker}: tray_count=9"
    before = files_digest(knowledge)
    run_step(executable, workspace, "record", "Record this fictional fact in the existing Orbit Garden "
             f"project authority, retaining the exact text: {old}. This is local planning only; "
             "production remains NOT_PROVEN. Verify the saved note.", timeout)
    body = authority.read_text(encoding="utf-8")
    after = files_digest(knowledge)
    authority_key = authority.relative_to(knowledge).as_posix()
    if old not in body or not preserves_original_lines(original, body):
        raise RuntimeError("record: exact fact missing or existing authority not preserved")
    if {p for p in set(before) | set(after) if before.get(p) != after.get(p)} != {authority_key}:
        raise RuntimeError("record: modified unexpected knowledge files")
    passed("record")

    before = files_digest(knowledge)
    answer = run_step(executable, workspace, "retrieve", f"Look up {marker} in Orbit Garden. "
                      "Return its exact saved value and relative source path. Read only.", timeout)
    if (marker not in answer or re.search(r"\btray_count=7\b", answer) is None
            or authority_key not in answer or files_digest(knowledge) != before):
        raise RuntimeError("retrieve: answer or no-write invariant failed")
    passed("retrieve")

    before = files_digest(knowledge)
    run_step(executable, workspace, "correct", f"Correct the fictional Orbit Garden fact {old}: "
             f"the current fact is {new}. Update the existing project authority, mark the earlier value "
             "as superseded history, and verify the correction. Production remains NOT_PROVEN.", timeout)
    body = authority.read_text(encoding="utf-8")
    after = files_digest(knowledge)
    if (old not in body or new not in body or "NOT_PROVEN" not in body
            or not preserves_original_lines(original, body)):
        raise RuntimeError("correct: old or new value or evidence boundary missing")
    if {p for p in set(before) | set(after) if before.get(p) != after.get(p)} != {authority_key}:
        raise RuntimeError("correct: modified unexpected knowledge files")
    # This lexical check does not replace review of the saved note's meaning.
    if not any(word in body.lower() for word in ("superseded", "historical", "已取代", "已被", "旧值")):
        raise RuntimeError("correct: superseded history label missing; inspect saved note")
    passed("correct-preserving-history")

    before = files_digest(knowledge)
    ephemeral = "DO_NOT_SAVE_" + secrets.token_hex(8)
    run_step(executable, workspace, "do-not-save", f"This is just a conversation: {ephemeral}. "
             "Do not record this, do not save any profile or progress, and do not modify any file. "
             "Briefly acknowledge my choice.", timeout)
    if files_digest(knowledge) != before:
        raise RuntimeError("do-not-save: knowledge changed")
    passed("do-not-save")

    before = files_digest(knowledge)
    run_step(executable, workspace, "html", "Generate the HTML knowledge overview using the "
             "installed HanOS generator and configured knowledge home. Do not edit Markdown. "
             "Report the output path and note, repository, connection and unresolved counts.", timeout)
    after = files_digest(knowledge)
    changed = {p for p in set(before) | set(after) if before.get(p) != after.get(p)}
    if changed != {".hanos/knowledge-overview.html"}:
        raise RuntimeError("html: unexpected output or knowledge modification")
    html = (knowledge / ".hanos/knowledge-overview.html").read_text(encoding="utf-8")
    if "midnight-atlas" not in html or marker not in html:
        raise RuntimeError("html: missing actual generated view or saved demo fact")
    native.validate_codex_read(
        (workspace / "html.trace.jsonl").read_text(encoding="utf-8"),
        "INSTALLED_GENERATOR_EXECUTION_NOT_PROVEN",
        (".agents/skills/hanos/scripts/generate_html.py",), ("HANOS_HTML=PASS",),
    )
    passed("html-generation")
    print("HANOS_NATIVE_JOURNEY=PASS", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="New empty local directory; logs stay private")
    parser.add_argument("--timeout", type=int, default=240, help="Per-step timeout in seconds")
    args = parser.parse_args()
    try:
        evaluate(args.workspace.expanduser().resolve(), args.timeout)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"HANOS_NATIVE_JOURNEY_ERROR={error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
