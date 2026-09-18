#!/usr/bin/env python3
"""Generate a local, read-only HTML overview of a HanOS knowledge home.

The HTML is a derived view. It is never read as knowledge and is excluded from
the Markdown scan when it is written into ``.hanos``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import posixpath
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__:
    from .star_layout import prepare_star_atlas
else:
    from star_layout import prepare_star_atlas


GENERATED_FILENAME = "knowledge-overview.html"
MAX_PREVIEW_LENGTH = 240
MARKDOWN_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}
SKIP_DIRECTORY_NAMES = {".git", ".obsidian", ".hanos", "node_modules"}
SKIP_DIRECTORY_NAMES_FOLDED = {name.casefold() for name in SKIP_DIRECTORY_NAMES}


class OverviewError(RuntimeError):
    """Raised when the configured knowledge authority cannot be read safely."""


@dataclass(frozen=True)
class Note:
    path: str
    title: str
    preview: str
    size: int
    modified: str
    link_targets: tuple[str, ...]
    tags: tuple[str, ...]
    content: str


@dataclass(frozen=True)
class Repository:
    repository_id: str
    name: str
    repository_type: str
    status: str
    path: str
    notes: tuple[Note, ...]


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise OverviewError(f"{label} is unreadable: {path}: {error}") from error


def _resolve(path: Path, label: str, *, strict: bool = True) -> Path:
    try:
        return path.expanduser().resolve(strict=strict)
    except (OSError, RuntimeError, ValueError) as error:
        raise OverviewError(f"{label} cannot be resolved: {path}: {error}") from error


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    return value


def _parse_legacy_yaml_scalars(text: str) -> dict[str, Any]:
    """Read the small scalar/nested-map YAML subset used by older HanOS installs.

    Public installations use JSON. This fallback keeps the generated view useful
    for an existing local vault without adding a PyYAML dependency or accepting a
    general-purpose YAML execution surface.
    """

    values: dict[str, Any] = {}
    parents: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if stripped.startswith("-"):
            continue
        key, separator, raw_value = stripped.partition(":")
        if not separator or not key.strip():
            continue
        while parents and indent <= parents[-1][0]:
            parents.pop()
        key = key.strip()
        value = raw_value.strip()
        if not value:
            parents.append((indent, key))
            continue
        dotted = ".".join([parent for _, parent in parents] + [key])
        values[dotted] = _parse_scalar(value)
    return values


def _load_document(path: Path, label: str) -> dict[str, Any]:
    text = _read_text(path, label)
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _parse_legacy_yaml_scalars(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OverviewError(f"{label} is invalid JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise OverviewError(f"{label} must be a JSON object: {path}")
    return value


def resolve_knowledge_home(config_path: Path | None, knowledge_home: Path | None) -> Path:
    if config_path is not None and knowledge_home is not None:
        raise OverviewError("choose either --config or --knowledge-home, not both")
    if config_path is None and knowledge_home is None:
        raise OverviewError("one of --config or --knowledge-home is required")
    if knowledge_home is not None:
        root = _resolve(knowledge_home, "knowledge home")
    else:
        config = _resolve(config_path, "HanOS config")
        document = _load_document(config, "HanOS config")
        configured = document.get("knowledge_home")
        if not isinstance(configured, str):
            configured = document.get("knowledge_base.root")
        if not isinstance(configured, str) or not configured.strip():
            raise OverviewError(
                f"HanOS config has no absolute knowledge_home: {config}"
            )
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            raise OverviewError(
                f"HanOS config has no absolute knowledge_home: {config}"
            )
        root = _resolve(configured_path, "configured knowledge home")
    if not root.is_dir():
        raise OverviewError(f"knowledge home is not a directory: {root}")
    return root


def _registry_path(root: Path) -> Path:
    for candidate in (
        root / ".hanos/repositories.json",
        root / ".hanos/repositories.yaml",
        root / ".hanos/repositories.yml",
    ):
        if candidate.is_file():
            resolved = _resolve(candidate, "repository registry")
            if not _inside(resolved, root):
                raise OverviewError(f"repository registry escapes the knowledge home: {candidate}")
            return resolved
    raise OverviewError(
        "repository registry is missing; expected .hanos/repositories.json"
    )


def _load_repositories(root: Path) -> list[Any]:
    registry = _registry_path(root)
    text = _read_text(registry, "repository registry")
    if registry.suffix.lower() in {".yaml", ".yml"}:
        # The legacy registry has a list of flat repository maps. Parse only the
        # fields used by the protocol; JSON remains the canonical format.
        repositories: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        in_aliases = False
        version: Any = None
        for raw_line in text.splitlines():
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            stripped = raw_line.strip()
            if stripped.startswith("version:") and current is None:
                version = _parse_scalar(stripped.partition(":")[2])
                continue
            if stripped == "repositories:":
                continue
            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if ":" not in value:
                    if current is not None and in_aliases:
                        current.setdefault("aliases", []).append(_parse_scalar(value))
                    continue
                current = {}
                repositories.append(current)
                in_aliases = False
                key, _, raw_value = value.partition(":")
                current[key.strip()] = _parse_scalar(raw_value)
                continue
            if current is None or ":" not in stripped:
                continue
            key, _, raw_value = stripped.partition(":")
            key = key.strip()
            if key == "aliases" and not raw_value.strip():
                current["aliases"] = []
                in_aliases = True
            else:
                in_aliases = False
                current[key] = _parse_scalar(raw_value)
        if version != 1 or not repositories:
            raise OverviewError(f"repository registry has no repositories list: {registry}")
        return repositories
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise OverviewError(f"repository registry is invalid JSON: {registry}: {error}") from error
    if (
        not isinstance(document, dict)
        or document.get("version") != 1
        or not isinstance(document.get("repositories"), list)
        or not document["repositories"]
    ):
        raise OverviewError(f"repository registry has no repositories list: {registry}")
    return document["repositories"]


def _repository_root(root: Path, item: dict[str, Any]) -> tuple[Path, str, str, str, str]:
    required = ("id", "name", "type", "path")
    missing = [key for key in required if not isinstance(item.get(key), str) or not item[key].strip()]
    if missing:
        raise OverviewError(f"active repository is missing fields: {', '.join(missing)}")
    repository_id = str(item["id"])
    name = str(item["name"])
    repository_type = str(item["type"])
    if repository_type not in {"global", "project"}:
        raise OverviewError(
            f"repository {repository_id} has unsupported type: {repository_type}"
        )
    status = str(item.get("status", "active"))
    raw_path = Path(str(item["path"])).expanduser()
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = _resolve(candidate, f"repository {repository_id}")
    if not _inside(resolved, root):
        raise OverviewError(f"repository {repository_id} escapes the knowledge home: {candidate}")
    if not resolved.exists():
        raise OverviewError(f"repository {repository_id} does not exist: {resolved}")
    if not resolved.is_dir() and not resolved.is_file():
        raise OverviewError(f"repository {repository_id} is not a file or directory: {resolved}")
    return resolved, repository_id, name, repository_type, status


def _markdown_files(repository_path: Path, root: Path) -> Iterable[Path]:
    if repository_path.is_file():
        if (
            repository_path.suffix.lower() in MARKDOWN_SUFFIXES
            and not any(
                part.casefold() in SKIP_DIRECTORY_NAMES_FOLDED
                for part in repository_path.relative_to(root).parts
            )
        ):
            yield repository_path
        return
    for path in sorted(repository_path.rglob("*")):
        if any(
            part.casefold() in SKIP_DIRECTORY_NAMES_FOLDED
            for part in path.relative_to(root).parts
        ):
            continue
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if (
            _inside(resolved, root)
            and resolved.is_file()
            and resolved.suffix.lower() in MARKDOWN_SUFFIXES
            and not any(
                part.casefold() in SKIP_DIRECTORY_NAMES_FOLDED
                for part in resolved.relative_to(root).parts
            )
        ):
            yield resolved


def _title_and_preview(text: str, fallback: str) -> tuple[str, str]:
    lines = text.splitlines()
    title = ""
    for line in lines:
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line.strip())
        if match:
            title = match.group(1).strip()
            break
    if not title:
        title = fallback
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith(("- ", "* ", "> ")):
            stripped = stripped[2:].strip()
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    preview = re.sub(r"\s+", " ", paragraphs[0] if paragraphs else "").strip()
    if len(preview) > MAX_PREVIEW_LENGTH:
        preview = preview[: MAX_PREVIEW_LENGTH - 1].rstrip() + "…"
    return title, preview


def _extract_links_and_tags(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract Obsidian-compatible links and inline tags without resolving them."""

    wiki_links = re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", text)
    markdown_links = re.findall(
        r"\[[^\]]+\]\(([^)\s#]+(?:\.md|\.markdown|\.mdown|\.mkdn)(?:#[^)]*)?)\)",
        text,
        flags=re.IGNORECASE,
    )
    targets: list[str] = []
    for target in (*wiki_links, *markdown_links):
        normalized = target.strip()
        if normalized and not re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)", normalized):
            targets.append(normalized)
    tags = re.findall(r"(?<![\w#])#([A-Za-z0-9_\-/\u3400-\u9fff]+)", text)
    return tuple(dict.fromkeys(targets)), tuple(dict.fromkeys(tags))


def _note(path: Path, root: Path) -> Note:
    text = _read_text(path, "Markdown note")
    try:
        stat = path.stat()
    except OSError as error:
        raise OverviewError(f"Markdown note is unreadable: {path}: {error}") from error
    relative = path.relative_to(root).as_posix()
    title, preview = _title_and_preview(text, path.stem)
    link_targets, tags = _extract_links_and_tags(text)
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")
    return Note(relative, title, preview, stat.st_size, modified, link_targets, tags, text)


def _link_key(value: str) -> str:
    value = value.strip().replace("\\", "/")
    value = re.sub(r"\.(?:md|markdown|mdown|mkdn)$", "", value, flags=re.IGNORECASE)
    while value.startswith("./"):
        value = value[2:]
    return value.casefold()


def _relative_link_key(note_path: str, target: str) -> str:
    """Resolve a local link from the directory containing its source note."""

    target = target.strip().replace("\\", "/")
    if target.startswith("/"):
        candidate = target.lstrip("/")
    else:
        candidate = posixpath.join(posixpath.dirname(note_path), target)
    normalized = posixpath.normpath(candidate)
    if normalized == ".." or normalized.startswith("../"):
        return ""
    return _link_key(normalized)


def _constellation_positions(
    nodes: list[dict[str, Any]], edges: list[dict[str, str]],
) -> dict[str, tuple[float, float]]:
    """Settle related stars once at generation time, without a circular orbit.

    Stable per-note anchors keep isolated stars scattered and avoid a central
    gravity well. Local repulsion leaves space to click; actual links draw
    constellations together. A spatial grid bounds the repulsion neighborhood.
    """
    ordered = sorted(nodes, key=lambda node: node["id"])
    if not ordered:
        return {}
    if len(ordered) == 1:
        return {ordered[0]["id"]: (500.0, 280.0)}
    points: dict[str, list[float]] = {}
    anchors: dict[str, tuple[float, float]] = {}
    for node in ordered:
        digest = hashlib.sha256(node["id"].encode("utf-8")).digest()
        x = 70 + int.from_bytes(digest[:4], "big") / 2**32 * 830
        y = 50 + int.from_bytes(digest[4:8], "big") / 2**32 * 455
        points[node["id"]] = [x, y]
        anchors[node["id"]] = (x, y)
    links = sorted({
        tuple(sorted((edge["source"], edge["target"]))) for edge in edges
        if edge["source"] in points and edge["target"] in points
        and edge["source"] != edge["target"]
    })
    degrees = {node_id: 0 for node_id in points}
    for source, target in links:
        degrees[source] += 1
        degrees[target] += 1

    reach = 120.0
    # Spend fewer settling passes on larger vaults to reduce generation cost,
    # without putting an animation or a force simulation in the browser.
    iterations = max(12, min(240, 24000 // len(ordered)))
    for iteration in range(iterations):
        cells: dict[tuple[int, int], list[str]] = {}
        forces: dict[str, list[float]] = {}
        for node_id, (x, y) in points.items():
            cells.setdefault((int(x // reach), int(y // reach)), []).append(node_id)
            ax, ay = anchors[node_id]
            forces[node_id] = [(ax - x) * .009, (ay - y) * .009]
        for node_id, (x, y) in points.items():
            column, row = int(x // reach), int(y // reach)
            for cx in range(column - 1, column + 2):
                for cy in range(row - 1, row + 2):
                    for other_id in cells.get((cx, cy), []):
                        if other_id <= node_id:
                            continue
                        ox, oy = points[other_id]
                        dx, dy = x - ox, y - oy
                        distance = math.hypot(dx, dy)
                        if distance >= reach:
                            continue
                        if distance < .001:
                            dx, dy, distance = 1.0, 0.0, 1.0
                        push = 3.8 * (1 - distance / reach)**2 + max(0, 54 - distance) * .8
                        fx, fy = dx / distance * push, dy / distance * push
                        forces[node_id][0] += fx
                        forces[node_id][1] += fy
                        forces[other_id][0] -= fx
                        forces[other_id][1] -= fy
        for source, target in links:
            sx, sy = points[source]
            tx, ty = points[target]
            dx, dy = tx - sx, ty - sy
            distance = max(.001, math.hypot(dx, dy))
            pull = (distance - 120) * .018 / math.sqrt(max(degrees[source], degrees[target]))
            fx, fy = dx / distance * pull, dy / distance * pull
            forces[source][0] += fx
            forces[source][1] += fy
            forces[target][0] -= fx
            forces[target][1] -= fy
        limit = 4 * (1 - iteration / iterations) + .2
        for node_id, point in points.items():
            fx, fy = forces[node_id]
            factor = min(1, limit / max(.001, math.hypot(fx, fy)))
            point[0] = min(910, max(50, point[0] + fx * factor))
            point[1] = min(510, max(45, point[1] + fy * factor))
    return {node_id: (round(x, 2), round(y, 2)) for node_id, (x, y) in points.items()}


def _build_graph(repositories: list[Repository], root: Path) -> dict[str, Any]:
    """Build note and tag nodes from the local Markdown corpus.

    Link resolution intentionally stays conservative: a link resolves when it
    matches a unique relative path, stem, title, or basename. Unresolved links
    remain visible as dashed nodes so broken knowledge connections are easy to
    find without inventing a second source of truth.
    """

    notes = [note for repository in repositories for note in repository.notes]
    note_by_key: dict[str, list[Note]] = {}
    note_by_path: dict[str, list[Note]] = {}
    for note in notes:
        path_key = _link_key(Path(note.path).with_suffix("").as_posix())
        note_by_path.setdefault(path_key, []).append(note)
        keys = {
            _link_key(Path(note.path).name),
            _link_key(Path(note.path).stem),
            _link_key(note.title),
        }
        for key in keys:
            if key:
                note_by_key.setdefault(key, []).append(note)

    nodes: dict[str, dict[str, Any]] = {}
    for repository in repositories:
        for note in repository.notes:
            node_id = f"note:{note.path}"
            nodes[node_id] = {
                "id": node_id,
                "label": note.title,
                "path": note.path,
                "kind": "note",
                "repository": repository.name,
                "tags": list(note.tags),
                "href": (root / note.path).resolve().as_uri(),
                "content": note.content,
            }

    edges: list[dict[str, str]] = []
    edge_keys: set[tuple[str, str]] = set()
    for note in notes:
        source_id = f"note:{note.path}"
        for raw_target in note.link_targets:
            target_key = _link_key(raw_target.split("#", 1)[0])
            relative_key = _relative_link_key(note.path, raw_target.split("#", 1)[0])
            matches = note_by_path.get(relative_key, []) if relative_key else []
            if len(matches) != 1:
                matches = note_by_path.get(target_key, [])
            if len(matches) != 1:
                matches = note_by_key.get(target_key, [])
            target = matches[0] if len(matches) == 1 else None
            if target is None:
                unresolved_key = target_key or raw_target.casefold()
                target_id = f"unresolved:{unresolved_key}"
                nodes.setdefault(
                    target_id,
                    {
                        "id": target_id,
                        "label": raw_target,
                        "path": raw_target,
                        "kind": "unresolved",
                        "repository": "",
                        "tags": [],
                        "href": "",
                        "content": "",
                    },
                )
            else:
                target_id = f"note:{target.path}"
            edge_key = (source_id, target_id)
            if edge_key not in edge_keys and source_id != target_id:
                edge_keys.add(edge_key)
                edges.append({"source": source_id, "target": target_id})

    tag_nodes: dict[str, str] = {}
    for note in notes:
        source_id = f"note:{note.path}"
        for tag in note.tags:
            tag_key = tag.casefold()
            tag_id = tag_nodes.setdefault(tag_key, f"tag:{tag_key}")
            nodes.setdefault(
                tag_id,
                {
                    "id": tag_id,
                    "label": f"#{tag}",
                    "path": "",
                    "kind": "tag",
                    "repository": "",
                    "tags": [],
                    "href": "",
                    "content": "",
                },
            )
            edge_key = (source_id, tag_id)
            if edge_key not in edge_keys:
                edge_keys.add(edge_key)
                edges.append({"source": source_id, "target": tag_id})

    degree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    for node_id, node in nodes.items():
        node["degree"] = degree[node_id]
    ordered_nodes = sorted(nodes.values(), key=lambda node: (node["kind"], node["label"].casefold()))
    positions = _constellation_positions(ordered_nodes, edges)
    # Spread the constellation horizontally before reserving title space, so
    # both the nodes and their collision-free labels fit the wide reading panel.
    positions = {node_id: (x * 1.4, y * .8) for node_id, (x, y) in positions.items()}
    atlas = prepare_star_atlas(ordered_nodes, positions)
    width = max(1000.0, atlas["width"], atlas["height"] * 2)
    height = width / 2
    for node in ordered_nodes:
        node.update(atlas["nodes"][node["id"]])
        node["x"] += (width - atlas["width"]) / 2
        node["y"] += (height - atlas["height"]) / 2
    return {
        "nodes": ordered_nodes,
        "edges": edges,
        "width": width, "height": height,
        "font_size": atlas["font_size"], "line_height": atlas["line_height"],
        "note_count": len(notes),
        "connection_count": len(edges),
        "unresolved_count": sum(1 for node in nodes.values() if node["kind"] == "unresolved"),
    }


def collect_overview(root: Path) -> dict[str, Any]:
    repositories: list[Repository] = []
    seen_ids: set[str] = set()
    selectors: dict[str, str] = {}
    for item in _load_repositories(root):
        if not isinstance(item, dict):
            raise OverviewError("repository registry contains a non-object entry")
        status = item.get("status", "active")
        if not isinstance(status, str) or not status.strip():
            raise OverviewError("repository registry entry has an invalid status")
        if status != "active":
            continue
        resolved, repository_id, name, repository_type, status = _repository_root(root, item)
        if repository_id in seen_ids:
            raise OverviewError(f"duplicate active repository id: {repository_id}")
        aliases = item.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise OverviewError(f"repository {repository_id} aliases must be a list of strings")
        for selector in (repository_id, name, *aliases):
            normalized = selector.strip().casefold()
            if not normalized:
                raise OverviewError(f"repository {repository_id} has an empty selector")
            previous = selectors.get(normalized)
            if previous is not None and previous != repository_id:
                raise OverviewError(
                    f"active repository selector is ambiguous: {selector} ({previous}, {repository_id})"
                )
            selectors[normalized] = repository_id
        seen_ids.add(repository_id)
        notes = tuple(_note(path, root) for path in _markdown_files(resolved, root))
        repositories.append(
            Repository(
                repository_id=repository_id,
                name=name,
                repository_type=repository_type,
                status=status,
                path=resolved.relative_to(root).as_posix(),
                notes=notes,
            )
        )
    repositories.sort(key=lambda repository: (repository.repository_type, repository.name.casefold()))
    all_notes = [note for repository in repositories for note in repository.notes]
    latest = max((note.modified for note in all_notes), default=None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "knowledge_home": str(root),
        "repository_count": len(repositories),
        "note_count": len(all_notes),
        "total_bytes": sum(note.size for note in all_notes),
        "latest_modified": latest,
        "repositories": [
            {
                "id": repository.repository_id,
                "name": repository.name,
                "type": repository.repository_type,
                "status": repository.status,
                "path": repository.path,
                "notes": [
                    {
                        **note.__dict__,
                        "link_targets": list(note.link_targets),
                        "tags": list(note.tags),
                    }
                    for note in repository.notes
                ],
            }
            for repository in repositories
        ],
        "graph": _build_graph(repositories, root),
    }


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_html(data: dict[str, Any]) -> str:
    repositories = data["repositories"]
    graph = data["graph"]
    repository_cards: list[str] = []
    for repository in repositories:
        notes = repository["notes"]
        note_markup = "".join(
            "<li class=\"note\" data-search=\"{search}\" data-node-id=\"note:{path}\">"
            "<strong>{title}</strong>"
            "<span class=\"path\">{path}</span>"
            "<p>{preview}</p>"
            "</li>".format(
                search=_esc(" ".join((note["title"], note["path"], note["preview"]))),
                title=_esc(note["title"]),
                path=_esc(note["path"]),
                preview=_esc(note["preview"] or "暂无摘要"),
            )
            for note in notes
        )
        if not note_markup:
            note_markup = '<li class="empty">这个仓库暂时没有 Markdown 笔记。</li>'
        repository_cards.append(
            "<article class=\"repository\" data-search=\"{search}\">"
            "<div class=\"repository-header\">"
            "<div><p class=\"eyebrow\">{type}</p><h2>{name}</h2>"
            "<p class=\"path\">{path}</p></div>"
            "<span class=\"count\">{count} 篇</span></div>"
            "<ul class=\"notes\">{notes}</ul></article>".format(
                search=_esc(" ".join((repository["name"], repository["type"], repository["path"]))),
                type=_esc(repository["type"]),
                name=_esc(repository["name"]),
                path=_esc(repository["path"]),
                count=len(notes),
                notes=note_markup,
            )
        )
    if not repository_cards:
        repository_cards.append('<p class="empty">注册表中没有 active 仓库。</p>')
    payload = (
        json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("</", "<\\/")
    )
    latest = data["latest_modified"] or "暂无"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HanOS 知识库总览</title>
  <style>
    /* Shared offline theme: a midnight atlas, shipped inside every generated file.
       Atmospheric layers are static; only the existing connection trails move. */
    :root {{ color-scheme:dark; --ink:#e2edf5; --muted:#97adbf; --line:#2c4055; --accent:#8ed7ee; --blue:#8ed7ee; --paper:#080f1c; --panel:#0d1929; --card:#101e30; --radius:20px; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:radial-gradient(ellipse at 8% 0%,#14263c 0,transparent 45%),var(--paper); color:var(--ink); font:15px/1.6 "Avenir Next","Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; -webkit-font-smoothing:antialiased; }}
    ::selection {{ background:#31536b; color:#fff; }}
    main {{ width:min(1440px,calc(100% - 80px)); margin:0 auto; padding:36px 0 48px; }}
    h1,h2,p {{ margin:0; }}
    header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:24px; }}
    .brand {{ display:flex; align-items:center; gap:12px; color:var(--accent); font-size:11px; font-weight:600; letter-spacing:.2em; margin-bottom:14px; }}
    .brand-mark {{ font-size:26px; line-height:1; text-shadow:0 0 18px #8ed7ee66; }}
    h1 {{ font-size:clamp(28px,3vw,40px); font-weight:500; line-height:1.3; letter-spacing:.05em; }}
    h2 {{ font-size:19px; line-height:1.4; font-weight:500; }}
    .lede {{ color:var(--muted); margin-top:9px; font-size:14px; letter-spacing:.035em; }}
    .meta {{ color:var(--muted); font-size:11px; text-align:right; line-height:1.9; font-variant-numeric:tabular-nums; }}
    .meta strong {{ display:block; color:var(--ink); font-weight:400; font-size:13px; margin-bottom:5px; }}
    .search {{ display:grid; grid-template-columns:max-content minmax(0,440px); align-items:center; gap:16px; margin:28px 0 20px; }}
    .search label {{ color:var(--muted); font-size:12px; letter-spacing:.08em; }}
    input {{ width:100%; min-width:0; border:1px solid var(--line); border-radius:10px; padding:11px 15px; font:inherit; font-size:13px; color:var(--ink); background:#0d1929; transition:border-color .18s ease,box-shadow .18s ease; }}
    #search-status, #search-results {{ grid-column:1 / -1; }}
    #search-status {{ margin:0; color:var(--muted); font-size:13px; }}
    #search-results {{ max-height:240px; overflow:auto; }}
    .search-result {{ display:block; width:100%; text-align:left; white-space:normal; margin:6px 0; overflow-wrap:anywhere; }}
    .search-result span {{ display:block; color:var(--muted); font-size:12px; margin-top:5px; }}
    .graph-node.search-muted, .graph-edge.search-muted {{ opacity:.12; }}
    .graph-node.search-match text {{ fill:#fff; }}
    .graph-node.search-match .node-star {{ opacity:1; filter:drop-shadow(0 0 5px #8ed7ee); }}
    input::placeholder {{ color:var(--muted); }}
    input:focus {{ border-color:var(--accent); box-shadow:0 0 0 4px #8ed7ee0d; }}
    input:focus-visible,button:focus-visible,a:focus-visible {{ outline:2px solid var(--accent); outline-offset:3px; }}
    button {{ border:1px solid var(--line); border-radius:8px; background:#132337; color:var(--ink); min-height:36px; padding:7px 12px; font:inherit; font-size:12px; line-height:1.4; white-space:nowrap; cursor:pointer; transition:background .18s ease,border-color .18s ease,color .18s ease; }}
    button:hover {{ background:#20394d; border-color:#54768b; color:#fff; }}
    button:active {{ transform:translateY(1px); }}
    #graph-fullscreen {{ background:#a5e1ef; color:#102c3d; border-color:#a5e1ef; }}
    #graph-fullscreen:hover {{ background:#c7edf5; border-color:#c7edf5; }}
    #graph-reset {{ background:transparent; color:var(--muted); }}
    .graph-panel {{ overflow:hidden; border:1px solid #354b61; border-radius:var(--radius); background:var(--panel); margin-bottom:28px; box-shadow:0 24px 80px #0004,inset 0 1px #ffffff08; }}
    .graph-canvas {{ position:relative; display:grid; width:100%; min-width:0; grid-template-columns:minmax(0,1fr); grid-template-rows:auto minmax(0,1fr) auto; height:60vh; height:60dvh; background:var(--panel); }}
    .graph-panel.is-expanded {{ position:fixed; z-index:10; inset:0; height:100dvh; margin:0; border:0; border-radius:0; overflow:auto; }}
    .graph-panel.is-expanded .graph-canvas {{ width:100%; height:100%; min-height:320px; aspect-ratio:auto; }}
    .graph-header,.graph-footer {{ position:relative; z-index:1; background:transparent; }}
    .graph-header {{ display:flex; justify-content:space-between; align-items:center; gap:20px; padding:22px 26px 18px; border-bottom:1px solid #8ed7ee14; }}
    .graph-header h2 {{ font-size:17px; letter-spacing:.08em; }}
    .graph-header p {{ color:var(--muted); font-size:12px; margin-top:6px; }}
    .graph-actions {{ display:flex; min-width:0; max-width:100%; gap:7px; align-items:center; flex-wrap:wrap; }}
    .graph-actions .zoom-button {{ width:36px; padding:5px 0; font-size:18px; }}
    .graph-stage {{ position:relative; z-index:0; min-width:0; min-height:0; overflow:hidden; background:radial-gradient(ellipse at 28% 42%,#20577338 0,transparent 52%),radial-gradient(ellipse at 78% 64%,#34486838 0,transparent 48%),#0b1727; }}
    .graph-stage::before {{ content:""; position:absolute; inset:0; pointer-events:none; background-image:linear-gradient(#b8dcff04 1px,transparent 1px),linear-gradient(90deg,#b8dcff04 1px,transparent 1px); background-size:72px 72px; }}
    .graph-stage::after {{ content:""; position:absolute; inset:0; pointer-events:none; box-shadow:inset 0 0 100px #080f1c55; }}
    .graph-stage > svg {{ width:100%; height:100%; display:block; cursor:grab; touch-action:none; }}
    .graph-stage > svg:active {{ cursor:grabbing; }}
    .background-star {{ fill:#b8e4f8; pointer-events:none; }}
    .graph-edge {{ stroke:#6b98b4; stroke-width:.8; opacity:.36; pointer-events:none; transition:opacity .15s ease; }}
    .graph-edge line {{ vector-effect:non-scaling-stroke; }}
    .graph-edge.related {{ stroke:var(--accent); opacity:.85; stroke-width:1.2; }}
    .graph-edge.unresolved .edge-thread {{ stroke-dasharray:3 5; }}
    .edge-flow {{ stroke:#a2e2f7; stroke-width:1.5; stroke-linecap:round; stroke-dasharray:6 94; opacity:.75; animation:edge-flow-travel var(--flow-duration,9s) linear infinite; animation-delay:var(--flow-delay,0s); }}
    .graph-edge.related .edge-flow {{ opacity:1; stroke-width:1.8; }}
    .graph-edge.muted .edge-flow {{ opacity:0; animation-play-state:paused; }}
    .motion-paused .edge-flow,.reader-open .edge-flow {{ animation-play-state:paused; }}
    @keyframes edge-flow-travel {{ to {{ stroke-dashoffset:-100; }} }}
    .graph-node {{ cursor:pointer; }}
    .node-star {{ pointer-events:none; transition:opacity .15s ease; }}
    .graph-node .node-hit {{ fill:transparent; stroke:none; pointer-events:all; }}
    .star-halo {{ fill:#8ed7ee; opacity:.12; filter:blur(3px); }}
    .star-rays {{ fill:#9ddff2; stroke:none; }}
    .star-core {{ fill:#f9fcfe; stroke:#b8eaff; stroke-width:.3; }}
    .graph-node.tone-white .star-rays {{ fill:#e1eaf6; }}
    .graph-node.tone-white .star-halo {{ opacity:.1; }}
    .graph-node.tag .star-rays {{ fill:#84a9c7; }}
    .graph-node.unresolved .star-rays {{ fill:none; stroke:#8297b0; stroke-width:.8; }}
    .graph-node.unresolved .star-halo {{ opacity:.04; }}
    .graph-node.focused .star-rays,.graph-node.related .star-rays {{ fill:#d1f6ff; }}
    .graph-node.focused .star-halo {{ opacity:.26; }}
    .graph-node:focus-visible {{ outline:none; }}
    .graph-node:focus-visible .star-rays {{ stroke:var(--ink); stroke-width:.7; }}
    .graph-node text {{ fill:#d3e3ef; font-weight:400; stroke:#0b1727; stroke-width:1.5; stroke-linejoin:round; paint-order:stroke fill; white-space:pre; pointer-events:none; }}
    .graph-node.focused text,.graph-node.related text {{ fill:#f1fcff; }}
    .graph-node.muted .node-star {{ opacity:.35; }} .graph-edge.muted {{ opacity:.1; }}
    .graph-footer {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:15px 26px; border-top:1px solid #8ed7ee14; font-size:12px; color:var(--muted); }}
    .graph-legend {{ display:flex; gap:18px; flex-wrap:wrap; }}
    .graph-hints {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; }}
    .motion-button {{ padding:4px 8px; font-size:12px; color:var(--muted); }}
    .legend-dot {{ display:inline-block; width:7px; height:7px; margin-right:6px; border-radius:50%; background:#b1e5f4; border:1px solid var(--accent); }}
    .legend-dot.tag {{ background:#698ca9; }} .legend-dot.unresolved {{ background:transparent; border-style:dashed; }}
    .graph-empty {{ position:absolute; inset:0; display:grid; place-content:center; text-align:center; color:var(--muted); padding:24px; pointer-events:none; }}
    .graph-empty[hidden] {{ display:none; }}
    .graph-empty strong {{ color:var(--ink); font-size:18px; font-weight:500; margin-bottom:6px; }}
    .stats {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:24px; margin:0 0 48px; padding:8px 0 26px; border-bottom:1px solid var(--line); }}
    .stat {{ padding:0 24px; border-left:1px solid var(--line); }}
    .stat:first-child {{ border-left:0; padding-left:0; }}
    .stat strong {{ display:block; font-size:clamp(20px,2.2vw,28px); font-weight:400; letter-spacing:.025em; font-variant-numeric:tabular-nums; margin-bottom:4px; }}
    .stat span,.path {{ color:var(--muted); font-size:12px; overflow-wrap:anywhere; }}
    .repositories {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:24px; align-items:start; }}
    .repository {{ min-width:0; border:1px solid var(--line); border-radius:16px; padding:26px; background:linear-gradient(145deg,#14243999,#0d182799); }}
    .repository-header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; padding-bottom:20px; margin-bottom:22px; border-bottom:1px solid var(--line); }}
    .repository-header > div {{ min-width:0; }}
    .repository-header h2 {{ overflow-wrap:anywhere; }}
    .repository-header .path {{ margin-top:4px; }}
    .eyebrow {{ color:var(--muted); font-size:12px; margin-bottom:4px; }}
    .count {{ white-space:nowrap; color:var(--accent); font-size:12px; padding:3px 8px; background:#8ed7ee0b; border:1px solid #8ed7ee26; border-radius:6px; }}
    .notes {{ list-style:none; padding:0; margin:0; display:grid; gap:24px; }}
    .note {{ min-width:0; }}
    .note strong {{ display:block; font-size:15px; font-weight:500; line-height:1.7; overflow-wrap:anywhere; margin-bottom:4px; }}
    .note p {{ color:#b0c2d0; font-size:13px; line-height:1.85; margin-top:8px; overflow-wrap:anywhere; }}
    .empty {{ color:var(--muted); padding:12px 0; }}
    .hidden {{ display:none; }}
    footer {{ margin-top:38px; padding-top:20px; border-top:1px solid var(--line); color:var(--muted); font-size:12px; }}
    .reader-backdrop {{ display:none; }}
    .note-reader {{ position:fixed; z-index:2; inset:0; width:100%; height:100dvh; overflow:auto; background:var(--panel); visibility:hidden; opacity:0; pointer-events:none; transition:opacity .16s ease; }}
    .note-reader[hidden] {{ display:none; }}
    .note-reader.visible {{ opacity:1; visibility:visible; pointer-events:auto; }}
    .reader-inner {{ width:min(740px,calc(100% - 48px)); margin:0 auto; padding:20px 0 72px; }}
    .reader-top {{ position:sticky; z-index:1; top:0; display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 0; margin-bottom:40px; background:var(--panel); border-bottom:1px solid var(--line); }}
    .reader-label {{ color:var(--muted); font-size:13px; margin-bottom:8px; }}
    .reader-title {{ font-size:clamp(25px,4vw,36px); line-height:1.5; font-weight:600; overflow-wrap:anywhere; }}
    .reader-path {{ color:var(--muted); font-size:12px; margin-top:12px; overflow-wrap:anywhere; }}
    .reader-content {{ margin-top:36px; padding-top:28px; border-top:1px solid var(--line); color:#c4d4e0; font-size:16px; line-height:2; overflow-wrap:anywhere; }}
    .reader-content h1,.reader-content h2,.reader-content h3 {{ color:var(--ink); line-height:1.5; margin:1.5em 0 .5em; }}
    .reader-content h1 {{ font-size:24px; }} .reader-content h2 {{ font-size:21px; }} .reader-content h3 {{ font-size:18px; }}
    .reader-content p {{ margin:0 0 1em; }} .reader-content ul {{ padding-left:1.4em; margin:0 0 1em; }}
    .reader-content blockquote {{ margin:1em 0; padding-left:16px; border-left:2px solid var(--accent); color:var(--muted); }}
    .reader-content code {{ background:#1c3348; color:#bce9f6; border-radius:4px; padding:2px 5px; font-size:.9em; }}
    @media (max-width:767px) {{
      main {{ width:calc(100% - 32px); padding-top:24px; }}
      .brand {{ margin-bottom:12px; }}
      header {{ display:block; }} h1 {{ font-size:26px; }}
      .meta {{ text-align:left; margin-top:10px; }} .meta br {{ display:none; }} .meta strong {{ display:inline; margin-right:12px; }}
      .search {{ grid-template-columns:1fr; gap:6px; margin:18px 0; }}
      .graph-canvas {{ height:70vh; height:70dvh; }}
      .graph-header {{ align-items:flex-start; flex-direction:column; gap:12px; padding:18px 16px 14px; }}
      .graph-actions {{ width:100%; flex-wrap:wrap; gap:6px; }} .graph-actions button {{ min-height:40px; }} .graph-header p {{ font-size:12px; }}
      .graph-footer {{ padding:10px 16px 16px; align-items:flex-start; flex-direction:column; gap:8px; }}
      .graph-legend {{ gap:12px; }} .stats {{ grid-template-columns:repeat(2,minmax(0,1fr)); gap:18px; }}
      .repositories {{ grid-template-columns:minmax(0,1fr); gap:20px; }}
      .repository {{ padding:20px; }}
      .stat {{ padding:0 12px; }} .stat:nth-child(odd) {{ border-left:0; padding-left:0; }}
      .reader-inner {{ width:calc(100% - 36px); }}
    }}
    @media (prefers-reduced-motion:reduce) {{ *,*::before,*::after {{ transition:none !important; animation:none !important; }} .edge-flow,#graph-motion {{ display:none; }} }}
  </style>
</head>
<body data-theme="midnight-atlas">
  <main>
    <header id="page-header"><div><div class="brand"><span class="brand-mark" aria-hidden="true">✦</span><span>HANOS / KNOWLEDGE ATLAS</span></div><h1>知识库总览</h1><p class="lede">让散落的思考，连成自己的星空。</p></div><p class="meta"><strong>{_esc(data["repository_count"])} 个分类 · {_esc(data["note_count"])} 篇笔记</strong>生成于 {_esc(data["generated_at"])}</p></header>
    <div class="search" id="search-panel"><label for="search">搜索笔记</label><input id="search" type="search" placeholder="搜索笔记、分类或内容…" aria-label="搜索笔记、分类或内容" aria-describedby="search-status"><p id="search-status" role="status" aria-live="polite"></p><div id="search-results" hidden="hidden"></div></div>
    <section class="graph-panel" id="graph-panel" aria-labelledby="graph-title">
      <div class="graph-canvas" id="graph-canvas">
        <div class="graph-header" id="graph-header"><div><h2 id="graph-title">星空知识图谱</h2><p>悬停查看关联，点击阅读笔记。</p></div><div class="graph-actions"><button class="zoom-button" id="graph-zoom-out" type="button" aria-label="缩小图谱">−</button><button class="zoom-button" id="graph-zoom-in" type="button" aria-label="放大图谱">+</button><button id="graph-readable" type="button">清晰查看</button><button id="graph-fit" type="button">回到全图</button><button id="graph-fullscreen" type="button" aria-expanded="false" aria-controls="graph-canvas">全屏查看</button><button id="graph-reset" type="button">清除选择</button></div></div>
        <div class="graph-stage" id="graph-stage">
          <svg id="graph" viewBox="0 0 {graph["width"]} {graph["height"]}" role="group" aria-label="HanOS 星空知识图谱"><g id="graph-viewport"><g id="graph-stars"></g><g id="graph-edges"></g><g id="graph-nodes"></g></g></svg>
          <div class="graph-empty" id="graph-empty" hidden><strong>这里还没有笔记</strong><p>记录一些想法，再打开图谱看看。</p></div>
        </div>
        <div class="graph-footer" id="graph-footer"><div class="graph-legend"><span><i class="legend-dot"></i>笔记 {graph["note_count"]}</span><span><i class="legend-dot tag"></i>主题标签</span><span><i class="legend-dot unresolved"></i>待补充笔记 {graph["unresolved_count"]}</span><span>{graph["connection_count"]} 条联系</span></div><div class="graph-hints"><button id="graph-motion" class="motion-button" type="button">暂停动效</button><span>滚轮缩放，拖动浏览</span></div></div>
  <div id="reader-backdrop" class="reader-backdrop"></div>
  <section id="note-reader" class="note-reader" hidden="hidden" role="dialog" aria-modal="true" aria-label="笔记内容" aria-hidden="true"><div class="reader-inner"><div class="reader-top"><span class="eyebrow">笔记内容</span><button id="reader-close" class="reader-close" type="button" aria-label="返回知识图谱">← 返回图谱</button></div><div id="reader-empty" class="empty">点击图上的笔记星点，就能在这里阅读。</div><div id="reader-body" hidden><p class="reader-label">所在分类</p><h2 id="reader-title" class="reader-title"></h2><p id="reader-path" class="reader-path"></p><article id="reader-content" class="reader-content"></article></div></div></section>
      </div>
    </section>
    <section class="stats" id="overview-stats" aria-label="知识库统计"><div class="stat"><strong>{data["repository_count"]}</strong><span>个分类</span></div><div class="stat"><strong>{data["note_count"]}</strong><span>篇笔记</span></div><div class="stat"><strong>{_format_bytes(data["total_bytes"])}</strong><span>笔记总大小</span></div><div class="stat"><strong>{_esc(latest[:10])}</strong><span>最近更新</span></div></section>
    <section id="repositories" class="repositories">{"".join(repository_cards)}</section>
    <footer id="page-footer">这是根据本地笔记生成的查看页面；内容仍以原笔记为准。</footer>
  </main>
  <script type="application/json" id="hanos-overview-data">{payload}</script>
  <script>
    const search = document.querySelector('#search');
    const cards = [...document.querySelectorAll('.repository')];
    const graphData = JSON.parse(document.querySelector('#hanos-overview-data').textContent);
    const graphSvg = document.querySelector('#graph');
    const viewport = document.querySelector('#graph-viewport');
    const starLayer = document.querySelector('#graph-stars');
    const edgeLayer = document.querySelector('#graph-edges');
    const nodeLayer = document.querySelector('#graph-nodes');
    document.querySelector('#graph-empty').hidden = graphData.graph.nodes.length > 0;
    const reader = document.querySelector('#note-reader');
    const readerBackdrop = document.querySelector('#reader-backdrop');
    const readerEmpty = document.querySelector('#reader-empty');
    const readerBody = document.querySelector('#reader-body');
    const readerTitle = document.querySelector('#reader-title');
    const readerPath = document.querySelector('#reader-path');
    const readerContent = document.querySelector('#reader-content');
    const pageBackground = [...document.querySelectorAll('main > header, .search, .stats, .repositories, main > footer')];
    const graphBackground = ['#graph-header', '#graph-stage', '#graph-footer'].map(selector => document.querySelector(selector));
    const graphPanel = document.querySelector('#graph-panel');
    const fullscreenButton = document.querySelector('#graph-fullscreen');
    let graphExpanded = false, savedBodyOverflow = null;
    function syncInteractionState() {{
      const reading = !reader.hidden;
      pageBackground.forEach(element => element.inert = reading || graphExpanded);
      graphBackground.forEach(element => element.inert = reading);
      const locked = reading || graphExpanded;
      if (locked && savedBodyOverflow === null) {{
        savedBodyOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
      }} else if (!locked && savedBodyOverflow !== null) {{
        document.body.style.overflow = savedBodyOverflow;
        savedBodyOverflow = null;
      }}
    }}
    function setGraphExpanded(expanded) {{
      // Keep the surface in the document's coordinate system, including in
      // embedded browsers where native fullscreen uses a separate host view.
      graphExpanded = expanded;
      graphPanel.classList.toggle('is-expanded', expanded);
      fullscreenButton.textContent = expanded ? '退出全屏' : '全屏查看';
      fullscreenButton.setAttribute('aria-expanded', String(expanded));
      syncInteractionState();
      fullscreenButton.focus();
    }}
    let readerReturnFocus = null;
    const nodeMap = new Map(graphData.graph.nodes.map(node => [node.id, node]));
    const positions = new Map(graphData.graph.nodes.map(node => [node.id, {{ x:node.x, y:node.y }}]));
    const graphWidth = graphData.graph.width, graphHeight = graphData.graph.height;
    const svgEl = (name, attrs) => {{ const element = document.createElementNS('http://www.w3.org/2000/svg', name); Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value)); return element; }};
    let starSeed = (graphData.graph.nodes.length + 17) * 2654435761 >>> 0;
    const nextStar = () => {{ starSeed = (starSeed * 1664525 + 1013904223) >>> 0; return starSeed / 4294967296; }};
    for (let index = 0; index < 36; index += 1) {{
      const star = svgEl('circle', {{ cx: nextStar() * graphWidth, cy: nextStar() * graphHeight, r: .35 + nextStar() * .6, opacity: .1 + nextStar() * .16, class:'background-star' }});
      starLayer.appendChild(star);
    }}
    const edgeElements = [];
    graphData.graph.edges.forEach((edge, index) => {{
      const source = positions.get(edge.source), target = positions.get(edge.target);
      if (!source || !target) return;
      const line = svgEl('g', {{ class:`graph-edge ${{nodeMap.get(edge.target)?.kind === 'unresolved' ? 'unresolved' : ''}}`, 'aria-hidden':'true' }});
      const coordinates = {{ x1:source.x, y1:source.y, x2:target.x, y2:target.y }};
      const thread = svgEl('line', {{ ...coordinates, class:'edge-thread' }});
      // A short travelling highlight leaves the actual connection stationary.
      const flow = svgEl('line', {{ ...coordinates, class:'edge-flow', pathLength:100, style:`--flow-duration:${{8 + index % 5 * .7}}s;--flow-delay:${{-(index % 17) * .43}}s` }});
      line.append(thread, flow);
      line.dataset.source = edge.source; line.dataset.target = edge.target; edgeLayer.appendChild(line); edgeElements.push({{ line, source:edge.source, target:edge.target }});
    }});
    const motionButton = document.querySelector('#graph-motion');
    motionButton.addEventListener('click', () => {{
      const paused = !edgeLayer.classList.contains('motion-paused');
      edgeLayer.classList.toggle('motion-paused', paused);
      motionButton.textContent = paused ? '开启动效' : '暂停动效';
    }});
    const nodeElements = [];
    graphData.graph.nodes.forEach((node, index) => {{
      const point = positions.get(node.id); const tone = index % 2 === 0 ? 'tone-blue' : 'tone-white'; const group = svgEl('g', {{ class:`graph-node ${{node.kind}} ${{tone}}`, transform:`translate(${{point.x}} ${{point.y}})`, tabindex:0, role:'button', 'aria-label':node.kind === 'note' ? `${{node.label}}，打开笔记` : node.label }});
      const radius = node.radius;
      const star = svgEl('g', {{ class:'node-star', 'aria-hidden':'true' }});
      const r = radius, t = r * .16;
      const halo = svgEl('circle', {{ r:r * 1.55, class:'star-halo' }});
      // A small luminous core and thin diffraction rays form a star, rather
      // than the outlined circles used for ordinary graph vertices.
      const rays = svgEl('path', {{ class:'star-rays', d:`M 0 ${{-r * 1.1}} L ${{t}} ${{-t}} L ${{r}} 0 L ${{t}} ${{t}} L 0 ${{r * 1.1}} L ${{-t}} ${{t}} L ${{-r}} 0 L ${{-t}} ${{-t}} Z` }});
      const core = svgEl('circle', {{ r:Math.max(.6, r * .16), class:'star-core' }});
      star.append(halo, rays, core);
      const label = svgEl('text', {{ x:node.label_x, y:node.label_y, 'font-size':graphData.graph.font_size }});
      node.label_lines.forEach((line, lineIndex) => {{
        const span = svgEl('tspan', {{ x:node.label_x, y:node.label_y + lineIndex * graphData.graph.line_height }});
        span.textContent = line; label.appendChild(span);
      }});
      const hit = svgEl('circle', {{ r:node.hit_radius, class:'node-hit', 'aria-hidden':'true' }});
      const titleHit = svgEl('rect', {{ x:node.label_x, y:node.label_y - graphData.graph.font_size, width:node.label_width, height:node.label_height, class:'node-hit', 'aria-hidden':'true' }});
      group.append(star, label, hit, titleHit);
      group.addEventListener('pointerenter', () => focusGraphNode(node.id));
      group.addEventListener('pointerleave', event => {{ if (!event.relatedTarget?.closest?.('.graph-node')) clearGraphFocus(); }});
      group.addEventListener('focus', () => focusGraphNode(node.id));
      group.addEventListener('blur', () => clearGraphFocus());
      group.addEventListener('keydown', event => {{ if (event.key === 'Enter' || event.key === ' ') {{ event.preventDefault(); focusGraphNode(node.id); if (node.kind === 'note') openNote(node); }} }});
      group.addEventListener('click', event => {{ event.stopPropagation(); focusGraphNode(node.id); if (node.kind === 'note') openNote(node); }});
      nodeLayer.appendChild(group);
      group.__nodeId = node.id;
      nodeElements.push({{ node, point, group, label, radius }});
    }});
    const searchStatus = document.querySelector('#search-status');
    const searchResults = document.querySelector('#search-results');
    const repositoryTerms = new Map();
    graphData.repositories.forEach(repository => repository.notes.forEach(note =>
      repositoryTerms.set(`note:${{note.path}}`, `${{repository.name}} ${{repository.type}} ${{repository.path}}`)));
    const searchIndex = nodeElements.filter(entry => entry.node.kind === 'note').map(entry => ({{
      ...entry,
      terms: [entry.node.label, entry.node.path, entry.node.content, ...(entry.node.tags || []), repositoryTerms.get(entry.node.id)].join(' ').toLocaleLowerCase()
    }}));
    search.addEventListener('input', () => {{
      const query = search.value.trim().toLocaleLowerCase();
      const matches = query ? searchIndex.filter(entry => entry.terms.includes(query)) : [];
      const matchedIds = new Set(matches.map(entry => entry.node.id));
      searchStatus.textContent = !query ? '' : matches.length ? `找到 ${{matches.length}} 篇笔记` : '没有找到匹配的笔记，请换个关键词';
      searchResults.textContent = '';
      searchResults.hidden = !query || matches.length === 0;
      matches.forEach(({{node}}) => {{
        const button = document.createElement('button');
        button.setAttribute('type', 'button'); button.setAttribute('class', 'search-result');
        const body = String(node.content || '');
        const position = body.toLocaleLowerCase().indexOf(query);
        const start = Math.max(0, position - 35);
        const excerpt = position < 0 ? node.path : `${{start ? '…' : ''}}${{body.slice(start, Math.max(start + 150, position + query.length))}}`;
        button.textContent = node.label;
        const snippet = document.createElement('span'); snippet.textContent = excerpt; button.appendChild(snippet);
        button.addEventListener('click', () => {{ focusGraphNode(node.id); openNote(node, button); }});
        searchResults.appendChild(button);
      }});
      cards.forEach(card => {{
        let visibleNotes = 0;
        card.querySelectorAll('.note').forEach(note => {{
          const visible = !query || matchedIds.has(note.dataset.nodeId);
          note.classList.toggle('hidden', !visible); if (visible) visibleNotes += 1;
        }});
        const matchesEmptyCard = (card.dataset.search || '').toLocaleLowerCase().includes(query);
        card.classList.toggle('hidden', Boolean(query) && visibleNotes === 0 && !matchesEmptyCard);
      }});
      clearGraphFocus();
      nodeElements.forEach(({{node, group}}) => {{
        group.classList.toggle('search-match', Boolean(query) && matchedIds.has(node.id));
        group.classList.toggle('search-muted', Boolean(query) && !matchedIds.has(node.id));
      }});
      edgeElements.forEach(({{line, source, target}}) => line.classList.toggle('search-muted', Boolean(query) && !matchedIds.has(source) && !matchedIds.has(target)));
    }});
    function focusGraphNode(id) {{
      const related = new Set([id]); graphData.graph.edges.forEach(edge => {{ if (edge.source === id) related.add(edge.target); if (edge.target === id) related.add(edge.source); }});
      nodeLayer.querySelectorAll('.graph-node').forEach(node => {{ node.classList.toggle('muted', !related.has(node.__nodeId)); node.classList.toggle('related', related.has(node.__nodeId)); node.classList.toggle('focused', node.__nodeId === id); }});
      edgeLayer.querySelectorAll('.graph-edge').forEach(edge => {{ const connected = edge.dataset.source === id || edge.dataset.target === id; edge.classList.toggle('muted', !connected); edge.classList.toggle('related', connected); }});
    }}
    function clearGraphFocus() {{
      nodeLayer.querySelectorAll('.graph-node').forEach(node => {{ node.classList.remove('muted'); node.classList.remove('related'); node.classList.remove('focused'); }});
      edgeLayer.querySelectorAll('.graph-edge').forEach(edge => {{ edge.classList.remove('muted'); edge.classList.remove('related'); }});
    }}
    const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({{ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }})[character]);
    const inlineMarkdown = value => escapeHtml(value).replace(/\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]/g, '$1').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/`([^`]+)`/g, '<code>$1</code>');
    const renderNote = value => {{
      const lines = String(value || '').replace(/\\r/g, '').split('\\n'); let output = '', listOpen = false;
      const closeList = () => {{ if (listOpen) {{ output += '</ul>'; listOpen = false; }} }};
      lines.forEach(line => {{
        const trimmed = line.trim();
        if (!trimmed) {{ closeList(); return; }}
        const heading = trimmed.match(/^(#{{1,3}})\s+(.+?)\s*#*$/);
        const bullet = trimmed.match(/^[-*]\s+(.+)$/);
        if (heading) {{ closeList(); output += `<h${{heading[1].length}}>${{inlineMarkdown(heading[2])}}</h${{heading[1].length}}>`; return; }}
        if (bullet) {{ if (!listOpen) {{ output += '<ul>'; listOpen = true; }} output += `<li>${{inlineMarkdown(bullet[1])}}</li>`; return; }}
        if (trimmed.startsWith('>')) {{ closeList(); output += `<blockquote>${{inlineMarkdown(trimmed.slice(1).trim())}}</blockquote>`; return; }}
        closeList(); output += `<p>${{inlineMarkdown(trimmed)}}</p>`;
      }});
      closeList(); return output || '<p>这篇笔记暂时没有可显示的内容。</p>';
    }};
    function openNote(node, returnFocus = null) {{
      readerReturnFocus = returnFocus || nodeElements.find(entry => entry.node.id === node.id)?.group || null;
      readerTitle.textContent = node.label; readerPath.textContent = `所在位置：${{node.path}} · ${{node.repository}}`;
      readerContent.innerHTML = renderNote(node.content); readerEmpty.hidden = true; readerBody.hidden = false;
      reader.hidden = false;
      reader.classList.add('visible'); readerBackdrop.classList.add('visible'); reader.setAttribute('aria-hidden', 'false'); document.body.classList.add('reader-open');
      syncInteractionState();
      reader.querySelector('#reader-close').focus();
    }}
    function closeNote() {{
      if (!reader.classList.contains('visible')) return;
      reader.hidden = true;
      reader.classList.remove('visible'); readerBackdrop.classList.remove('visible'); reader.setAttribute('aria-hidden', 'true'); document.body.classList.remove('reader-open');
      syncInteractionState(); readerReturnFocus?.focus();
    }}
    document.querySelector('#reader-close').addEventListener('click', closeNote); readerBackdrop.addEventListener('click', closeNote);
    document.addEventListener('keydown', event => {{
      if (event.key === 'Escape') {{
        if (!reader.hidden) {{ event.preventDefault(); closeNote(); }}
        else if (graphExpanded) {{ event.preventDefault(); setGraphExpanded(false); }}
        else clearGraphFocus();
      }}
      // The local Markdown renderer emits no links or controls; the reader's
      // only focus target is its back button. Keep Tab inside the open reader.
      if (event.key === 'Tab' && reader.classList.contains('visible')) {{ event.preventDefault(); reader.querySelector('#reader-close').focus(); }}
    }});
    let scale = 1, maximumScale = 3, offsetX = 0, offsetY = 0, dragging = false, startX = 0, startY = 0, startOffsetX = 0, startOffsetY = 0;
    const updateTransform = () => viewport.setAttribute('transform', `translate(${{offsetX}} ${{offsetY}}) scale(${{scale}})`);
    const zoomBy = (factor, anchorX = graphWidth / 2, anchorY = graphHeight / 2) => {{
      const rect = graphSvg.getBoundingClientRect();
      const unit = Math.min(rect.width / graphWidth, rect.height / graphHeight);
      maximumScale = Math.max(maximumScale, 18 / (graphData.graph.font_size * unit || 1));
      const nextScale = Math.max(.35, Math.min(maximumScale, scale * factor));
      const worldX = (anchorX - offsetX) / scale, worldY = (anchorY - offsetY) / scale;
      offsetX = anchorX - worldX * nextScale; offsetY = anchorY - worldY * nextScale; scale = nextScale; updateTransform();
    }};
    const fitGraph = () => {{ scale = 1; offsetX = 0; offsetY = 0; updateTransform(); }};
    const readableGraph = () => {{
      const rect = graphSvg.getBoundingClientRect();
      const unit = Math.min(rect.width / graphWidth, rect.height / graphHeight);
      // Start at a legible small-text size. Fit-to-view remains available for
      // surveying the entire atlas, while dragging reveals nearby notes.
      fitGraph();
      if (unit > 0) zoomBy(Math.max(1, 12 / (graphData.graph.font_size * unit)));
    }};
    document.querySelector('#graph-zoom-out').addEventListener('click', () => zoomBy(.82));
    document.querySelector('#graph-zoom-in').addEventListener('click', () => zoomBy(1.22));
    document.querySelector('#graph-readable').addEventListener('click', readableGraph);
    document.querySelector('#graph-fit').addEventListener('click', fitGraph);
    document.querySelector('#graph-reset').addEventListener('click', clearGraphFocus);
    fullscreenButton.addEventListener('click', () => setGraphExpanded(!graphExpanded));
    const pointerInViewBox = event => {{ const point = graphSvg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY; const matrix = graphSvg.getScreenCTM?.(); if (matrix) {{ const local = point.matrixTransform(matrix.inverse()); return {{ x: local.x, y: local.y }}; }} const rect = graphSvg.getBoundingClientRect(); const unit = Math.min(rect.width / graphWidth, rect.height / graphHeight); return {{ x:(event.clientX - rect.left - (rect.width - graphWidth * unit) / 2) / unit, y:(event.clientY - rect.top - (rect.height - graphHeight * unit) / 2) / unit }}; }};
    graphSvg.addEventListener('wheel', event => {{
      event.preventDefault();
      if (!Number.isFinite(event.deltaY) || event.deltaY === 0) return;
      // Trackpads emit many tiny pixel deltas; wheels may report lines/pages.
      // Scale by distance instead of applying a fixed jump to every event.
      const deltaUnit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? graphSvg.getBoundingClientRect().height : 1;
      const delta = Math.max(-48, Math.min(48, event.deltaY * deltaUnit));
      const point = pointerInViewBox(event);
      zoomBy(Math.exp(-delta * .001), point.x, point.y);
    }}, {{ passive:false }});
    graphSvg.addEventListener('dblclick', fitGraph);
    graphSvg.addEventListener('pointerdown', event => {{ if (event.target.closest('.graph-node')) return; clearGraphFocus(); dragging = true; const point = pointerInViewBox(event); startX = point.x; startY = point.y; startOffsetX = offsetX; startOffsetY = offsetY; graphSvg.setPointerCapture(event.pointerId); }});
    graphSvg.addEventListener('pointermove', event => {{ if (!dragging) return; const point = pointerInViewBox(event); offsetX = startOffsetX + point.x - startX; offsetY = startOffsetY + point.y - startY; updateTransform(); }});
    graphSvg.addEventListener('pointerup', () => dragging = false); graphSvg.addEventListener('pointercancel', () => dragging = false); graphSvg.addEventListener('pointerleave', () => dragging = false);
    readableGraph();
  </script>
</body>
</html>
"""


def write_atomic(path: Path, text: str) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
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


def resolve_output_path(
    root: Path, requested: Path | None, *, protected_inputs: Iterable[Path] = (),
) -> Path:
    """Keep the derived HTML separate from source files and unrelated content."""

    default = requested is None
    raw = requested if requested is not None else root / ".hanos" / GENERATED_FILENAME
    lexical = Path(os.path.abspath(os.path.expanduser(str(raw))))
    if lexical.suffix.lower() not in {".html", ".htm"}:
        raise OverviewError(f"HTML output must use an .html or .htm extension: {lexical}")
    if not _inside(lexical, root):
        if default:
            raise OverviewError(f"default HTML output escapes the knowledge home: {raw}")
    else:
        existing_parent = lexical.parent
        while not existing_parent.exists() and existing_parent != existing_parent.parent:
            existing_parent = existing_parent.parent
        resolved_parent = _resolve(existing_parent, "HTML output directory")
        if not _inside(resolved_parent, root):
            raise OverviewError(f"HTML output directory escapes the knowledge home: {lexical.parent}")
        resolved_target = _resolve(lexical, "HTML output", strict=False)
        if not _inside(resolved_target, root):
            raise OverviewError(f"HTML output escapes the knowledge home: {lexical}")

    resolved_target = _resolve(lexical, "HTML output", strict=False)
    protected = {_resolve(path, "protected HTML input") for path in protected_inputs}
    if resolved_target in protected or resolved_target.suffix.lower() in MARKDOWN_SUFFIXES:
        raise OverviewError(f"HTML output would replace a protected input: {lexical}")
    if lexical.exists():
        if not lexical.is_file():
            raise OverviewError(f"HTML output must be a regular file: {lexical}")
        existing = _read_text(lexical, "existing HTML output").lstrip("\ufeff")
        if not re.match(r"\s*(?:<!doctype\s+html(?:\s|>)|<html(?:\s|>))", existing, flags=re.IGNORECASE):
            raise OverviewError(f"HTML output would replace an existing non-HTML file: {lexical}")
    return lexical


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a local HTML overview from a HanOS Markdown knowledge home."
    )
    parser.add_argument("--config", type=Path, help="Installed HanOS JSON config path")
    parser.add_argument("--knowledge-home", type=Path, help="Existing knowledge-home path")
    parser.add_argument(
        "--output",
        type=Path,
        help=f"HTML output path (default: <knowledge-home>/.hanos/{GENERATED_FILENAME})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        root = resolve_knowledge_home(args.config, args.knowledge_home)
        data = collect_overview(root)
        protected_inputs = [_registry_path(root)]
        if args.config is not None:
            protected_inputs.append(args.config)
        protected_inputs.extend(
            root / note["path"]
            for repository in data["repositories"]
            for note in repository["notes"]
        )
        output = resolve_output_path(root, args.output, protected_inputs=protected_inputs)
        write_atomic(output, render_html(data))
    except OverviewError as error:
        print(f"HANOS_HTML_ERROR={error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"HANOS_HTML_ERROR=unable to write output: {error}", file=sys.stderr)
        return 2
    print(f"HANOS_HTML=PASS")
    print(f"HANOS_HTML_OUTPUT={output.resolve()}")
    print(f"HANOS_HTML_REPOSITORIES={data['repository_count']}")
    print(f"HANOS_HTML_NOTES={data['note_count']}")
    print(f"HANOS_HTML_CONNECTIONS={data['graph']['connection_count']}")
    print(f"HANOS_HTML_UNRESOLVED={data['graph']['unresolved_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
