# Changelog

## Unreleased

## 0.1.0-preview.3 — 2026-09-21

- Locked the shared HTML renderer and constellation layout as `midnight-atlas@1.0.0` using a shipped SHA-256 manifest. Missing or changed assets fail before output is written.
- Added `--check-template` and read-only `--verify-output`; generation verifies the complete HTML before reporting success. Modified markup, styles, scripts, host-injected attributes and changed source notes require regeneration.
- Required all agents and models to use the bundled renderer without screenshot imitation, client-specific redesign or model-written fallback pages. Template upgrades require an explicit shared-version change.
- Added template integrity checks to installation and public-package validation, with regression coverage for drift, missing assets, source changes and preserved existing output.
- Verified complete HTML parity, apart from generation timestamps, across five isolated client installations. This is packaging/renderer evidence, not a native runtime claim for every client or model.
- Upgrade with the existing knowledge home and display name, reload the Skill, and regenerate HTML. Existing knowledge is not migrated; older generated files must be regenerated to pass verification.

## 0.1.0-preview.2 — 2026-09-18

- Separated knowledge-workflow activation, HTML viewing and explicit Obsidian requests; activation no longer implicitly launches a note application.
- Reworded first-use naming as naming the knowledge assistant, using the agreed conversational introduction.
- Fixed search to include full Markdown content, subheadings, tags and repository information; added result counts, empty-state feedback, clickable excerpts and matching graph emphasis while preserving node positions and reader focus.
- Preserved user/assistant attribution through capture, organization and recall; an existing note no longer constitutes user confirmation of assistant suggestions.
- Added four activation-routing cases and search runtime regressions; corrected shared-case coverage documentation.
- Upgrade using the installer with the existing knowledge home and display name, reload the client, then regenerate HTML to use the updated search. This release does not migrate or rewrite existing notes; older claims need their original evidence checked when revisited.
- Preview limits remain: other clients lack equivalent native verification, and model instruction changes cannot guarantee every future response.

## 0.1.0-preview.1 — 2026-09-17

- Fixed fail-closed installer preflight for symbolic-link loops on Python 3.13.
- Added a short fictional-demo screencast as an inline GIF preview and a compact MP4.
- Added actual desktop screenshots of the fictional atlas demo and its connection highlighting.

- Added a versioned release manifest, clean-snapshot export and reproducible archive builder, CI checks, issue and PR templates, troubleshooting/uninstall guidance, and a support roadmap.
- Added an opt-in six-step native Codex journey using fictional knowledge, separate from the nine shared behavioral cases.

- Changed this release candidate to PolyForm Noncommercial 1.0.0, with a license copy bundled in the installed Skill. Commercial uses require separate permission; this does not revoke rights already granted for earlier versions under their original licenses.
- Protected HTML output from overwriting knowledge/configuration inputs and rechecked control-directory exclusions after resolving Markdown links.
- Excluded Python bytecode caches from installed payloads and integrity checks, recorded Codex adapter identity for template upgrades, and retained recovery snapshots when rollback is incomplete.
- Added an installed `installation.json` locator for clients that discover the shared core directly, with doctor validation.
- Unified explicit handoff persistence, authorized corrections, derived-view output boundaries, and first diary-record routing.
- Added a local HTML knowledge-base overview generator with repository grouping, note previews, search, and path-containment checks.
- Added an offline Obsidian-inspired knowledge graph to the HTML view, resolving WikiLinks, relative Markdown links, and inline tags while keeping unresolved links visible.
- Refined the desktop view with a midnight-blue theme, a horizontal 2:1 star atlas, a panel occupying 60% of the viewport height, and a matching note reader.
- Refined graph navigation with fine pointer-centered wheel zoom, background-only panning, and fit/expanded-view controls. Node positions stay fixed; animated connection highlights respect reduced-motion preferences.
- Added direct-connection highlighting on hover and local Markdown opening on note click.
- Integrated the cyber-diary experience layer as a governed HanOS reference, preserving diary source truth, plain-language reflection, adaptive low-risk capture, and sensitive-content confirmation boundaries.
- Introduced one Agent-neutral HanOS core.
- Added client adapters for Codex, Claude Code, Cursor, GitHub Copilot in VS Code, and Gemini CLI.
- Added an idempotent standard-library installer with `doctor` and drift detection.
- Added zero-write target preflight, bidirectional source/knowledge-home separation, authority-file and symbolic-link containment, fail-closed reinstall, Codex-block ownership, and broken-registry handling, structured malformed-input and symlink-loop failures, stale-backup rollback, complete schema and adapter checks, install-path containment, and Unicode display-name hardening.
- Moved public configuration to JSON templates and separated the private knowledge home from the source tree.
- Added a fictional demo knowledge base, identity-bound machine-readable native evaluations, an isolated release-candidate Git-index privacy gate, privacy documentation, and a portability report with explicit `NOT_RUN` behavioral evidence boundaries.

## 0.1.0-preview.4 (local candidate)

- Scoped evidence lookup with note aliases, basic properties, sections and actual backlinks.
- Byte-preserved text imports with attributed source mappings and explicit coverage limits.
- Version-checked edit plans, idempotent operations, per-file journals and conflict-preserving recovery.
- Installed Skill routing and opt-in isolated Codex Stage A acceptance.
- Existing Markdown and the locked midnight-atlas renderer remain compatible.
