# Behavioral evaluation results

Checked: 2026-09-17. Candidate: `0.1.0-preview.1`.

## Current package verification

The isolated public-only checkout passed **89/89** automated tests on macOS.
Coverage includes installation and upgrades, release and privacy boundaries,
HTML interactions and graph layout, deterministic archives, and native-evaluator
checks for preserving history and terminating a timed-out process group.
These are local results. The configured Linux/macOS CI matrix has not yet run on
the hosting service; its workflow passed local actionlint 1.7.12 validation.

## Current native Codex journey

An installed Codex client completed all six steps against a new isolated home
and entirely fictional knowledge:

| Step | Result | Evidence |
|---|---|---|
| Explicit read | PASS | Machine-readable events proved canonical core, nonce-bearing registry and authority reads; structured answer; no knowledge changes |
| Record | PASS | Exact random fact saved in existing authority; original contents retained; no unrelated knowledge changed |
| Retrieve | PASS | Correct fact and relative source returned; no knowledge changed |
| Correct | PASS | Current value updated from 7 to 9; old value explicitly marked superseded; original authority and NOT_PROVEN boundary retained |
| Do not save | PASS | Explicit refusal to record produced no knowledge changes |
| HTML generation | PASS | Installed generator actually executed; only derived HTML changed; output included the new fictional fact |

The correction note was also read manually to verify that 9 is current and 7 is
superseded history. Installed payload, config and registry remained unchanged.
The native journey ran before the final evaluator-only process-group cleanup
patch; that cleanup was then verified with timeout and child-process regressions.
The installed Skill and generator did not change between those checks.

- Client: `codex-cli 0.154.0-alpha.6.2`.
- Client binary SHA-256: `ecad78dbf98adb89ec475edac86630406cbe59d9f3070b17d88065f136b94bcb`.
- Skill core SHA-256: `aad0b5e1d641705ce6a257972efd9850e7593d0b250c0a009d354bab2c24b506`.
- Explicit-read trace SHA-256: `ad5c53e495dc9e06d4919d88d37cbe102881e0ba7f77eabf2f7b8e2564237e47`.
- Six trace manifest aggregate SHA-256: `fdbe4fbe6519a75b0b48da1cee6b4a62a6818f6a82bb222fcfd80d3396694730` (sorted JSON mapping of trace filename to SHA-256).

Raw traces, local paths and generated knowledge remain outside the public package.
The hashes bind local evidence; they do not make private traces independently
reproducible public evidence. Rerun `run_journey.py` in a new directory to obtain
your own evidence. The native Codex runner currently requires macOS or Linux.

## Client coverage

| Client | Native result | Evidence scope |
|---|---|---|
| Codex | PASS, 2026-09-17 | Six-step isolated fictional journey above |
| Claude Code | NOT_TESTED | Historical attempt on 2026-09-03: configured model rejected before response |
| Cursor | NOT_TESTED | Static adapter checks only |
| GitHub Copilot / VS Code | NOT_TESTED | Static adapter checks only |
| Gemini CLI | NOT_TESTED | Static adapter checks only |

`AUTOMATED_SHARED_CASE_EXECUTION=NOT_RUN`

All nine shared case definitions pass schema and required-coverage checks. The
six-step journey is separate: it does not execute all nine cases or establish
cross-client parity. Portability remains `PARTIAL`. Other client versions,
operating systems and models require separate native evidence.

## Historical evaluation, 2026-09-03

Three independent paired judges compared the previous client-specific Skill with the Agent-neutral candidate. All three preferred the candidate (`3-0`); two marked the margin clear and one slight. They consistently credited runtime neutrality, ordered workflow, explicit failure branches, visible write checkpoints, and the anti-pattern blacklist.

The judges also identified four regressions: display-name changes, file-based repository entries, compound-write ownership reporting, and concrete authority paths. Those items were restored without reintroducing client-specific assumptions.

Two behavioral cases were narrowed after review: an unspecified project blocker now stops at the write checkpoint, and “organize” without a save verb remains read-only. Both were independently rerun against isolated demo copies; their before/after SHA-256 manifests were unchanged. This evidence covers those two cases only and does not upgrade `AUTOMATED_SHARED_CASE_EXECUTION`.
