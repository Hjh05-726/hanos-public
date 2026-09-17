# Privacy

HanOS separates public source from private knowledge by design.

## Public source may contain

- The Agent-neutral Skill and behavior protocols
- Client adapters and metadata
- Installer code
- Placeholder configuration
- Fictional examples and behavioral evaluation cases
- Project documentation and tests

## Public source must not contain

- A user's real Markdown knowledge, goals, project state, decisions, or conversations
- Credentials, tokens, account names, or production records
- Machine-specific home directories or private repository URLs
- Generated client configuration containing a real knowledge-home path

The generated HTML overview is a local derived artifact. It includes repository
paths, note titles, previews, and the Markdown content needed to open a note in
the on-page reader, so treat it with the same privacy level as the knowledge
home and do not publish or upload it by default.

Adaptive capture stores only a filtered, durable portion of a user's message;
it does not copy the complete chat. Feelings, lived experiences, and recurring
personal themes can be valid knowledge, but highly sensitive material is kept
as a candidate until persistence is clearly welcome. Cyber-diary is an
experience layer over this same private store, not a second diary database.

The installer rejects any overlap between the knowledge home and source checkout in either direction. It also validates the real paths of the knowledge entry, rules, global authority, registry, and installed client artifacts. The repository allowlist ignores everything except named public artifacts, which is an additional guard rather than permission to place private data beside source.

Before publishing, inspect the exact candidate index blobs as well as the public worktree. The built-in gate detects user-home paths and common credential forms, but it is not a comprehensive privacy or secret scanner. Keep any owner-specific names or identifiers used for local checks outside the public package; splitting them into string fragments does not anonymize them. Review Git history, author and tag metadata, and repository attachments separately. A clean working tree, successful test, marker scan, or private repository setting does not by itself prove privacy; use a mature secret scanner and human review before making the repository public.

Local storage does not mean local-only model processing. The Agent client may
send the notes it reads to its configured model provider. Review that client's
data-handling settings before using sensitive material. The standalone HTML
generator and generated page load no remote assets, but their offline behavior
does not change the Agent client's privacy policy.
