# Supported Agents

HanOS keeps one behavior source under `skills/hanos/`. The installer creates a shared standards-based copy and, where needed, a generated thin wrapper. Wrappers only locate the core and local config.

For shared-core discovery without a wrapper, the installed `installation.json`
beside `SKILL.md` supplies the local config path. The installer creates this
locator for every client and `doctor` validates it; clients do not infer paths.

| Client | Discovery | Adaptive use | Manual-only control | Current native evidence |
|---|---|---|---|---|
| OpenAI Codex | Shared user Agent Skills path | Model judges relevance; `$hanos` remains an explicit override | Client metadata supplies the canonical core | `PASS` (2026-09-17): six-step isolated read, record, retrieve, history-preserving correction, do-not-save and installed HTML generation |
| Claude Code | Generated user Skill wrapper | Model judges relevance; `/hanos` remains an explicit override | Core authorization gates; no wrapper-level manual-only flag | `NOT_TESTED`: the local configured model was rejected before a result |
| Cursor | Generated user Skill wrapper | Model judges relevance; `/hanos` remains an explicit override | Core authorization gates; no wrapper-level manual-only flag | `NOT_TESTED` |
| GitHub Copilot / VS Code Agent | Shared user Agent Skills path | Model judges relevance; `/hanos` remains an explicit override | Not applied to the shared standard core | `NOT_TESTED` |
| Gemini CLI | Shared user Agent Skills path | Client consent may activate the shared core; model judges relevance afterward | No documented per-Skill manual-only equivalent | `NOT_TESTED` |

## Evidence boundary

Codex completed the current six-step fictional journey on 2026-09-17 using
`codex-cli 0.154.0-alpha.6.2`. Other clients remain unverified; the Claude Code
attempt is historical (2026-09-03). See the [evaluation results](../tests/behavioral-evals/results.md)
for exact scope and evidence hashes.

Static tests verify packaging, adapter metadata, installation paths, privacy, and safety rules. They are not native runtime tests. A client remains `NOT_TESTED` until the generated installation is discovered and exercised in that client with the same fictional demo knowledge base.

The thirteen shared behavioral cases have validated definitions and required safety coverage, but no common runner has executed all thirteen end to end: `AUTOMATED_SHARED_CASE_EXECUTION=NOT_RUN`.

Local user Skills may not transfer to remote or cloud workers. Install a project-scoped copy in the remote environment using that client's documented mechanism when needed.

## Known limitations

- The dated Codex support result covers the six-step fictional journey. Additional routing and provenance samples are documented separately in the evaluation results; they do not establish cross-client parity. Raw traces remain local; macOS was used for these runs. The native runner supports macOS/Linux. The complete thirteen-case automated run remains `NOT_RUN`.
- A combined Cursor installation contains both the shared standards path and a client wrapper. Collision precedence remains unverified until a Cursor runtime is available.
- The shared Copilot installation keeps standard-only core frontmatter. Automatic capture still follows the core's low-risk, provenance, and privacy gates.
- Gemini CLI has no documented per-Skill control equivalent to manual-only invocation; initial client consent and the adaptive core's sensitive-content confirmation rules remain mandatory.
