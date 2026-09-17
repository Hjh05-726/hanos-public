# Knowledge repository protocol

This is the single behavior authority for selecting and creating HanOS knowledge repositories. A repository is a registered knowledge scope, not a version-control repository, application, service, or database.

## Resolve the registry

1. Resolve the configured knowledge home as an existing absolute directory, including symbolic links.
2. Read `.hanos/repositories.json`. Validate every active entry before selection.
3. Each active entry requires `id`, `name`, `type`, and `path`. Ids and selectors must be unique across entries. Supported types are `global` and `project`.
4. A repository path may identify a directory or an entry file. For a directory, start from its narrowest relevant index. For an entry file, read it first and follow only relevant links that stay inside the knowledge home.
5. Resolve each active path immediately before access. It must exist inside the resolved knowledge home, including through symbolic links. If any active entry is invalid, report it; do not silently skip it.
6. Match an explicit selector against `id`, `name`, or `aliases`, treating Latin case differences as equivalent. If multiple entries match, stop and ask the user to choose.
7. The selection lasts only for the current instruction and its compound follow-on tasks. Do not persist a hidden current selection.

## Select without an explicit name

- Select `global` for cross-project background, durable user preferences, general methods, cross-project experience, and long-term constraints.
- Select the matching `project` for one project's goals, state, decisions, architecture, results, blockers, next step, or handoff.
- A project task may read relevant global context, but each durable write item has exactly one repository owner.
- In a compound instruction, classify independently scoped write items separately. Report the repository owner for every write.
- Never write project state to global merely because the project is unclear.
- Never confine a cross-project preference to one project merely because that project prompted it.
- If the wording and registry do not identify one scope, remain read-only and ask the user to choose.

## Create or register

Creation requires explicit repository-creation intent. A request to read, analyze, record, or update knowledge does not authorize creation.

1. Search the knowledge home for the requested project's existing directory, index, or overview.
2. Prefer registering that existing path; do not move or copy knowledge.
3. Only when no suitable path exists, create one ordinary directory inside the knowledge home and register it.
4. Do not create an empty authority note or parallel hierarchy automatically.
5. Re-resolve the new path and validate the complete registry before saving.

Never initialize version control, create a remote repository, create a separate software project, or create a database for an internal knowledge scope.
