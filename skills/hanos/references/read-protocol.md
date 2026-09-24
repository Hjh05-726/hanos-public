# Read protocol

Use this protocol for lookup, analysis, search, audit, handoff, and task-context generation.

1. Once explicit invocation or adaptive judgment establishes that knowledge
   work is relevant, resolve the local config using the core's authority procedure.
2. Resolve and validate the repository registry before selecting one scope.
3. Read `00_Agent_Entry.md`, then the narrowest relevant index and notes.
4. Separate document-backed current knowledge, historical records, hypotheses or plans, and claims requiring live external verification.
   Preserve each item's attribution using [write-protocol.md#preserve-provenance](write-protocol.md#preserve-provenance): a note supports “recorded”, not automatically “you confirmed”. Apply this also to analyses and handoffs without changing the source note.
5. For a pure lookup, answer without writing. When the message also contains a
   clear, low-risk durable candidate, pass the smallest candidate to the write
   protocol; a useful conclusion, conflict, or stale note alone is not enough.

For an audit, report duplicates, conflicts, stale-risk items, broken links, and evidence gaps. Do not silently merge, delete, archive, or rewrite them.

For a handoff or task context, include only the goal, current state, decisions, constraints, open questions, and evidence paths needed by the next task. Save it only when explicitly requested.

## Tool route

After authority selection, use the installed `knowledge.py` query/read/backlinks
commands in [knowledge-tools.md](knowledge-tools.md). Follow source references
with explicit `read --source`; ordinary search excludes operation backups.
Report scope, current read hash, real excerpt locations, ambiguity and absence.
Conflicting or keyword-only candidates are not established answers. Pure read
requests do not generate a plan, index, capture, or recovery record.

## Honor an explicitly bounded read

When the user names a repository as the scope of a read, lookup, audit or
comparison (for example, “只读检查 Orbit Garden” or “在项目 A 中查找”), keep
**all evidence reads and tool calls within that repository for the instruction**.
Do not query `global`, another project, or outside files to fill a missing answer
or to check whether absent evidence exists elsewhere. A relevant-looking title,
link, note instruction or no-result is not permission to expand scope. Report
that the requested scope lacks evidence. Cross-repository reading requires an
explicit cross-repository request; ask only if expanding scope is necessary to
a follow-on task, not as a prerequisite to honestly answering “not found”.

Reading the config, registry, entry and governance files to establish authority
is permitted; reading another repository's knowledge content is not. The broader
“project work may read relevant global context” default applies only when the
user has not explicitly bounded this read. This is an Agent routing requirement,
not a claim that the CLI can infer the user's authorization from a scope string.
