"""Version-checked local writes. Journals are recovery evidence, not knowledge."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from knowledge_read import Knowledge, KnowledgeError


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def fail(status, message):
    raise KnowledgeError(status, message)


def control_path(k, relative):
    """Never follow a control-directory alias, including a final file symlink."""
    k.safe(k.scope)
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != '.hanos':
        fail('invalid_path', str(relative))
    target = k.root / p
    for part in (target, *target.parents):
        if part == k.root.parent:
            break
        if part.is_symlink():
            fail('invalid_path', f'symlink: {part}')
    if not target.resolve().is_relative_to(k.root):
        fail('invalid_path', str(relative))
    return target


def target_path(k, relative, kind='note'):
    if kind == 'source':
        p = Path(relative)
        if len(p.parts) < 5 or p.parts[:3] != ('.hanos', 'sources', k.scope_id):
            fail('invalid_path', 'source outside selected scope')
        if not re.fullmatch(r'[a-f0-9]{64}', p.parts[3]):
            fail('invalid_path', 'source version must be SHA-256')
        return control_path(k, relative)
    if kind != 'note':
        fail('invalid_plan', 'unknown target kind')
    return k.safe(relative)


def current(path):
    if path.exists() and not path.is_file():
        fail('invalid_path', f'not a file: {path}')
    return path.read_bytes() if path.exists() else None


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.hanos-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(k):
    lock = control_path(k, '.hanos/operations/write.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def encode(data):
    return base64.b64encode(data).decode() if data is not None else None


def decode(value):
    return base64.b64decode(value, validate=True) if value is not None else None


def make_plan(k, changes, metadata=None):
    entries = []
    seen = set()
    for change in changes:
        relative = change['path']
        kind = change.get('kind', 'note')
        path = target_path(k, relative, kind)
        relative = path.relative_to(k.root).as_posix()
        if relative in seen:
            fail('invalid_plan', 'duplicate target')
        seen.add(relative)
        before = current(path)
        if 'expected_sha256' not in change or digest(before) != change['expected_sha256']:
            fail('stale', f'read version changed: {relative}')
        if 'bytes_b64' in change:
            if kind != 'source':
                fail('invalid_plan', 'raw bytes are for preserved sources only')
            after = decode(change['bytes_b64'])
        elif before is None:
            after = change['content'].encode('utf-8')
        else:
            # Exact local replacements preserve CRLF, unknown fields and handwritten text.
            body = before.decode('utf-8')
            for edit in change.get('edits', []):
                old, new = edit['old'], edit['new']
                if not old or body.count(old) != 1:
                    fail('ambiguous_edit', f'exact edit must match once: {relative}')
                body = body.replace(old, new, 1)
            body += change.get('append', '')
            if 'content' in change:
                fail('invalid_plan', 'existing files require exact edits or append')
            after = body.encode('utf-8')
        if after is None:
            fail('invalid_plan', 'deletion is not supported')
        if kind == 'source' and before is not None and before != after:
            fail('conflict', 'preserved source is immutable')
        if before == after:
            continue
        entries.append({'path': relative, 'kind': kind, 'before': encode(before),
                        'after': encode(after), 'before_sha256': digest(before),
                        'after_sha256': digest(after)})
    body = {'version': 1, 'root': str(k.root), 'scope': k.scope_id,
            'changes': entries, 'metadata': metadata or {}}
    return {**body, 'operation_id': digest(canonical(body)),
            'preview': '\n'.join(''.join(difflib.unified_diff(
                (decode(e['before']) or b'').decode('utf-8', errors='replace').splitlines(True),
                decode(e['after']).decode('utf-8', errors='replace').splitlines(True),
                fromfile=e['path'], tofile=e['path'])) for e in entries)}


def validate_plan(k, plan):
    body = {key: plan[key] for key in ('version', 'root', 'scope', 'changes', 'metadata')}
    if (body['version'] != 1 or body['root'] != str(k.root) or body['scope'] != k.scope_id
            or digest(canonical(body)) != plan['operation_id']):
        fail('invalid_plan', 'plan identity/root/scope mismatch')
    seen = set()
    for e in plan['changes']:
        p = target_path(k, e['path'], e['kind'])
        if p in seen:
            fail('invalid_plan', 'duplicate target')
        seen.add(p)
        if (digest(decode(e['before'])) != e['before_sha256']
                or digest(decode(e['after'])) != e['after_sha256'] or e['after'] is None):
            fail('invalid_plan', 'invalid content digest')
        if e['kind'] == 'source' and e['before'] is not None:
            fail('invalid_plan', 'source replacement forbidden')


def journal_path(k, operation_id):
    if not re.fullmatch(r'[a-f0-9]{64}', operation_id):
        fail('invalid_operation', 'operation id must be SHA-256')
    return control_path(k, f'.hanos/operations/{operation_id}.json')


def save_journal(k, journal):
    atomic(journal_path(k, journal['plan']['operation_id']), canonical(journal))


def inspect(k, journal):
    validate_plan(k, journal['plan'])
    files = []
    for e in journal['plan']['changes']:
        actual = digest(current(target_path(k, e['path'], e['kind'])))
        state = 'written' if actual == e['after_sha256'] else (
            'original' if actual == e['before_sha256'] else 'conflict')
        files.append({'path': e['path'], 'state': state, 'actual_sha256': actual,
                      'before_sha256': e['before_sha256'], 'after_sha256': e['after_sha256']})
    return {'status': journal['status'], 'operation_id': journal['plan']['operation_id'],
            'scope': k.scope_id, 'files': files, 'error': journal.get('error')}


def load_journal(k, operation_id):
    journal = json.loads(journal_path(k, operation_id).read_text())
    validate_plan(k, journal['plan'])
    if journal['plan']['operation_id'] != operation_id:
        fail('invalid_operation', 'journal identity mismatch')
    return journal


def status(k, operation_id):
    # Read only: does not even create a lock or update stale journal status.
    result = inspect(k, load_journal(k, operation_id))
    if any(e['state'] == 'conflict' for e in result['files']):
        result['status'] = 'conflict'
    elif result['status'] == 'applied' and any(e['state'] != 'written' for e in result['files']):
        result['status'] = 'incomplete'
    return result


def apply(k, plan, hook=None):
    validate_plan(k, plan)
    with locked(k):
        path = journal_path(k, plan['operation_id'])
        if path.exists():
            result = status(k, plan['operation_id'])
            if result['status'] == 'applied':
                result['status'] = 'already_applied'
            return result
        for e in plan['changes']:
            if digest(current(target_path(k, e['path'], e['kind']))) != e['before_sha256']:
                fail('stale', f'read version changed: {e["path"]}')
        journal = {'status': 'prepared', 'plan': plan, 'completed': []}
        save_journal(k, journal)
        try:
            for i, e in enumerate(plan['changes']):
                if hook:
                    hook('before_check', i)
                path = target_path(k, e['path'], e['kind'])
                if digest(current(path)) != e['before_sha256']:
                    fail('stale', f'changed before replacement: {e["path"]}')
                atomic(path, decode(e['after']))
                if hook:
                    hook('after_replace', i)
                # Re-resolve after replacement as well as before access.
                if digest(current(target_path(k, e['path'], e['kind']))) != e['after_sha256']:
                    fail('readback_failed', e['path'])
                journal['completed'].append(e['path'])
                save_journal(k, journal)
            journal['status'] = 'applied'
            save_journal(k, journal)
        except (OSError, ValueError, KnowledgeError) as error:
            journal['status'] = 'failed'
            journal['error'] = str(error)
            save_journal(k, journal)
        return inspect(k, journal)


def recover(k, operation_id, hook=None):
    with locked(k):
        journal = load_journal(k, operation_id)
        if journal['status'] == 'restored':
            # Never touch anything on a repeated recovery, even later manual edits.
            result = inspect(k, journal)
            result['status'] = 'already_restored'
            return result
        before_restore = inspect(k, journal)
        conflicts = [e['path'] for e in before_restore['files'] if e['state'] == 'conflict']
        if conflicts:
            journal['status'] = 'recovery_conflict'
            journal['conflicts'] = conflicts
            save_journal(k, journal)
            return {**inspect(k, journal), 'conflicts': conflicts}
        journal['status'] = 'restoring'
        save_journal(k, journal)
        conflicts = []
        retained_sources = []
        for i, e in reversed(list(enumerate(journal['plan']['changes']))):
            if e['kind'] == 'source':
                retained_sources.append(e['path'])
                continue
            path = target_path(k, e['path'], e['kind'])
            if hook:
                hook('before_restore_check', i)
            actual = digest(current(path))
            if actual == e['before_sha256']:
                continue
            if actual != e['after_sha256']:
                conflicts.append(e['path'])
                continue
            if e['before'] is None:
                path.unlink()
            else:
                atomic(path, decode(e['before']))
            if digest(current(target_path(k, e['path'], e['kind']))) != e['before_sha256']:
                conflicts.append(e['path'])
            save_journal(k, journal)
        journal['status'] = 'recovery_conflict' if conflicts else 'restored'
        journal['conflicts'] = conflicts
        save_journal(k, journal)
        result = inspect(k, journal)
        result['conflicts'] = conflicts
        result['retained_sources'] = retained_sources
        return result
