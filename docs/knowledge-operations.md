# Knowledge operations and recovery

Stage A adds scoped local evidence tools to the existing natural-language Skill.
Markdown remains authoritative. No data migration or required new frontmatter is
introduced; the locked star-map generator and layout assets are unchanged.

Read the installed [tool contract](../skills/hanos/references/knowledge-tools.md)
and [query syntax](knowledge-query.md). The current implementation requires
Python 3.9+ on macOS/Linux (POSIX advisory locking); Windows native writes have
not been implemented or accepted. It has no third-party package dependencies.

## What is stored

- Ordinary notes retain their paths and format. Existing files accept precise
  unique text edits and appends, not whole-file replacement.
- `.hanos/sources/<repository-id>/<input-sha256>/original.md` (or `.txt`) is the
  byte-exact explicit import. Per-target coverage JSON maps summary claims to
  original lines; incomplete structures and unprocessed lines stay visible.
- `.hanos/operations/<operation-id>.json` contains before/after bytes, identity,
  progress and recovery evidence. It is private operational data, excluded from
  normal knowledge search. Never commit these journals to the public package.
- External plan JSON is a reviewable diff plus exact expected versions. Keep it
  outside the knowledge root and private. It is not a second knowledge authority.

Automatic capture stores only the smallest durable part in an existing authority.
It does not create a source transcript. Explicit import preserves the provided
text. Agent decisions about semantics, duplication, attribution and corrections
remain separate from byte/line validation.

## Minimal recovery procedure

1. Keep the original plan and operation ID from the CLI result. Stop retrying
   mutations blindly after an interrupted or failed command.
2. Run `knowledge.py --config <config> --scope <repository> status <operation-id>`.
   Each file is reconciled against disk as `written`, `original` or `conflict`.
3. Within the authorization to undo that operation, run the same prefix followed
   by `recover <operation-id>`. It prechecks all files for later manual edits.
   A `recovery_conflict` preserves the later work and all recovery evidence;
   compare the journal and current note before deciding a new explicit plan.
4. Inspect the returned per-file states and read changed notes. `restored` means
   notes restored; source snapshots and coverage evidence are intentionally
   retained because other notes can reference them. Empty new directories may
   remain. A repeated recovery never reapplies original content over later work.
5. After recovery, a retry of the old plan reports its restored state rather than
   silently doing it again. Create a new explicit edit for subsequent intended
   changes; do not manually edit journals to force a retry.

Explicit source paths must use their canonical absolute location without symbolic
link ancestors. On macOS, resolve temporary `/var/...` aliases to their actual
location before importing; a rejected alias is not a source parsing failure.

No real global installation needs restoration after Stage A development: all
installation tests use separate homes. To discard an uninstalled candidate,
retain evidence and remove only that task's isolated checkout using normal Git
worktree management after checking ownership. Real configuration and knowledge
are never copied into the package or used as fixtures.

## Limits that affect use

Tool invocations coordinate under a local advisory lock. Independent editors,
network filesystems and hostile directory replacement are not covered by a
filesystem transaction. Every tool write rechecks expected bytes immediately
before replacement and reads back afterward, but an outside writer can still
race within the check/replace interval. Multi-file operations have journals and
recovery, not database atomicity. Plans and journals are integrity-bound with
SHA-256, not authenticated authorization tokens or a host access sandbox.

Scanning is per-request within the selected repository. No persistent index or
vector service exists. Markdown/YAML/link support is deliberately bounded and
listed in the query guide. Text imports cannot parse original PDF/Word binaries,
images or attachment contents; a host extraction must document provenance and
losses. Coverage counts and passing tests do not prove every semantic summary.
Native acceptance is opt-in with fictional workspaces; adapter installation is
not evidence of another client's actual model behavior.

## Reproduce validation

```bash
python3 -m unittest discover -s tests -v
python3 skills/hanos/scripts/generate_html.py --check-template
python3 scripts/release.py check
python3 tests/behavioral-evals/run_stage_a.py --workspace /absolute/new-fictional-workspace
python3 tests/behavioral-evals/run_stage_a.py --extra --workspace /absolute/new-fault-workspace
```

The native runner uses the existing configured Codex CLI identity without copying
credentials or changing `HOME`/`CODEX_HOME`. Its local adapter points to the
isolated installed core and records command traces, answers and disk hashes.
Workspace sandbox and prompts are not proof of host-enforced read isolation.
