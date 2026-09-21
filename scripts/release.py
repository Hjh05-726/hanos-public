#!/usr/bin/env python3
"""Export an explicit public snapshot or build an archive from a clean checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def public_files(root: Path) -> list[str]:
    lines = (root / "release-files.txt").read_text(encoding="utf-8").splitlines()
    names = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
    if len(names) != len(set(names)) or not names:
        raise ValueError("release manifest is empty or contains duplicates")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name:
            raise ValueError(f"unsafe manifest path: {name}")
        source = root / name
        if any(part.is_symlink() for part in (source, *source.parents)):
            raise ValueError(f"symlink in public source: {name}")
        if not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"missing or escaping public file: {name}")
    return sorted(names)


def version(root: Path) -> str:
    value = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", value):
        raise ValueError("VERSION must contain a semantic version")
    return value


def check(root: Path, *, clean: bool = False) -> list[str]:
    names = public_files(root)
    version(root)
    if (root / "LICENSE").read_bytes() != (root / "skills/hanos/LICENSE").read_bytes():
        raise ValueError("root and installed Skill licenses differ")
    checked = subprocess.run(
        [sys.executable, "-B", str(root / "skills/hanos/scripts/generate_html.py"), "--check-template"],
        capture_output=True, text=True, check=False,
    )
    if checked.returncode != 0:
        raise ValueError(f"TEMPLATE_PACKAGE_INVALID: {checked.stderr.strip()}")
    exposed = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    if set(filter(None, exposed)) != set(names):
        raise ValueError("Git file set differs from release-files.txt")
    if clean:
        subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root,
                       check=True, stdout=subprocess.DEVNULL)
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=root).strip():
            raise ValueError("release archives require a clean committed checkout")
    return names


def new_destination(root: Path, output: Path) -> Path:
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output must be a new path; existing files are never replaced")
    resolved = output.resolve()
    root = root.resolve()
    if resolved.is_relative_to(root) or root.is_relative_to(resolved):
        raise ValueError("output must be separate from the source checkout")
    # Refuse parent symlinks rather than creating files through an unexpected alias.
    if any(p.is_symlink() for p in output.parents):
        raise ValueError("output parent must not be a symlink")
    return resolved


def export(root: Path, output: Path) -> Path:
    names = check(root)
    destination = new_destination(root, output)
    destination.mkdir(parents=True)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    return destination


def build(root: Path, output: Path) -> Path:
    names = check(root, clean=True)
    destination = new_destination(root, output)
    label = f"hanos-{version(root)}"
    payload = {name: (root / name).read_bytes() for name in names}
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    destination.mkdir(parents=True)
    archive_path = destination / f"{label}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            entry = zipfile.ZipInfo(f"{label}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    manifest_path = destination / "source-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (archive_path, manifest_path)
    )
    (destination / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "export", "build"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        root = ROOT.resolve()
        if args.operation == "check":
            print(f"HANOS_PUBLIC_FILES={len(check(root))}")
        else:
            if args.output is None:
                parser.error("--output is required for export and build")
            result = export(root, args.output) if args.operation == "export" else build(root, args.output)
            print(f"HANOS_RELEASE_OUTPUT={result}")
        print("HANOS_RELEASE=PASS")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"HANOS_RELEASE_ERROR={error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
