# Getting started

## Requirements

- Python 3.9 or newer
- A desktop computer and a modern desktop browser for the HTML view; mobile use
  is outside the current support scope
- At least one supported Agent client
- A directory outside this source checkout for private Markdown knowledge

The installer and generator have no third-party Python dependencies. Git is
needed to clone the repository and run release-package tests, but not to install
from an extracted source archive. Native execution evidence varies by client;
see [Supported Agents](supported-agents.md).

## Install

Download and extract the source package, or clone the published release branch.
Keep that source directory available for later upgrades and display-name changes.
From the folder containing `install.py`, choose your client:

```bash
python3 install.py --agent codex
python3 install.py --agent claude-code
python3 install.py --agent cursor
python3 install.py --agent copilot
python3 install.py --agent gemini-cli
python3 install.py --agent all
```

The installer asks for a knowledge-home path and display name. For scripted installation, pass `--knowledge-home`, `--display-name`, and `--yes`.

```bash
python3 install.py --agent all \
  --knowledge-home /absolute/path/to/hanos-knowledge \
  --display-name Atlas \
  --yes
```

The knowledge home must be outside the source checkout. Existing files are reused; HanOS does not move or import them automatically.

To hand HanOS to another person, share this public package and have them run
the installer with a knowledge-home directory they own. They should choose
their own display name and keep that knowledge home outside this source
checkout; do not copy your private Markdown vault or installed config. The
same Skill behavior and local graph then work against their own repositories.

## Verify

```bash
python3 install.py --doctor
```

`doctor` validates the config schema, active repository registry, installed core hashes, generated wrappers, and every adapter artifact declared by the install manifest. A successful doctor result proves the local installation contract only; it does not prove that every Agent client is installed or has executed HanOS.

Start a new client session after installation so the client can discover the
installed Skill. Use its documented Skill discovery or reload mechanism if
HanOS is not visible immediately.

Clients that discover the shared core directly locate the private config through
`installation.json` beside the installed `SKILL.md`. The installer generates this
local file and includes it in integrity checks; it is not part of the public source package.

Upgrades validate the recorded installed Codex adapter before replacing it, so a
new public template does not count as a local edit. Older manifests without an
adapter hash can migrate only when their block matches the known template;
unverified differences remain protected. Python bytecode caches are excluded
from new payload hashes. Legacy hashes that included bytecode are accepted only
when the exact old payload can still be verified.

If both installation and rollback fail, the error reports a retained recovery
directory. Its `restore-manifest.json` maps each original path to its backup.
Preserve this directory until recovery is complete.

## Upgrade

Download the new source package and run its installer with an already-installed
client, the same knowledge-home path, and the same display name:

```bash
python3 install.py --agent codex \
  --knowledge-home /absolute/path/to/existing-knowledge \
  --display-name Atlas --yes
python3 install.py --doctor
```

Replace `codex`, the example path, and `Atlas` with your existing values. If you
originally supplied `--home`, supply that same installation home again. The
installer retains the previously installed client set and checks managed files
for local changes before replacing them. If drift is reported, preserve and
review those edits before retrying.

Restart or reload the client after the upgrade. Ask HanOS to regenerate the HTML
overview to apply the new generator; an existing HTML file is a snapshot and
does not update itself. Each installation uses its own config and knowledge;
never distribute your installed config as part of the source package.

## First use

Say “开始我的知识库” to begin a short introduction. HanOS asks one question at
a time: what you want to call your knowledge assistant, how to address you, your current context,
what you care about, and how you prefer it to respond. It then explains everyday
use and helps you save a first real record. You can skip questions, say “先用起来”,
or resume later with “继续上次的引导”. Existing answers are reused, and upgrading
an established knowledge home does not restart the questionnaire. The naming
invitation is “我是你的知识库助手，你可以给我取一个名字，以后有需要喊我就行。你想叫我什么？”
The chosen name becomes HanOS's configured display name; addressing it by that
name in conversation invokes the knowledge workflow.

Answers and progress stay in your registered local global knowledge authority;
the public Skill contains only the flow. A new name is applied through the
existing installer without changing your knowledge-home directory or adding
clients. The private install manifest records `source_root` so the model can
locate that installer; if the original distribution has moved or was removed,
the name remains pending until its location is known.

After installation, the model can judge when a message contains durable
knowledge and capture the smallest useful part automatically. It still reads
only the relevant scope, skips one-off tasks, and asks before saving highly
sensitive or ambiguous material. An explicit HanOS invocation remains
available when you want to force a knowledge operation.

## Generate a local HTML overview

When you explicitly ask HanOS to show the knowledge base as HTML, it reads the
configured registry and writes a derived view:

```bash
python3 skills/hanos/scripts/generate_html.py --config "/path/to/hanos/config.json"
```

The output path is `<knowledge_home>/.hanos/knowledge-overview.html` unless you
pass `--output` with an `.html` or `.htm` path. Existing non-HTML files and
knowledge/configuration inputs cannot be overwritten. The page groups active repositories, lists Markdown notes, and
supports a browser-side search across titles, paths, and previews. It also
renders an offline midnight-blue star atlas from `[[WikiLink]]`, relative
Markdown links, and inline `#tags`; unresolved links stay visible so missing
connections can be repaired in the source notes.

The desktop graph uses a horizontal 2:1 layout in a panel that occupies 60% of
the viewport height. Wheel zoom makes fine, cursor-anchored adjustments. Notes
open in a matching reading panel; their text is embedded in the HTML, so the
generated file must be treated as private. The same generator and embedded
assets ship with every client adapter, with no external font or CDN dependency.
