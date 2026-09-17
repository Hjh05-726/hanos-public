# Contributing

HanOS keeps one Agent-neutral behavior authority at `skills/hanos/SKILL.md`. Client folders may contain metadata or thin wrappers, but must not fork the behavior protocols.

HanOS is source-available under PolyForm Noncommercial 1.0.0, rather than an
OSI-approved open-source license. Submit only contributions you have the right
to provide under that license. Contributions do not transfer copyright or grant
the maintainers a separate commercial relicensing right. Keep third-party
notices intact and identify any differently licensed material before inclusion.

The root `LICENSE` and `skills/hanos/LICENSE` must remain byte-identical. The
second copy travels with the installed Skill so its license is available even
when the source checkout is absent.

Before opening a change:

1. Add a failing test for a behavior or safety rule change.
2. Make the smallest change that passes it.
3. Run `python3 -m unittest discover -s tests`.
4. Run `python3 install.py --doctor` against an isolated test installation when installer behavior changes.
5. Confirm that no personal knowledge, absolute user path, token, conversation, or production record entered the public package.

Keep native runtime claims separate from static contract tests. An adapter is not `PASS` until it has been exercised in that client.

## Development and review

Use a Git checkout with Python 3.9 or newer, Git, and Node.js 22 for HTML runtime
checks. Runtime installation itself does not require Node.js. Keep private
knowledge outside the checkout and use the fictional examples for reproduction.

Run `python3 scripts/release.py check` and the test command above before a PR.
Every new public file must be named in `release-files.txt`, the explicit
`.gitignore` allowlist, and any new directory in the release directory contract.
Never add real native traces or generated personal HTML. Test changes to the
installed Skill in a fresh isolated home.

PRs should explain the problem, resulting behavior, checks and limitations.
The maintainer reviews safety boundaries, scope, compatibility and tests;
current preview releases have no fixed review-time promise. CI uses read-only
permissions and does not run a model or publish a release. See
[release instructions](docs/releasing.md) and [support roadmap](docs/roadmap.md).
