"""Read-only, scope-bound Markdown evidence. No persistent index or third-party parser."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote


class KnowledgeError(Exception):
    """A machine-readable status and a human-readable failure explanation."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise KnowledgeError("invalid_authority", f"Cannot read JSON authority {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise KnowledgeError("invalid_authority", f"JSON authority must be an object: {path}")
    return data


def _no_links(path: Path, root: Path) -> None:
    if not _inside(path, root):
        raise KnowledgeError("unsafe_path", "Path escapes knowledge home")
    current = root
    if current.is_symlink():
        raise KnowledgeError("unsafe_path", f"Symbolic link is forbidden: {current}")
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise KnowledgeError("unsafe_path", f"Symbolic link is forbidden: {current}")


def _scalar(value: str) -> str | list[str] | None:
    """Deliberately small YAML subset. None marks unsupported syntax."""
    value = value.strip()
    if value.startswith("["):
        if not value.endswith("]"):
            return None
        # Split only outside quotes; nested YAML is intentionally unsupported.
        items = re.findall(r'''(?:"[^"\\]*"|'[^']*'|[^,])+''', value[1:-1])
        result = []
        for item in items:
            parsed = _scalar(item.strip())
            if not isinstance(parsed, str):
                return None
            result.append(parsed)
        return result
    if not value or value[0] in "{|>&*!%`" or any(c in value for c in "{}[]"):
        return None
    if value.startswith(('"', "'")):
        if len(value) < 2 or value[-1] != value[0] or "\\" in value:
            return None
        return value[1:-1]
    if " #" in value or ": " in value or value in {"|", ">"}:
        return None
    return value


def _metadata(text: str) -> tuple[dict[str, Any], list[str], int]:
    """Return simple frontmatter fields, explicit limitations, and body start."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, [], 0
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, ["Unclosed frontmatter; no properties parsed"], 0
    fields: dict[str, Any] = {}
    warnings: list[str] = []
    index = 1
    while index < end:
        line = lines[index].rstrip("\r\n")
        if not line.strip() or line.startswith("#"):
            index += 1
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]*(.*))", line)
        if not match:
            warnings.append(f"Unsupported frontmatter syntax at line {index + 1}; preserved as source")
            index += 1
            continue
        key, value = match.groups()
        if key in fields:
            warnings.append(f"Duplicate property {key}; property excluded")
            fields[key] = None
            index += 1
            continue
        if not value:
            values = []
            following = index + 1
            while following < end:
                item = re.fullmatch(r"[ \t]+-[ \t]+(.+)", lines[following].rstrip("\r\n"))
                if not item:
                    break
                parsed = _scalar(item.group(1))
                if not isinstance(parsed, str):
                    values = None
                elif values is not None:
                    values.append(parsed)
                following += 1
            fields[key] = values if values else None
            index = following
        else:
            fields[key] = _scalar(value)
            index += 1
        if fields[key] is None:
            warnings.append(f"Unsupported property {key}; not indexed")
    return {key: value for key, value in fields.items() if value is not None}, warnings, end + 1


def _visible_lines(text: str, body_start: int = 0) -> list[tuple[int, str]]:
    """Preserve character columns while blanking fenced/inline code and HTML comments."""
    result = []
    fence_char = ""
    fence_size = 0
    fence_quoted = False
    in_comment = False
    for number, original in enumerate(text.splitlines(), 1):
        if number <= body_start:
            result.append((number, ""))
            continue
        line = original
        quote = re.match(r"^(?: {0,3}>[ \t]?)+", line)
        if fence_char and fence_quoted and not quote and line.strip():
            fence_char = ""
        fence_line = line[quote.end():] if quote else line
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", fence_line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char, fence_size = marker[0], len(marker)
                fence_quoted = quote is not None
            elif marker[0] == fence_char and len(marker) >= fence_size and not fence_line[fence.end():].strip():
                fence_char = ""
            result.append((number, ""))
            continue
        if fence_char or line.startswith("    ") or line.startswith("\t"):
            result.append((number, ""))
            continue
        chars = list(line)
        index = 0
        while index < len(line):
            if in_comment:
                end = line.find("-->", index)
                stop = len(line) if end < 0 else end + 3
                chars[index:stop] = " " * (stop - index)
                index = stop
                in_comment = end < 0
            elif line.startswith("<!--", index):
                in_comment = True
            elif line[index] == "`":
                run = re.match(r"`+", line[index:]).group()
                end = line.find(run, index + len(run))
                if end >= 0:
                    stop = end + len(run)
                    chars[index:stop] = " " * (stop - index)
                    index = stop
                else:
                    index += len(run)
            else:
                index += 1
        result.append((number, "".join(chars)))
    return result


def _headings(text: str, body_start: int) -> list[tuple[int, int, str]]:
    headings = []
    for number, line in _visible_lines(text, body_start):
        match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$", line)
        if match:
            headings.append((number, len(match.group(1)), match.group(2)))
    return headings


class Knowledge:
    """One explicit repository scope, selected afresh for each CLI invocation."""

    def __init__(self, config_path: str | Path, scope_selector: str):
        self.config_path = Path(config_path).expanduser()
        if not self.config_path.is_absolute():
            raise KnowledgeError("invalid_authority", "Config path must be absolute")
        config = _json(self.config_path)
        home = config.get("knowledge_home")
        if not isinstance(home, str) or not Path(home).is_absolute():
            raise KnowledgeError("invalid_authority", "knowledge_home must be an absolute directory")
        self._home = Path(home)
        try:
            self.root = self._home.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise KnowledgeError("invalid_authority", f"Invalid knowledge_home: {exc}") from exc
        if not self.root.is_dir():
            raise KnowledgeError("invalid_authority", "knowledge_home is not a directory")
        registry = self.root / ".hanos/repositories.json"
        _no_links(registry, self.root)
        document = _json(registry)
        entries = document.get("repositories")
        if document.get("version") != 1 or not isinstance(entries, list) or not entries:
            raise KnowledgeError("invalid_registry", "Expected version 1 and nonempty repositories list")
        selectors: dict[str, str] = {}
        active: dict[str, tuple[dict[str, Any], Path]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise KnowledgeError("invalid_registry", "Repository entry must be an object")
            status = entry.get("status", "active")
            if not isinstance(status, str) or not status.strip():
                raise KnowledgeError("invalid_registry", "Invalid repository status")
            if status != "active":
                continue
            if any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in ("id", "name", "type", "path")):
                raise KnowledgeError("invalid_registry", "Active entries require id, name, type and path")
            if entry["type"] not in {"global", "project"}:
                raise KnowledgeError("invalid_registry", "Unsupported repository type")
            repository_id = entry["id"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", repository_id):
                raise KnowledgeError("invalid_registry", "Repository id must be a safe path component")
            if repository_id in active:
                raise KnowledgeError("invalid_registry", f"Duplicate repository id: {repository_id}")
            path = Path(entry["path"])
            if ".." in path.parts:
                raise KnowledgeError("unsafe_path", "Repository path contains parent traversal")
            if not path.is_absolute():
                path = self.root / path
            _no_links(path, self.root)
            if any(part.startswith(".") for part in path.relative_to(self.root).parts):
                raise KnowledgeError("unsafe_path", "Repository cannot be a hidden/control path")
            if not path.exists() or not (path.is_file() or path.is_dir()):
                raise KnowledgeError("invalid_registry", f"Repository does not exist: {repository_id}")
            aliases = entry.get("aliases", [])
            if aliases is None:
                aliases = []
            if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                raise KnowledgeError("invalid_registry", "Repository aliases must be strings")
            for selector in (repository_id, entry["name"], *aliases):
                normalized = selector.strip().casefold()
                if not normalized:
                    raise KnowledgeError("invalid_registry", "Empty repository selector")
                if normalized in selectors and selectors[normalized] != repository_id:
                    raise KnowledgeError("ambiguous_scope", f"Repository selector is ambiguous: {selector}")
                selectors[normalized] = repository_id
            active[repository_id] = (entry, path)
        selected = selectors.get(str(scope_selector).strip().casefold())
        if selected is None:
            raise KnowledgeError("scope_not_found", f"No active repository matches: {scope_selector}")
        self.repository, self.entry_path = active[selected]
        self.scope_id = selected
        self._entry_is_file = self.entry_path.is_file()
        self.scope = self.entry_path.parent if self._entry_is_file else self.entry_path

    def safe(self, relative: str | Path, control: bool = False) -> Path:
        """Validate a home-relative target, including nonexistent write targets."""
        try:
            if self._home.resolve(strict=True) != self.root or not self.root.is_dir():
                raise KnowledgeError("unsafe_path", "Knowledge home changed since selection")
        except (OSError, RuntimeError) as exc:
            raise KnowledgeError("unsafe_path", f"Knowledge home unavailable: {exc}") from exc
        path = Path(relative)
        if ".." in path.parts:
            raise KnowledgeError("unsafe_path", "Parent traversal is forbidden")
        if not path.is_absolute():
            path = self.root / path
        _no_links(path, self.root)
        parts = path.relative_to(self.root).parts
        if control:
            prefix = (".hanos", "sources", self.scope_id)
            if parts[:3] != prefix or len(parts) <= 3 or any(part.startswith(".") for part in parts[3:]):
                raise KnowledgeError("unsafe_path", "Control reads are limited to this scope's source snapshots")
        elif any(part.startswith(".") for part in parts) or not _inside(path, self.scope):
            raise KnowledgeError("unsafe_path", "Target is hidden or outside selected scope")
        _no_links(self.entry_path, self.root)
        if self._entry_is_file and not self.entry_path.is_file():
            raise KnowledgeError("unsafe_path", "Selected repository entry file no longer exists")
        if not self.scope.is_dir():
            raise KnowledgeError("unsafe_path", "Selected scope no longer exists")
        return path

    def _document(self, relative: str | Path, control: bool = False) -> dict[str, Any]:
        path = self.safe(relative, control=control)
        try:
            if not path.is_file():
                raise KnowledgeError("not_found", f"File not found: {path.relative_to(self.root)}")
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            raise KnowledgeError("read_error", f"Cannot read UTF-8 file: {path.relative_to(self.root)}: {exc}") from exc
        properties, warnings, body_start = _metadata(text)
        headings = _headings(text, body_start)
        title = properties.get("title")
        if not isinstance(title, str):
            title = headings[0][2] if headings else path.stem
        aliases = properties.get("aliases", [])
        if isinstance(aliases, str):
            aliases = [aliases]
        return {"path": path.relative_to(self.root).as_posix(), "title": title,
                "sha256": hashlib.sha256(raw).hexdigest(), "text": text,
                "properties": properties, "aliases": aliases, "warnings": warnings,
                "headings": headings, "body_start": body_start}

    def _excerpt(self, document: dict[str, Any], section: str | None = None) -> dict[str, Any]:
        lines = document["text"].splitlines(keepends=True)
        start, end = 1, len(lines)
        if section is not None:
            matching = [(number, level, title) for number, level, title in document["headings"] if title.casefold() == section.casefold()]
            if not matching:
                raise KnowledgeError("section_not_found", f"Section not found: {section} in {document['path']}")
            if len(matching) > 1:
                raise KnowledgeError("ambiguous_section", f"Repeated section heading: {section} in {document['path']}")
            start, level, _title = matching[0]
            end = next((number - 1 for number, other_level, _ in document["headings"] if number > start and other_level <= level), len(lines))
        return {"path": document["path"], "title": document["title"], "section": section,
                "sha256": document["sha256"], "excerpt": "".join(lines[start - 1:end]),
                "start_line": start, "end_line": end, "warnings": document["warnings"],
                "properties": document["properties"]}

    def read(self, relative: str | Path, section: str | None = None, control: bool = False) -> dict[str, Any]:
        return self._excerpt(self._document(relative, control), section)

    def _documents(self) -> list[dict[str, Any]]:
        self.safe(self.scope)
        documents = []
        for directory, dirs, filenames in os.walk(self.scope, followlinks=False):
            dirs[:] = sorted(name for name in dirs if not name.startswith(".") and not (Path(directory) / name).is_symlink())
            for filename in sorted(filenames):
                path = Path(directory) / filename
                if filename.startswith(".") or path.is_symlink() or path.suffix.casefold() not in {".md", ".markdown"}:
                    continue
                documents.append(self._document(path))
        return documents

    def _result(self, status: str, hits: list[dict[str, Any]], warnings: list[str] | None = None) -> dict[str, Any]:
        return {"scope": {"id": self.scope_id, "path": self.scope.relative_to(self.root).as_posix()},
                "status": status, "hits": hits, "warnings": warnings or []}

    @staticmethod
    def _named(term: str, document: dict[str, Any]) -> bool:
        path = Path(document["path"])
        return term.casefold() in {str(name).casefold() for name in
                                   [document["title"], path.name, path.stem, document["path"], *document["aliases"]]}

    def query(self, term: str, filters: dict[str, Any] | None = None, section: str | None = None) -> dict[str, Any]:
        if not isinstance(term, str) or not term.strip():
            raise KnowledgeError("invalid_query", "Query must contain a name or keyword")
        filters = filters or {}
        if not isinstance(filters, dict) or any(not isinstance(value, str) for value in filters.values()):
            raise KnowledgeError("unsupported_filter", "Filters require scalar string values")
        documents = self._documents()
        warnings = [f"{doc['path']}: {warning}" for doc in documents for warning in doc["warnings"]]
        for key in filters:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
                raise KnowledgeError("unsupported_filter", f"Unsupported property name: {key}")
        def matches(doc: dict[str, Any]) -> bool:
            for key, expected in filters.items():
                actual = doc["properties"].get(key)
                values = actual if isinstance(actual, list) else [actual]
                if expected not in values:
                    return False
            return True
        documents = [doc for doc in documents if matches(doc)]
        names = [doc for doc in documents if self._named(term.strip(), doc)]
        selected = names or [doc for doc in documents if term.casefold() in doc["text"].casefold()]
        hits = []
        for doc in selected:
            try:
                hit = self._excerpt(doc, section)
            except KnowledgeError as exc:
                if exc.status == "section_not_found":
                    warnings.append(str(exc))
                    continue
                raise
            hit["match"] = "name" if names else "keyword_candidate"
            hits.append(hit)
        status = "ambiguous" if names and len(hits) > 1 else "ok" if names and hits else "candidates" if hits else "not_found"
        if status == "not_found":
            warnings.append("No evidence found in this selected scope; other scopes were not searched")
        elif not names:
            warnings.append("Keyword candidates are source matches, not verified answers or semantic relationships")
        result = self._result(status, hits, warnings)
        result.update({"query": term, "filters": filters})
        return result

    def _resolve_link(self, source: dict[str, Any], target: str, wiki: bool, documents: list[dict[str, Any]]) -> tuple[list[str], str, str | None]:
        target = unquote(target)
        note, separator, section = target.partition("#")
        if not note:
            candidates = [source]
        elif wiki and "/" not in note and not note.startswith("."):
            candidates = [doc for doc in documents if self._named(note, doc)]
        else:
            if Path(note).is_absolute() or "\\" in note:
                return [], "unsafe", section or None
            parent = Path(source["path"]).parent
            # Relative Markdown paths may use ../ when normalization stays in scope.
            candidate = Path(os.path.normpath(str(parent / note)))
            if wiki:
                alternatives = [Path(note), candidate]
            else:
                alternatives = [candidate]
            valid_paths = set()
            for candidate in alternatives:
                if candidate.suffix.casefold() not in {".md", ".markdown"}:
                    candidate = Path(str(candidate) + ".md")
                try:
                    validated = self.safe(candidate)
                except KnowledgeError:
                    continue
                valid_paths.add(validated.relative_to(self.root).as_posix())
            if not valid_paths:
                return [], "unsafe", section or None
            candidates = [doc for doc in documents if doc["path"] in valid_paths]
        paths = sorted({doc["path"] for doc in candidates})
        status = "resolved" if len(paths) == 1 else "ambiguous" if paths else "broken"
        if status == "resolved" and separator and section:
            sections = [title for _, _, title in candidates[0]["headings"]]
            matched = [heading for heading in sections if heading.casefold() == section.casefold() or re.sub(r"[^\w\- ]", "", heading.casefold()).replace(" ", "-") == section.casefold()]
            if len(matched) != 1:
                status = "ambiguous_section" if matched else "broken_section"
        return paths, status, section or None

    def backlinks(self, target: str) -> dict[str, Any]:
        documents = self._documents()
        targets = [doc for doc in documents if self._named(target, doc)]
        target_paths = {doc["path"] for doc in targets}
        hits = []
        issues = []
        warnings = [f"{doc['path']}: {warning}" for doc in documents for warning in doc["warnings"]]
        pattern = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]|(?<!!)\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
        for source in documents:
            section = None
            for line_number, line in _visible_lines(source["text"], source["body_start"]):
                heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
                if heading:
                    section = heading.group(1)
                for match in pattern.finditer(line):
                    if match.start() and line[match.start() - 1] == "\\":
                        continue
                    wiki = match.group(1) is not None
                    destination = match.group(1).split("|", 1)[0] if wiki else match.group(2).strip("<>")
                    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", destination) or destination.startswith("//"):
                        continue
                    if not wiki and destination.split("#", 1)[0] and Path(unquote(destination.split("#", 1)[0])).suffix.casefold() not in {".md", ".markdown"}:
                        continue
                    paths, status, anchor = self._resolve_link(source, destination, wiki, documents)
                    edge = {"path": source["path"], "title": source["title"], "sha256": source["sha256"],
                            "start_line": line_number, "end_line": line_number, "column": match.start() + 1,
                            "excerpt": source["text"].splitlines(keepends=True)[line_number - 1],
                            "section": section, "target": destination, "target_section": anchor,
                            "candidates": paths, "status": status}
                    if status != "resolved":
                        issues.append(edge)
                    elif target_paths.intersection(paths):
                        hits.append(edge)
        status = "ambiguous" if len(target_paths) > 1 else "ok" if target_paths else "not_found"
        if status == "not_found":
            warnings.append("Target absent in this selected scope; no cross-scope lookup was performed")
        result = self._result(status, hits, warnings)
        result.update({"target": target, "target_candidates": sorted(target_paths), "link_issues": issues})
        return result
