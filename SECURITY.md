# Security policy

## Supported version

Security fixes target the latest release on the default branch.

## Report a vulnerability

Do not open a public issue containing credentials, private knowledge, or a
reproducible path to private files. If this repository's Security tab offers
"Report a vulnerability", use that private channel. If it is unavailable, open
an issue requesting a private reporting channel without disclosing the
vulnerability or private data. In the private report, include the affected
version, impact, a minimal reproduction using fictional data, and whether the
issue crosses the configured knowledge-home boundary.

## Security boundaries

- HanOS is local and file-based. It starts no service, listener, scheduler, database, or MCP server.
- Skill activation does not authorize a write.
- Knowledge paths must resolve inside the configured knowledge home.
- The public source tree must never contain user knowledge, credentials, private conversations, or machine-specific paths.
- Installer-managed copies carry hashes so `doctor` can report local drift before replacement.
