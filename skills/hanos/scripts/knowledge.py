#!/usr/bin/env python3
"""HanOS scoped query, import planning, checked writes and recovery (JSON output)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Do not create a hidden search index or bytecode in an installed Skill on reads.
sys.dont_write_bytecode = True
from knowledge_read import Knowledge, KnowledgeError
from knowledge_write import apply, recover, status, make_plan
from knowledge_import import make_import


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--scope', required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    read = sub.add_parser('read'); read.add_argument('path'); read.add_argument('--section'); read.add_argument('--source', action='store_true')
    query = sub.add_parser('query'); query.add_argument('term'); query.add_argument('--filter', action='append', default=[]); query.add_argument('--section')
    back = sub.add_parser('backlinks'); back.add_argument('path')
    plan = sub.add_parser('plan'); plan.add_argument('--spec', type=Path, required=True); plan.add_argument('--out', type=Path, required=True)
    imp = sub.add_parser('import-plan'); imp.add_argument('--source', type=Path, required=True); imp.add_argument('--target', required=True); imp.add_argument('--spec', type=Path, required=True); imp.add_argument('--out', type=Path, required=True)
    app = sub.add_parser('apply'); app.add_argument('plan', type=Path)
    for command in ('status', 'recover'):
        p = sub.add_parser(command); p.add_argument('operation_id')
    args = parser.parse_args()
    try:
        k = Knowledge(args.config, args.scope)
        if args.command == 'read':
            result = {'status': 'ok', 'scope': k.scope_id, **k.read(args.path, section=args.section, control=args.source)}
        elif args.command == 'query':
            filters = dict(v.split('=', 1) for v in args.filter)
            result = k.query(args.term, filters=filters, section=args.section)
        elif args.command == 'backlinks':
            result = k.backlinks(args.path)
        elif args.command in ('plan', 'import-plan'):
            spec = json.loads(args.spec.read_text())
            result = (make_plan(k, spec['changes']) if args.command == 'plan'
                      else make_import(k, args.source, args.target, spec))
            destination = args.out.absolute()
            if (destination.resolve().is_relative_to(k.root)
                    or any(p.is_symlink() for p in (destination, *destination.parents))):
                raise KnowledgeError('invalid_path', 'plan output must be outside the knowledge home without symlinks')
            # Refuse replacement: a plan is evidence bound to its original read.
            with destination.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            result = {'status': 'planned', 'operation_id': result['operation_id'],
                      'plan': str(destination), 'preview': result['preview'], 'metadata': result['metadata']}
        elif args.command == 'apply':
            result = apply(k, json.loads(args.plan.read_text()))
        elif args.command == 'status':
            result = status(k, args.operation_id)
        else:
            result = recover(k, args.operation_id)
        print(json.dumps({'tool': 'hanos-knowledge-v1', **result}, ensure_ascii=False, indent=2))
        return 1 if result.get('status') in ('failed', 'stale', 'conflict', 'recovery_conflict', 'incomplete') else 0
    except (KnowledgeError, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'tool': 'hanos-knowledge-v1', 'status': getattr(error, 'status', 'error'),
                          'error': str(error)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
