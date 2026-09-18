# Write protocol

Use this protocol for an explicit knowledge change and whenever the model has
identified a clear, low-risk durable candidate in an ordinary user message.
Automatic capture is limited to the smallest durable portion; the user's full
message is never copied as a transcript.

## Before writing

1. Read the local config, `00_Agent_Entry.md`, `HanOS Rules.md`, and the repository registry.
2. Resolve the narrowest existing authority node and its unique index.
3. Read the current node and search the affected scope for semantic duplicates or conflicting claims.
4. Establish source, date, evidence status, privacy boundary, and whether live external verification is required.
5. Re-resolve the target, including links. If it is outside the knowledge home, stop without writing.

🔴 **CHECKPOINT — stop and ask** if the target, ownership, evidence authority,
privacy expectation, requested deletion, or history treatment is ambiguous. A
highly sensitive feeling or personal pattern may be analyzed without saving,
then offered as a candidate for the user to approve.

A conflict with an older statement does not itself require another
confirmation. When the user has already authorized a correction and its
target and source authority are clear, apply it, preserve the superseded
statement as labelled history, and keep the correction's evidence status
explicit. Ask only when authority or another required decision remains
unresolved.

## Preserve provenance

At first capture, distinguish the user's statements from assistant additions.
Keep added checkpoints, interpretations, or recommendations under **assistant
suggestion — not user-confirmed**, if useful and authorized to retain; otherwise
leave them out. Cite the originating message or source/date where available.

Organization, paraphrasing, summaries, repeated recall, and presence in an
existing note preserve that attribution; none constitutes user confirmation.
Use **user-confirmed** only when an explicit user statement or approval supports
that specific item, and retain its evidence. If an older note has no traceable
attribution, say **recorded; source/confirmation unclear** and avoid upgrading it.
A request to organize a note approves the organization, not all of its claims.

Before finishing, compare each new or changed claim with its source. For example,
“check five flows” remains the user's method; an added “record results against
acceptance criteria” stays an assistant suggestion until explicitly adopted.

## Apply and verify

- Update an existing authority before creating a note.
- Preserve superseded conclusions as labelled history; never silently erase the evidence trail.
- Never store credentials, tokens, private communications, real production records, or unrelated external-project material.
- A HanOS write does not authorize changes to source projects, cloud resources, databases, production services, or external files.
- Update the existing index when local governance requires it.
- Re-read every changed file, validate links and indexes in the affected scope, and state exactly what changed.

If the instruction contains another task, continue it using the updated knowledge.
