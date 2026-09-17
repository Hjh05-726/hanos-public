# Portability report

Package verification: 2026-09-17, **89/89** public tests passed in an isolated
public-only checkout on macOS. Codex completed the six-step fictional native
journey with `codex-cli 0.154.0-alpha.6.2`. CI configuration passed actionlint;
the hosted Linux/macOS matrix has not run yet.

```text
HANOS_PORTABILITY_RESULT=PARTIAL
AGENT_SKILLS_SPEC_COMPLIANCE=PASS
CORE_AGENT_NEUTRAL=YES
PRIVATE_KNOWLEDGE_EXCLUDED=YES

CODEX_ADAPTER=PASS
CLAUDE_CODE_ADAPTER=NOT_TESTED
CURSOR_ADAPTER=NOT_TESTED
COPILOT_ADAPTER=NOT_TESTED
GEMINI_CLI_ADAPTER=NOT_TESTED

CANONICAL_SKILL_PATH=~/.agents/skills/hanos
SUPPORTED_AGENTS=codex,claude-code,cursor,copilot,gemini-cli
KNOWLEDGE_HOME_HARDCODED=NO
BACKGROUND_SERVICE_CREATED=NO
MCP_CREATED=NO
AUTOMATED_SHARED_CASE_EXECUTION=NOT_RUN

PUBLIC_SOURCE_FILES_ADDED:
- Agent-neutral core and references
- Five client adapter manifests and required wrappers or metadata
- JSON config and repository templates
- Fictional demo knowledge base
- Installer, doctor, privacy checks, behavioral cases, and project documentation

ADAPTERS_ADDED:
- codex
- claude-code
- cursor
- copilot
- gemini-cli

PRIVATE_CONTENT_FOUND:
- none in the exact public worktree manifest or release-candidate Git-index blobs

KNOWN_COMPATIBILITY_LIMITATIONS:
- Claude Code rejected the locally configured model before returning a result
- Cursor, Copilot or VS Code, and Gemini CLI were unavailable for native execution
- Gemini CLI has no documented per-Skill manual-only control
- Combined Cursor shared-core and wrapper precedence is not yet verified
```

The Codex `PASS` covers explicit read, record, retrieve, history-preserving correction,
do-not-save and installed HTML generation. Machine-readable traces bind client
identity and actual file operations; manual note review confirms that the old
value is superseded. The final evaluator-only timeout cleanup patch was verified
separately with process-group regressions; the installed Skill and generator were
unchanged. Traces stay local, outside the release package.

The nine shared case definitions pass schema and coverage checks, but their
complete automated execution is `NOT_RUN`. Full evidence is in
[the evaluation results](../tests/behavioral-evals/results.md); limitations are
maintained in [supported-agents.md](supported-agents.md). Static package success
never upgrades an unavailable client's native status.
