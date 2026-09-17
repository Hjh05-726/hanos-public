# Knowledge map

Resolve paths from the `knowledge_home` in the local JSON config. Re-read the config before every operation; never embed a user's machine path in the Skill.

## Operating authorities

| Need | Existing authority |
|---|---|
| Runtime identity, root, invocation, and safety defaults | Client-supplied local config |
| Registered global and project scopes | `.hanos/repositories.json` |
| Agent entry and load order | `00_Agent_Entry.md` |
| Admission, status, history, and evidence rules | `HanOS Rules.md` |
| Human navigation | The knowledge home's existing dashboard or index |
| User introduction, preferences, and onboarding progress | Existing profile/preferences authority in the registered global scope; see [onboarding.md](onboarding.md) |

## Conventional knowledge authorities

| Need | Existing location to prefer |
|---|---|
| Project state | `01_Projects/` and the selected project's index or `00_Overview.md`, when present |
| Decisions | `04_Decision Log/` and its index, when present |
| Method lifecycle | `05_Methodology/` registry and index, when present |
| Goals | `06_Goals/Active/`, `06_Goals/Completed/`, and the local goal template, when present |
| Unclassified durable material | `00_Inbox/`, when present |
| Historical material | `99_Archive/`, when present |

These are routing conventions, not proof that a path exists. Start from the narrowest relevant index, prefer the existing authority for the same subject, and keep the operation read-only when no canonical destination can be established.

Repository selection and creation are defined only in [repository-protocol.md](repository-protocol.md).
