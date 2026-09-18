# HTML knowledge-base view

Use this mode when the user explicitly requests a visual knowledge-base interface, overview, or graph, including “打开知识库界面” and “看看知识图谱”; they need not say “HTML”. A bare activation request such as “开启我的知识库” follows the activation route in `SKILL.md` instead. This mode produces a local derived artifact; it does not create a second knowledge base and does not change Markdown notes.

When the user asks to open or see the view, open the generated HTML in an available browser or client preview and verify it is displayed. If opening is unavailable, return the exact local file link and distinguish generation from opening. A generate-only request needs the artifact and counts, without an unsolicited application launch. Do not fall back to Obsidian or another note-taking application unless the user explicitly requests that application.

## Generate the view

After resolving the client config and validating the repository registry, run the bundled script:

```bash
cd "<SKILL_DIR>" && python3 scripts/generate_html.py --config "<CONFIG_PATH>"
```

`<SKILL_DIR>` is the canonical installed HanOS Skill directory that contains
`SKILL.md`; resolve it from the client adapter, or use the directory of the
verified canonical `SKILL.md` already loaded when the shared core is discovered
directly. In that direct-discovery case, resolve the config through the adjacent
`installation.json` as described by the core. Do not assume the current project
working directory. The default output is
`<knowledge_home>/.hanos/knowledge-overview.html`. A different local path can
be requested with `--output`. For a standalone local vault or an older
installation without the JSON config, pass an existing knowledge home directly:

```bash
cd "<SKILL_DIR>" && python3 scripts/generate_html.py --knowledge-home "/absolute/path/to/knowledge-home" \
  --output "/absolute/path/to/knowledge-overview.html"
```

The script reads the active entries from `.hanos/repositories.json` and accepts the legacy `.hanos/repositories.yaml` shape as a compatibility fallback. It validates every active repository path, including symbolic links, before reading it. A missing registry or an escaping path is an error; the script never invents a repository. The default output directory must remain inside the knowledge home; an explicitly requested `--output` may be a separate local path.

Output paths must end in `.html` or `.htm`. The generator refuses to replace
Markdown sources, the resolved config or registry, or existing non-HTML files,
including authority files reached through an `.html` symbolic link. Existing
generated HTML can be refreshed at the same path. A rejected output leaves the
existing file unchanged.

## What the HTML contains

- A shared midnight-blue atlas theme with pale cyan stars, static nebula lighting,
  a subtle coordinate grid, compact controls, and a matching dark reading surface.
  CSS, SVG, and interaction code are embedded in the generated HTML. There are no
  remote fonts, CDNs, or adjacent asset dependencies. The installer distributes
  the same generator and layout module to every supported client; different
  knowledge homes use the same theme. Local font fallbacks can vary by operating
  system. Existing HTML must be regenerated after upgrading the installed core.
  The graph panel occupies 60% of the viewport height on desktop and 70% on
  narrow screens, including its toolbar and legend. The constellation layout
  spreads horizontally in a 2:1 atlas, with title collision checks and wrapped controls.
  Expanded view fits the viewport.
  Wheel zoom follows actual scroll distance, normalizes pixel/line/page deltas,
  and caps each event below a 5% change. Tiny trackpad movements make fine
  adjustments; equal opposite movements restore scale, with the cursor anchored.
- One summary card per active repository, with its type, relative path, and Markdown-note count.
- One row per Markdown note, with its first heading, relative path, and a short first-paragraph preview.
- Search across repository names/types, note titles, paths, tags, and full Markdown content including subheadings. Show a match count or an empty-result message, clickable excerpts that open the note, and matching graph nodes with unrelated nodes subdued. Clearing the query restores the graph and note list; searching does not move nodes or change source notes.
- An offline knowledge graph from `[[WikiLink]]`, relative Markdown links, and
  inline `#tags`, with click-to-focus, background-only pan, zoom buttons,
  fit-to-view, and fullscreen controls. Hovering a node highlights its directly
  related notes, tags, and links; clicking a note star or its full title opens
  the same-page reader.
  Related nodes form irregular constellations, with positions computed once
  during generation and fixed while reading. Hovering never moves the stars.
  Every title stays beside its star in small text. Long titles wrap without
  truncation. Generation reserves space for each star and its full title;
  hovering never hides or rearranges labels, and zoom scales the complete map.
  The initial view keeps title text at least 12 CSS pixels; drag to explore
  nearby notes. Clear-view and fit-to-view controls switch between readable
  detail and the whole atlas. Pale blue text has a fine background-colored
  outline to separate it from connecting lines, which retain a stable width.
  Stars have a small bright core, fine rays, and a subtle blue-white halo.
  Larger stars retain clear title spacing and an invisible 11-unit click radius.
  A slow, staggered highlight travels along each fixed connection. Hovering
  emphasizes related trails and stops unrelated ones. The footer can pause
  motion; reduced-motion preferences show static connections, and opening a
  note pauses the trails in the background.
  Fullscreen expands the graph within the current browser page, keeping the
  toolbar, graph, and reader in one document coordinate system. It does not
  use the browser's native Fullscreen API. Escape closes the reader first,
  then exits the expanded view; closing a reader restores graph controls
  while keeping the expanded state, and the last exit restores page scrolling.
  Closed readers are hidden and cannot intercept pointer or keyboard input. The
  graph is the first content section so it is visible immediately after opening.
- Total repository count, note count, file size, and latest note modification time.

Clicking a note node opens a readable note panel on the same page. The generated
HTML includes the note text for this local reader, so treat the file as private.
The panel
renders headings, paragraphs, lists, quotes, and inline code from the source
Markdown; the original file remains the authority.

The view skips control directories such as `.hanos`, `.git`, and `.obsidian` and rechecks both the real directory and the Markdown file type after resolving symbolic links. It is deliberately a summary: open the source Markdown note for its full content. The graph resolves a link only when it maps to one unique note by path, basename, stem, or title; unresolved links are shown as dashed nodes. The HTML uses no remote assets or network requests, and its output is escaped before being embedded in the page.

## Authorization and reporting

Generating the file is a write to the requested output path, so do not run it from a vague request to “analyze” the knowledge base. Run it when the user requests the HTML view, then report the exact output path and the repository, note, connection, and unresolved-link counts. Do not claim that the HTML proves external, deployed, or current business state; it only reflects the local files read at generation time.
