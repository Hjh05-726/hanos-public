"""Real-file and process-boundary acceptance for Stage A controlled writes."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/hanos/scripts"
sys.path.insert(0, str(SCRIPTS))
from knowledge_read import Knowledge, KnowledgeError
import knowledge_write as writes
from knowledge_import import make_import


CHILD = r'''
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from knowledge_read import Knowledge, KnowledgeError
import knowledge_write as writes
k = Knowledge(sys.argv[2], 'project')
mode, value = sys.argv[3:5]
try:
    if mode == 'apply':
        plan = json.loads(Path(value).read_text())
        boundary, index = sys.argv[5:7]
        def hook(phase, number):
            if phase == boundary and number == int(index):
                os._exit(73)
        result = writes.apply(k, plan, hook=hook)
    elif mode == 'race':
        plan = json.loads(Path(value).read_text())
        ready, go = map(Path, sys.argv[5:7])
        ready.write_text('ready')
        end = time.monotonic() + 10
        while not go.exists():
            if time.monotonic() > end:
                raise RuntimeError('race start timed out')
            time.sleep(.005)
        result = writes.apply(k, plan)
    else:
        result = getattr(writes, mode)(k, value)
except KnowledgeError as error:
    result = {'status': error.status, 'error': str(error)}
print(json.dumps(result))
'''


class ControlledWriteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / 'knowledge'
        (self.home / '.hanos').mkdir(parents=True)
        (self.home / 'project').mkdir()
        self.config = self.base / 'config.json'
        self.config.write_text(json.dumps({'knowledge_home': str(self.home)}))
        (self.home / '.hanos/repositories.json').write_text(json.dumps({
            'version': 1, 'repositories': [
                {'id': 'project', 'name': 'Fictional Project', 'type': 'project', 'path': 'project'}]}))
        self.k = Knowledge(self.config, 'project')
        self.note = self.home / 'project/note.md'
        self.original = b'---\r\nunknown_nested:\r\n  value: keep\r\n---\r\n# Note\r\nHandwritten.\r\nStatus: old\r\n'
        self.note.write_bytes(self.original)

    def change(self, path='project/note.md', **kwargs):
        return {'path': path, 'expected_sha256': writes.digest(writes.current(self.home / path)), **kwargs}

    def plan(self, suffix='\r\nAdded.\r\n'):
        return writes.make_plan(self.k, [self.change(append=suffix)])

    def save_plan(self, plan, name='plan.json'):
        path = self.base / name
        path.write_text(json.dumps(plan))
        return path

    def child(self, mode, value, boundary='never', index=-1):
        return subprocess.run([sys.executable, '-c', CHILD, str(SCRIPTS), str(self.config), mode,
                               str(value), boundary, str(index)], capture_output=True, text=True, timeout=15)

    def result(self, process):
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_ac13_stale_plan_preserves_manual_changes_without_journal(self):
        plan = self.plan()
        modified = self.original + b'Manual change.\r\n'
        self.note.write_bytes(modified)
        with self.assertRaises(KnowledgeError) as caught:
            writes.apply(self.k, plan)
        self.assertEqual(caught.exception.status, 'stale')
        self.assertEqual(self.note.read_bytes(), modified)
        self.assertFalse(writes.journal_path(self.k, plan['operation_id']).exists())

    def test_ac08_exact_edit_preserves_unknown_yaml_crlf_and_handwriting(self):
        plan = writes.make_plan(self.k, [self.change(edits=[{'old': 'Status: old', 'new': 'Status: new'}])])
        result = writes.apply(self.k, plan)
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.note.read_bytes(), self.original.replace(b'Status: old', b'Status: new'))
        self.assertEqual(writes.apply(self.k, plan)['status'], 'already_applied')
        self.assertEqual(writes.recover(self.k, plan['operation_id'])['status'], 'restored')
        self.assertEqual(self.note.read_bytes(), self.original)

    def test_ac13_two_processes_compete_on_the_same_read_version(self):
        plans = [self.plan('\r\nWriter A.\r\n'), self.plan('\r\nWriter B.\r\n')]
        go = self.base / 'go'
        processes = []
        try:
            for i, plan in enumerate(plans):
                processes.append(subprocess.Popen(
                    [sys.executable, '-c', CHILD, str(SCRIPTS), str(self.config), 'race',
                     str(self.save_plan(plan, f'plan-{i}.json')), str(self.base / f'ready-{i}'), str(go)],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            end = time.monotonic() + 10
            while not all((self.base / f'ready-{i}').exists() for i in range(2)):
                self.assertLess(time.monotonic(), end, 'workers did not reach race barrier')
                time.sleep(.005)
            go.write_text('start')
            results = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 0, stderr)
                results.append(json.loads(stdout))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertCountEqual([item['status'] for item in results], ['applied', 'stale'])
        winner = next(i for i, item in enumerate(results) if item['status'] == 'applied')
        self.assertEqual(self.note.read_bytes(), writes.decode(plans[winner]['changes'][0]['after']))
        self.assertEqual(len(list((self.home / '.hanos/operations').glob('*.json'))), 1)

    def test_ac13_manual_edit_at_last_version_check_is_preserved(self):
        plan = self.plan()
        changed = self.original + b'Human edited during operation.\r\n'
        def hook(phase, index):
            if phase == 'before_check':
                self.note.write_bytes(changed)
        result = writes.apply(self.k, plan, hook=hook)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('changed before replacement', result['error'])
        self.assertEqual(result['files'][0]['state'], 'conflict')
        self.assertEqual(self.note.read_bytes(), changed)

    def test_ac15_readback_failure_is_not_reported_as_success(self):
        plan = self.plan()
        changed = self.original + b'Human write after replacement.\r\n'
        def hook(phase, index):
            if phase == 'after_replace':
                self.note.write_bytes(changed)
        result = writes.apply(self.k, plan, hook=hook)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['files'][0]['state'], 'conflict')
        journal = writes.load_journal(self.k, plan['operation_id'])
        self.assertEqual(journal['completed'], [])
        self.assertEqual(writes.status(self.k, plan['operation_id'])['status'], 'conflict')
        self.assertEqual(writes.recover(self.k, plan['operation_id'])['status'], 'recovery_conflict')
        self.assertEqual(self.note.read_bytes(), changed)

    def multi_plan(self):
        source = b'# Fictional source\r\nSource claim.\r\n' + writes.digest(self.note.read_bytes()).encode()
        relative = f'.hanos/sources/project/{writes.digest(source)}/source.md'
        index = self.home / 'project/index.md'
        index.write_bytes(b'# Index\r\nHandwritten index.\r\n')
        return writes.make_plan(self.k, [
            self.change(relative, kind='source', bytes_b64=base64.b64encode(source).decode()),
            self.change(append='\r\nImported claim.\r\n'),
            self.change('project/index.md', append='\r\n[[note]]\r\n')])

    def test_ac15_fresh_process_recovers_every_multifile_boundary(self):
        # os._exit bypasses exceptions/finally: the next process must use only disk evidence.
        for boundary in ('before_check', 'after_replace'):
            for index in range(3):
                with self.subTest(boundary=boundary, index=index):
                    plan = self.multi_plan()
                    interrupted = self.child('apply', self.save_plan(plan), boundary, index)
                    self.assertEqual(interrupted.returncode, 73, interrupted.stderr)
                    status = self.result(self.child('status', plan['operation_id']))
                    self.assertEqual(status['status'], 'prepared')
                    written_count = index + (boundary == 'after_replace')
                    self.assertEqual([f['state'] for f in status['files']],
                                     ['written'] * written_count + ['original'] * (3 - written_count))
                    recovered = self.result(self.child('recover', plan['operation_id']))
                    self.assertEqual(recovered['status'], 'restored')
                    for position, entry in enumerate(plan['changes']):
                        expected = entry['after'] if entry['kind'] == 'source' and position < written_count else entry['before']
                        self.assertEqual(writes.current(self.home / entry['path']), writes.decode(expected))
                    repeated = self.result(self.child('recover', plan['operation_id']))
                    self.assertEqual(repeated['status'], 'already_restored')
                    # Keep each interruption's operation distinct without deleting recovery evidence.
                    self.note.write_bytes(self.note.read_bytes() + f'Boundary {boundary}:{index}\r\n'.encode())

    def test_ac16_recovery_preserves_later_manual_edits_and_is_repeatable(self):
        plan = self.multi_plan()
        self.assertEqual(writes.apply(self.k, plan)['status'], 'applied')
        manual = self.note.read_bytes() + b'Manual after apply.\r\n'
        self.note.write_bytes(manual)
        result = writes.recover(self.k, plan['operation_id'])
        self.assertEqual(result['status'], 'recovery_conflict')
        self.assertEqual(result['conflicts'], ['project/note.md'])
        self.assertEqual(self.note.read_bytes(), manual)
        self.assertEqual((self.home / plan['changes'][0]['path']).read_bytes(), writes.decode(plan['changes'][0]['after']))
        self.assertEqual((self.home / 'project/index.md').read_bytes(), writes.decode(plan['changes'][2]['after']))
        self.assertEqual(writes.recover(self.k, plan['operation_id'])['status'], 'recovery_conflict')
        self.assertEqual(self.note.read_bytes(), manual)

    def test_ac16_partial_process_write_then_manual_edit_blocks_all_recovery(self):
        plan = self.multi_plan()
        interrupted = self.child('apply', self.save_plan(plan), 'before_check', 2)
        self.assertEqual(interrupted.returncode, 73, interrupted.stderr)
        manual = self.note.read_bytes() + b'Manual after partial operation.\r\n'
        self.note.write_bytes(manual)
        before = {entry['path']: writes.current(self.home / entry['path']) for entry in plan['changes']}
        result = self.result(self.child('recover', plan['operation_id']))
        self.assertEqual(result['status'], 'recovery_conflict')
        self.assertEqual(result['conflicts'], ['project/note.md'])
        self.assertEqual([entry['state'] for entry in result['files']], ['written', 'conflict', 'original'])
        self.assertEqual({entry['path']: writes.current(self.home / entry['path'])
                          for entry in plan['changes']}, before)
        journal = writes.load_journal(self.k, plan['operation_id'])
        self.assertEqual(writes.decode(journal['plan']['changes'][1]['before']), self.original)
        self.assertEqual(self.result(self.child('recover', plan['operation_id']))['status'], 'recovery_conflict')
        self.assertEqual(self.note.read_bytes(), manual)

    def test_ac16_repeated_completed_recovery_does_not_touch_new_manual_edit(self):
        plan = self.plan()
        writes.apply(self.k, plan)
        writes.recover(self.k, plan['operation_id'])
        manual = self.original + b'Manual after restore.\r\n'
        self.note.write_bytes(manual)
        self.assertEqual(writes.recover(self.k, plan['operation_id'])['status'], 'already_restored')
        self.assertEqual(self.note.read_bytes(), manual)

    def test_ac14_correction_keeps_superseded_claim_and_source_attribution(self):
        original = self.original + b'\r\nSource: field report, line 7.\r\n'
        self.note.write_bytes(original)
        replacement = ('Status: old [superseded; source: field report, line 7]'
                       '\r\nStatus: new [user correction; current; old claim retained above]')
        plan = writes.make_plan(self.k, [self.change(edits=[{'old': 'Status: old', 'new': replacement}])])
        self.assertEqual(writes.apply(self.k, plan)['status'], 'applied')
        expected = original.replace(b'Status: old', replacement.encode())
        self.assertEqual(self.note.read_bytes(), expected)
        self.assertIn(b'Source: field report, line 7.', self.note.read_bytes())
        self.assertEqual(writes.decode(plan['changes'][0]['before']), original)

    def test_source_snapshot_symlink_cannot_escape_home(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.hanos/sources').symlink_to(outside, target_is_directory=True)
        raw = b'preserved source'
        with self.assertRaises(KnowledgeError):
            writes.make_plan(self.k, [{'path': f'.hanos/sources/project/{writes.digest(raw)}/source.md',
                                      'kind': 'source', 'expected_sha256': None,
                                      'bytes_b64': base64.b64encode(raw).decode()}])
        self.assertEqual(list(outside.iterdir()), [])

    def test_operations_symlink_cannot_escape_home(self):
        plan = self.plan()
        outside = self.base / 'outside'
        outside.mkdir()
        (self.home / '.hanos/operations').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(KnowledgeError):
            writes.apply(self.k, plan)
        self.assertEqual(self.note.read_bytes(), self.original)
        self.assertEqual(list(outside.iterdir()), [])

    def test_final_operation_file_symlink_is_rejected(self):
        plan = self.plan()
        outside = self.base / 'outside.json'
        outside.write_bytes(b'unchanged')
        journal = writes.journal_path(self.k, plan['operation_id'])
        journal.parent.mkdir(parents=True)
        journal.symlink_to(outside)
        with self.assertRaises(KnowledgeError):
            writes.apply(self.k, plan)
        self.assertEqual(outside.read_bytes(), b'unchanged')
        self.assertEqual(self.note.read_bytes(), self.original)


class ImportAcceptanceTests(unittest.TestCase):
    setUp = ControlledWriteTests.setUp

    def source(self, name='source.md', content=None):
        path = self.base / name
        path.write_bytes(content if content is not None else (
            '# 虚构资料\r\n仅在温室中适用。\r\n用户：只确认每日观察。\r\n'
            '助手：建议增加自动灌溉，尚未确认。\r\n'.encode()))
        return path

    def spec(self):
        return {'title': '温室资料', 'sections': [
            {'start_line': 2, 'end_line': 2, 'attribution': 'source', 'text': '仅在温室中适用。'},
            {'start_line': 3, 'end_line': 3, 'attribution': 'user_decision', 'text': '每日观察。'},
            {'start_line': 4, 'end_line': 4, 'attribution': 'assistant_suggestion',
             'text': '自动灌溉仍为未确认建议。'}]}

    def test_ac02_markdown_and_text_preserve_exact_bytes_and_line_mappings(self):
        for name in ('source.md', 'source.txt'):
            with self.subTest(name=name):
                source = self.source(name)
                original = source.read_bytes()
                prior_note = self.note.read_bytes()
                target = f'project/imported-{source.suffix[1:]}.md'
                plan = make_import(self.k, source, target, self.spec())
                self.assertEqual(writes.apply(self.k, plan)['status'], 'applied')
                metadata = plan['metadata']
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual((self.home / metadata['snapshot']).read_bytes(), original)
                self.assertEqual(metadata['source_sha256'], writes.digest(original))
                self.assertEqual(self.note.read_bytes(), prior_note)
                report = json.loads((self.home / metadata['coverage']).read_text())
                self.assertEqual(report['unprocessed_lines'], [1])
                self.assertEqual(report['covered_lines'], [2, 3, 4])
                self.assertEqual([m['attribution'] for m in report['mappings']],
                                 ['source', 'user_decision', 'assistant_suggestion'])
                output = (self.home / target).read_text()
                for mapping in report['mappings']:
                    start, end = mapping['start_line'], mapping['end_line']
                    self.assertEqual(mapping['excerpt'], '\n'.join(original.decode().splitlines()[start-1:end]))
                    self.assertEqual(mapping['sha256'], writes.digest(original))
                    self.assertIn(f'lines {start}-{end}', output)
                    self.assertIn(mapping['attribution'], output)
                    self.assertIn(metadata['snapshot'], output)

    def test_ac04_coverage_reports_structures_omissions_and_no_invented_pages(self):
        raw = ('---\ncustom: {nested: yes}\n---\n# Host parsed chapter\n'
               '有条件的结论。\n| 表格 | 未解释 |\n![图](missing.png)\n'
               '[^note]: 脚注\n未理解的语法 <<< ???\n').encode()
        source = self.source('host-parsed.txt', raw)
        spec = {'sections': [{'start_line': 5, 'end_line': 5, 'attribution': 'source',
                             'text': '有条件的结论。'}],
                'omissions': [{'line': 9, 'reason': '未理解的特殊语法，保全原样待核对'}]}
        plan = make_import(self.k, source, 'project/structured.md', spec)
        self.assertEqual(writes.apply(self.k, plan)['status'], 'applied')
        report = json.loads((self.home / plan['metadata']['coverage']).read_text())
        self.assertEqual((self.home / report['snapshot']).read_bytes(), raw)
        self.assertEqual(report['covered_lines'], [5])
        self.assertEqual(report['unprocessed_lines'], [1, 2, 3, 4, 6, 7, 8, 9])
        self.assertEqual({item['line'] for item in report['structure_limits']}, {2, 6, 7, 8})
        self.assertTrue(all(item['status'] == 'preserved_only' for item in report['structure_limits']))
        self.assertEqual(report['omissions'], spec['omissions'])
        self.assertIn('Line coverage is not semantic completeness.', report['limits'])
        self.assertTrue(any('No page numbers inferred.' in limitation for limitation in report['limits']))
        self.assertIn('lines 5-5', (self.home / 'project/structured.md').read_text())
        self.assertNotIn('page_number', json.dumps(report))

    def test_ac05_same_target_retry_is_idempotent_another_target_is_not_swallowed(self):
        source = self.source()
        plan = make_import(self.k, source, 'project/imported.md', self.spec())
        self.assertEqual(writes.apply(self.k, plan)['status'], 'applied')
        before = {p.relative_to(self.home).as_posix(): p.read_bytes()
                  for p in self.home.rglob('*') if p.is_file()}
        retry = make_import(self.k, source, 'project/imported.md', self.spec())
        self.assertEqual(retry['operation_id'], plan['operation_id'])
        self.assertEqual(writes.apply(self.k, retry)['status'], 'already_applied')
        after = {p.relative_to(self.home).as_posix(): p.read_bytes()
                 for p in self.home.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        other = make_import(self.k, source, 'project/other.md', self.spec())
        self.assertNotEqual(other['operation_id'], plan['operation_id'])
        self.assertEqual(writes.apply(self.k, other)['status'], 'applied')
        self.assertTrue((self.home / 'project/other.md').is_file())
        self.assertEqual(other['metadata']['snapshot'], plan['metadata']['snapshot'])
        self.assertEqual(writes.recover(self.k, plan['operation_id'])['status'], 'restored')
        self.assertTrue((self.home / other['metadata']['snapshot']).is_file())
        self.assertIn(other['metadata']['snapshot'], (self.home / 'project/other.md').read_text())

    def test_ac06_revision_appends_new_evidence_preserving_manual_text_and_old_source(self):
        source = self.source()
        first = make_import(self.k, source, 'project/note.md', self.spec())
        writes.apply(self.k, first)
        manual = self.note.read_bytes() + '人工批注：先核对条件。\n'.encode()
        self.note.write_bytes(manual)
        source.write_bytes(source.read_bytes().replace('仅在温室中适用'.encode(), '仅在低湿温室中适用'.encode()))
        spec = self.spec()
        spec['sections'][0]['text'] = '仅在低湿温室中适用。'
        spec['conflicts'] = ['旧版温室与新版低湿温室条件不同；需用户核对，不能合并。']
        second = make_import(self.k, source, 'project/note.md', spec)
        self.assertNotEqual(first['metadata']['source_sha256'], second['metadata']['source_sha256'])
        self.assertEqual(writes.apply(self.k, second)['status'], 'applied')
        final = self.note.read_bytes()
        self.assertTrue(final.startswith(manual))
        for plan in (first, second):
            self.assertTrue((self.home / plan['metadata']['snapshot']).is_file())
            self.assertIn(plan['metadata']['source_sha256'].encode(), final)
        self.assertIn('Unresolved evidence / candidate claims:', final.decode())
        self.assertIn(spec['conflicts'][0], final.decode())

    def test_ac06_similar_source_is_retained_as_distinct_evidence(self):
        source = self.source()
        first = make_import(self.k, source, 'project/note.md', self.spec())
        writes.apply(self.k, first)
        before = self.note.read_bytes()
        similar = self.source('similar.txt', '仅在室外适用，温室不能套用。\n'.encode())
        second = make_import(self.k, similar, 'project/note.md', {
            'sections': [{'start_line': 1, 'end_line': 1, 'attribution': 'uncertain',
                          'text': '措辞相近但条件不同，作为候选保留。'}],
            'conflicts': ['温室与室外条件互斥，不能据语义近似合并。']})
        self.assertEqual(writes.apply(self.k, second)['status'], 'applied')
        self.assertTrue(self.note.read_bytes().startswith(before))
        self.assertNotEqual(first['metadata']['source_sha256'], second['metadata']['source_sha256'])
        self.assertIn('uncertain', self.note.read_text())

    def test_ac05_retry_after_manual_rewrite_reports_actual_conflict(self):
        source = self.source()
        first = make_import(self.k, source, 'project/note.md', self.spec())
        writes.apply(self.k, first)
        manual = self.note.read_bytes() + b'Manual revision.\n'
        self.note.write_bytes(manual)
        retry = make_import(self.k, source, 'project/note.md', self.spec())
        result = writes.apply(self.k, retry)
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(self.note.read_bytes(), manual)
        self.assertEqual(result['files'][-1]['state'], 'conflict')

    def test_ac17_import_source_symlink_is_not_read_or_preserved(self):
        outside = self.source('outside.txt')
        alias = self.base / 'alias.md'
        alias.symlink_to(outside)
        original = outside.read_bytes()
        with self.assertRaises(KnowledgeError) as caught:
            make_import(self.k, alias, 'project/imported.md', self.spec())
        self.assertEqual(caught.exception.status, 'invalid_path')
        self.assertEqual(outside.read_bytes(), original)
        self.assertFalse((self.home / '.hanos/sources').exists())
        self.assertFalse((self.home / 'project/imported.md').exists())

    def test_import_invalid_locations_and_attributions_never_create_output(self):
        source = self.source()
        for section, expected in [
            ({'start_line': 1, 'end_line': 99, 'attribution': 'source', 'text': 'bad'}, 'invalid_source_location'),
            ({'start_line': 1, 'end_line': 1, 'attribution': 'approved', 'text': 'bad'}, 'invalid_attribution')]:
            with self.subTest(expected=expected):
                with self.assertRaises(KnowledgeError) as caught:
                    make_import(self.k, source, 'project/imported.md', {'sections': [section]})
                self.assertEqual(caught.exception.status, expected)
                self.assertFalse((self.home / 'project/imported.md').exists())
                self.assertFalse((self.home / '.hanos/sources').exists())


if __name__ == '__main__':
    unittest.main()
