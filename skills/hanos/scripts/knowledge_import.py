"""Preserve explicit UTF-8 Markdown/text inputs; let the agent supply attributed excerpts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from knowledge_write import (control_path, current, digest, encode, fail, journal_path,
                             load_journal, make_plan)


def make_import(k, source, target, spec):
    source = Path(source).absolute()
    if source.suffix.lower() not in ('.md', '.txt'):
        fail('unsupported_source', 'direct import supports UTF-8 Markdown and text only')
    if any(p.is_symlink() for p in (source, *source.parents)) or not source.is_file():
        fail('invalid_path', 'source must be an explicit regular file without symlinks')
    data = source.read_bytes()
    text = data.decode('utf-8-sig')
    lines = text.splitlines()
    source_hash = digest(data)
    target_path = k.safe(target)
    target = target_path.relative_to(k.root).as_posix()
    key = digest((str(k.root) + '\0' + k.scope_id + '\0' + target + '\0' + source_hash).encode())
    operations = control_path(k, '.hanos/operations')
    if operations.exists():
        for item in sorted(operations.glob('*.json')):
            raw = json.loads(control_path(k, item.relative_to(k.root)).read_text())
            if raw.get('plan', {}).get('metadata', {}).get('import_key') == key:
                return load_journal(k, item.stem)['plan']
    base = f'.hanos/sources/{k.scope_id}/{source_hash}'
    snapshot = f'{base}/original{source.suffix.lower()}'
    report_path = f'{base}/{digest(target.encode())}.coverage.json'
    mappings, covered, blocks = [], set(), []
    allowed = {'source', 'user_decision', 'assistant_suggestion', 'uncertain'}
    for section in spec.get('sections', []):
        start, end = section['start_line'], section['end_line']
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines)):
            fail('invalid_source_location', 'section lines outside preserved input')
        if section['attribution'] not in allowed or not section['text'].strip():
            fail('invalid_attribution', 'each section needs text and explicit attribution')
        excerpt = '\n'.join(lines[start - 1:end])
        mappings.append({'start_line': start, 'end_line': end, 'excerpt': excerpt,
                         'attribution': section['attribution'], 'text': section['text'],
                         'path': snapshot, 'sha256': source_hash})
        covered.update(range(start, end + 1))
        blocks.append(f'### {section["attribution"]}\n\n{section["text"]}\n\n'
                      f'Source: `{snapshot}` lines {start}-{end}; SHA-256 `{source_hash}`.\n')
    if not mappings:
        fail('invalid_import', 'at least one attributed source section is required')
    structural = []
    for i, line in enumerate(lines, 1):
        if re.search(r'!\[|\[\^|^\s*\||^\s*[^\s:]+:\s*[{|>]', line):
            structural.append({'line': i, 'status': 'preserved_only',
                               'reason': 'structure or external asset not interpreted by this tool'})
    report = {'source_name': source.name, 'sha256': source_hash, 'snapshot': snapshot,
              'target': target, 'source_version': source_hash,
              'mappings': mappings, 'covered_lines': sorted(covered),
              'unprocessed_lines': [n for n in range(1, len(lines) + 1) if n not in covered],
              'structure_limits': structural, 'omissions': spec.get('omissions', []),
              'conflicts': spec.get('conflicts', []),
              'limits': ['Line coverage is not semantic completeness.',
                         'No page numbers inferred. Images/attachments are not fetched.',
                         'Attribution is agent supplied; verify against original evidence.',
                         'Semantic similarity is a candidate, never automatic deduplication.']}
    prior = current(target_path)
    heading = spec.get('title', source.stem).replace('\n', ' ')
    addition = (f'\n\n## Imported source: {heading}\n\n'
                f'Version: `{source_hash}`. Prior sources and handwritten content remain unchanged.\n\n'
                + '\n'.join(blocks) + f'\nCoverage: `{report_path}`\n')
    if report['conflicts']:
        addition += '\nUnresolved evidence / candidate claims:\n' + '\n'.join(
            '- ' + str(c) for c in report['conflicts']) + '\n'
    changes = []
    for path, raw in [(snapshot, data), (report_path, (json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode())]:
        existing = current(control_path(k, path))
        if existing is not None and existing != raw:
            fail('conflict', 'preserved import artifact differs from requested bytes')
        if existing is None:
            changes.append({'path': path, 'kind': 'source', 'expected_sha256': None,
                            'bytes_b64': encode(raw)})
    changes.append({'path': target, 'expected_sha256': digest(prior),
                    **({'content': f'# {heading}\n' + addition} if prior is None else {'append': addition})})
    return make_plan(k, changes, {'import_key': key, 'source_sha256': source_hash,
                                 'snapshot': snapshot, 'coverage': report_path, 'target': target})
