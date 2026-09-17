#!/usr/bin/env python3
"""Generate a real HTML atlas from shipped fictional notes in a new directory."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

from release import ROOT, new_destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination = new_destination(ROOT.resolve(), args.output)
        sample = json.loads((ROOT / "examples/atlas-demo.json").read_text(encoding="utf-8"))
        for name in sample["notes"]:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or path.suffix != ".md":
                raise ValueError("invalid fictional note path")
        for repository in sample["repositories"]:
            identifier = repository["id"]
            if not identifier or not identifier.replace("-", "").isalnum():
                raise ValueError("invalid demo repository id")
        destination.mkdir(parents=True)
        for name, body in sample["notes"].items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        registry = {"version": 1, "repositories": [
            {**repository, "path": str(destination / repository["id"])}
            for repository in sample["repositories"]]}
        (destination / ".hanos").mkdir()
        (destination / ".hanos/repositories.json").write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return subprocess.run([
            sys.executable, str(ROOT / "skills/hanos/scripts/generate_html.py"),
            "--knowledge-home", str(destination), "--output", str(destination / "knowledge-overview.html"),
        ], check=False).returncode
    except (OSError, ValueError, KeyError) as error:
        print(f"HANOS_DEMO_ERROR={error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
