# Behavioral evaluation results

Checked: 2026-09-03

Package regression update, 2026-09-16: the public installer, release, HTML, and
layout suites passed `81/81` checks from an isolated public-only checkout.
This includes verifying that the Noncommercial license travels with the installed core.
The desktop visual revision and shared-generator installation are included.
New cases cover
template upgrades with Owner-content preservation, runtime-cache handling,
shared-client config locators, legacy migration, failed-rollback recovery, and
HTML source protection. This is local automated evidence; native-client and
shared behavioral execution evidence below remains dated 2026-09-03.

## Static and installer contracts

- Public release and installer tests: `44/44 PASS`; full local suite including eight ignored compatibility tests: `52/52 PASS`.
- Covered: standard-only core frontmatter, Agent-neutral core text, one core authority, client manifests, exact worktree and release-candidate Git-index allowlists, shared worktree/index privacy markers, staged-then-deleted blob scanning, common credential syntax, JSON validity, installer support for all five selectors, idempotence, drift detection, Unicode display-name injection rejection, complete config and active-registry schema checks, fail-closed reinstall, Codex-block ownership, and broken registry links, structured malformed-input and symbolic-link-loop failures, declared-adapter doctor checks, install-path and knowledge-authority containment, stale-backup rollback, preflight rejection of partial installs, bidirectional source/knowledge-home separation, persistent-workspace refusal, safe JSON path materialization, bound native-client identity, machine-readable native evidence checks, and the prompt/expected schema plus required safety coverage of nine shared behavior definitions.
- The official bundled quick validator was attempted but could not start because its environment lacked PyYAML. Equivalent frontmatter and package invariants are covered by the public tests; the helper failure is not presented as a pass.

`AUTOMATED_SHARED_CASE_EXECUTION=NOT_RUN`

The suite validates all nine case definitions, but no shared runner has executed every case end to end against a native client. Definition coverage is not reported as behavioral execution.

## Native clients

| Client | Version or availability | Result | Evidence scope |
|---|---|---|---|
| Codex | `codex-cli 0.151.0-alpha.7.2` | `PASS` | Current isolated rerun; executable realpath, version, and SHA-256 were recorded; machine-readable events proved reads of the canonical core, nonce-bearing registry, and nonce-bearing project authority; direct-address invocation returned the fictional project's relative evidence file; no knowledge file changed; local status remained distinct from production `NOT_PROVEN` |
| Claude Code | `2.1.252` | `NOT_TESTED` | Client started, but the locally configured model was rejected before producing a response |
| Cursor | Not found locally | `NOT_TESTED` | Static adapter contract only |
| GitHub Copilot / VS Code | VS Code command not found locally | `NOT_TESTED` | Static adapter contract only |
| Gemini CLI | Not found locally | `NOT_TESTED` | Static adapter contract only |

## Darwin comparison

Three independent paired judges compared the previous client-specific Skill with the Agent-neutral candidate. All three preferred the candidate (`3-0`); two marked the margin clear and one slight. They consistently credited runtime neutrality, ordered workflow, explicit failure branches, visible write checkpoints, and the anti-pattern blacklist.

The judges also identified four regressions: display-name changes, file-based repository entries, compound-write ownership reporting, and concrete authority paths. Those items were restored without reintroducing client-specific assumptions.

Two behavioral cases were narrowed after review: an unspecified project blocker now stops at the write checkpoint, and “organize” without a save verb remains read-only. Both were independently rerun against isolated demo copies; their before/after SHA-256 manifests were unchanged. This evidence covers those two cases only and does not upgrade `AUTOMATED_SHARED_CASE_EXECUTION`.

## Boundary

The current Codex rerun recorded binary SHA-256 `a6042937174f72112dbd2d554a4af36936422e0c5ac69e353dc68994458996e9` and local-only trace SHA-256 `cce9c166718c84f0e5706d2b9d10a7813836d813f518863ae27b6c2e6f38c041`. The trace is retained outside the release package; this is current local verification, not independently reproducible public evidence.

`PASS` above applies only to the named evidence. The full cross-client portability result remains `PARTIAL` until Claude Code, Cursor, Copilot or VS Code, and Gemini CLI complete native evaluations with the same fictional knowledge base. The built-in marker scan covers named private identifiers and common credential forms but is not a comprehensive secret scanner.
