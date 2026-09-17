from __future__ import annotations

import json
import math
from html.parser import HTMLParser
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skills.hanos.scripts.generate_html import _constellation_positions, collect_overview


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/hanos/scripts/generate_html.py"


class HtmlDashboardTests(unittest.TestCase):
    def test_landscape_graph_keeps_complete_titles_inside_without_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, _config = self.make_knowledge_home(Path(directory))
            for index in range(70):
                (root / "global" / f"note-{index}.md").write_text(
                    f"# 第 {index} 篇关于学习与日常观察的完整中英笔记 / Field Notes\n\n"
                    f"See [[note-{(index + 1) % 70}]]. #观察\n", encoding="utf-8",
                )
            graph = collect_overview(root.resolve())["graph"]
            self.assertAlmostEqual(graph["width"] / graph["height"], 2)
            xs = [node["x"] for node in graph["nodes"]]
            ys = [node["y"] for node in graph["nodes"]]
            self.assertGreater(max(xs) - min(xs), max(ys) - min(ys))
            rectangles = []
            for node in graph["nodes"]:
                self.assertEqual("".join(node["label_lines"]), node["label"])
                left = node["x"] - 14
                top = node["y"] + min(-11, node["label_y"] - graph["font_size"]) - 3
                right = node["x"] + max(11, node["label_x"] + node["label_width"]) + 3
                bottom = node["y"] + max(11, node["label_y"] - graph["font_size"] + node["label_height"]) + 3
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, graph["width"])
                self.assertLessEqual(bottom, graph["height"])
                for other in rectangles:
                    self.assertFalse(min(right, other[2]) - max(left, other[0]) > 1e-6
                                     and min(bottom, other[3]) - max(top, other[1]) > 1e-6)
                rectangles.append((left, top, right, bottom))

    def test_constellations_are_spread_stable_and_follow_real_links(self) -> None:
        nodes = [{"id": f"n{index}"} for index in range(40)]
        edges = [{"source": f"n{index}", "target": f"n{index + 1}"} for index in range(0, 38, 2)]
        positions = _constellation_positions(nodes, edges)
        self.assertEqual(positions, _constellation_positions(nodes[::-1], edges[::-1]))
        self.assertEqual(_constellation_positions([], []), {})
        self.assertEqual(_constellation_positions(nodes[:1], []), {"n0": (500.0, 280.0)})
        points = list(positions.values())
        for x, y in points:
            self.assertTrue(50 <= x <= 910 and 45 <= y <= 510)
        self.assertGreater(max(x for x, y in points) - min(x for x, y in points), 550)
        self.assertGreater(max(y for x, y in points) - min(y for x, y in points), 320)
        self.assertGreater(min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:]), 28)
        # Stars occupy many distances from the center, not one or two rings.
        self.assertGreater(len({round(math.dist(point, (500, 280)) / 20) for point in points}), 8)
        unlinked = _constellation_positions(nodes, [])
        self.assertLess(
            sum(math.dist(positions[e["source"]], positions[e["target"]]) for e in edges),
            sum(math.dist(unlinked[e["source"]], unlinked[e["target"]]) for e in edges),
        )

    def make_knowledge_home(self, temporary: Path) -> tuple[Path, Path]:
        root = temporary / "knowledge"
        (root / ".hanos").mkdir(parents=True)
        (root / "global").mkdir()
        (root / "projects/demo").mkdir(parents=True)
        (root / "global/00_Overview.md").write_text(
            "# Global <script>alert(1)</script>\n\n- Evidence stays local.\n",
            encoding="utf-8",
        )
        (root / "projects/demo/00_Overview.md").write_text(
            "# Demo Project\n\nStatus: `CONFIRMED_LOCAL`\n\nSee [[Global]] and [[Missing Note]]. #project/demo\n",
            encoding="utf-8",
        )
        (root / ".hanos/repositories.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "repositories": [
                        {
                            "id": "global",
                            "name": "Global",
                            "type": "global",
                            "path": "global",
                            "status": "active",
                        },
                        {
                            "id": "demo",
                            "name": "Demo Project",
                            "type": "project",
                            "path": "projects/demo",
                            "status": "active",
                        },
                        {
                            "id": "archived",
                            "name": "Archived",
                            "type": "project",
                            "path": "missing",
                            "status": "archived",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        config = temporary / "config.json"
        config.write_text(json.dumps({"knowledge_home": str(root)}), encoding="utf-8")
        return root, config

    def test_connected_constellation_leaves_space_between_stars(self) -> None:
        nodes = [{"id": f"n{index}"} for index in range(100)]
        edges = [{"source": f"n{index}", "target": f"n{(index + 1) % 100}"} for index in range(100)]
        edges += [{"source": "n0", "target": f"n{index}"} for index in range(2, 100, 3)]
        points = list(_constellation_positions(nodes, edges).values())
        # Cover a connected mass with a hub, not just separate pairs. The old
        # layout packed neighboring centers about 28 units apart.
        self.assertGreater(min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1:]), 42)

    def run_generator(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_generates_searchable_repository_and_note_overview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _root, config = self.make_knowledge_home(temporary)
            output = temporary / "overview.html"
            completed = self.run_generator("--config", str(config), "--output", str(output))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML=PASS", completed.stdout)
            self.assertIn("HANOS_HTML_REPOSITORIES=2", completed.stdout)
            self.assertIn("HANOS_HTML_NOTES=2", completed.stdout)
            self.assertIn("HANOS_HTML_CONNECTIONS=3", completed.stdout)
            self.assertIn("HANOS_HTML_UNRESOLVED=2", completed.stdout)
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("Global", rendered)
            self.assertIn("Demo Project", rendered)
            self.assertIn("CONFIRMED_LOCAL", rendered)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
            self.assertNotIn("<script>alert(1)</script>", rendered)
            self.assertIn("id=\"search\"", rendered)
            self.assertIn("HanOS 知识库总览", rendered)
            self.assertIn("知识图谱", rendered)
            self.assertIn('id="graph"', rendered)
            self.assertIn('id="note-reader"', rendered)
            self.assertIn('id="reader-content"', rendered)
            self.assertIn('返回知识图谱', rendered)
            self.assertIn('height:100dvh', rendered)
            self.assertIn("document.body.classList.add('reader-open')", rendered)
            self.assertIn('id="graph-fullscreen"', rendered)
            self.assertIn('id="graph-fit"', rendered)
            # Controls and the reader must remain in the fullscreen subtree.
            class TitleBarParser(HTMLParser):
                def __init__(self) -> None:
                    super().__init__()
                    self.divs: list[str | None] = []
                    self.contained: set[str] = set()

                def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                    identity = dict(attrs).get("id")
                    if identity in {"note-reader", "graph-fullscreen"} and "graph-canvas" in self.divs:
                        self.contained.add(identity)
                    if tag == "div":
                        self.divs.append(identity)

                def handle_endtag(self, tag: str) -> None:
                    if tag == "div" and self.divs:
                        self.divs.pop()

            structure = TitleBarParser()
            structure.feed(rendered)
            self.assertEqual(structure.contained, {"note-reader", "graph-fullscreen"})
            self.assertIn('pointerenter', rendered)
            self.assertIn("function openNote(node)", rendered)
            self.assertIn('pointerInViewBox', rendered)
            self.assertIn('const worldX = (anchorX - offsetX) / scale', rendered)
            self.assertNotIn('function stepMotion(now)', rendered)
            self.assertNotIn('pointerInWorld', rendered)
            self.assertIn("if (!dragging) return", rendered)
            self.assertIn('HanOS 星空知识图谱', rendered)
            self.assertIn('id="graph-stars"', rendered)
            self.assertNotIn('class="graph-space"', rendered)
            self.assertIn('background-star', rendered)
            self.assertIn('tone-white', rendered)
            self.assertIn('data-theme="midnight-atlas"', rendered)
            self.assertLess(rendered.index('class="graph-panel"'), rendered.index('class="stats"'))
            self.assertIn('"connection_count":3', rendered)
            self.assertIn('"unresolved_count":2', rendered)

    def test_graph_resolves_unique_wiki_links_and_keeps_unresolved_links_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            (root / "projects/demo/second.md").write_text(
                "# Second\n\nLink to [[Global]], [Home](../../global/00_Overview.md), and #research.\n", encoding="utf-8"
            )
            output = temporary / "graph.html"
            completed = self.run_generator("--knowledge-home", str(root), "--output", str(output))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            rendered = output.read_text(encoding="utf-8")
            self.assertIn('"kind":"tag"', rendered)
            self.assertIn('"label":"#research"', rendered)
            self.assertIn('"kind":"unresolved"', rendered)
            self.assertIn('"label":"Missing Note"', rendered)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for generated-script runtime checks")
    def test_generated_script_initializes_nodes_and_handles_reading_and_navigation(self) -> None:
        # Execute the actual generated script against a small event-capable DOM
        # fixture. This catches runtime failures that HTML substring checks miss;
        # it does not replace browser rendering or accessibility verification.
        runtime_check = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const html = require('node:fs').readFileSync(0, 'utf8');
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
const data = JSON.parse(scripts.find(match => match[1].includes('application/json'))[2]);
const elements = new Map();
let viewportWidth = 1200, viewportHeight = 600;
class Element {
  constructor(tagName = 'div') {
    this.tagName = tagName; this.children = []; this.attrs = {}; this.dataset = {}; this.style = {};
    this._textContent = ''; this.innerHTML = ''; this.events = new Map(); this.classes = new Set(); this.inert = false; this.hidden = false;
    this.classList = {
      add: name => this.classes.add(name), remove: name => this.classes.delete(name), contains: name => this.classes.has(name),
      toggle: (name, force) => { const enabled = force === undefined ? !this.classes.has(name) : force; if (enabled) this.classes.add(name); else this.classes.delete(name); }
    };
  }
  set textContent(value) { this.children = []; this._textContent = value; }
  get textContent() { return this._textContent + this.children.map(child => child.textContent).join(''); }
  setAttribute(name, value) { this.attrs[name] = String(value); if (name === 'class') this.classes = new Set(String(value).split(/\s+/)); if (name === 'hidden') this.hidden = true; }
  getAttribute(name) { return this.attrs[name]; }
  append(...children) { children.forEach(child => child.parentElement = this); this.children.push(...children); }
  appendChild(child) { this.append(child); }
  querySelector(selector) { return elements.get(selector.slice(1)); }
  querySelectorAll(selector) { return this.children.filter(child => child.classes.has(selector.slice(1))); }
  closest(selector) { for (let element = this; element; element = element.parentElement) if (element.classes.has(selector.slice(1))) return element; return null; }
  addEventListener(name, callback) { if (!this.events.has(name)) this.events.set(name, []); this.events.get(name).push(callback); }
  emit(name, event = {}) {
    for (let parent = this; parent; parent = parent.parentElement) if (parent.inert || parent.hidden) return;
    for (const callback of this.events.get(name) || []) callback({target: this, stopPropagation() {}, preventDefault() {}, ...event});
  }
  focus() { const previous = document.activeElement; document.activeElement = this; if (previous !== this) { previous?.emit('blur'); this.emit('focus'); } }
  setPointerCapture() {}
  createSVGPoint() { return {x: 0, y: 0}; }
  getBoundingClientRect() { return {left: 0, top: 0, width: viewportWidth, height: viewportHeight}; }
  requestFullscreen() { throw new Error('Embedded browsers must not require native fullscreen'); }
}
for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
  const element = new Element(match[1]);
  for (const attr of match[2].matchAll(/([a-zA-Z-]+)="([^"]*)"/g)) element.setAttribute(attr[1], attr[2]);
  elements.set(match[3], element);
}
elements.get('hanos-overview-data').textContent = JSON.stringify(data);
const document = new Element(); document.body = new Element();
document.createElementNS = (_, name) => new Element(name);
const pageBackground = ['page-header','search','overview-stats','repositories','page-footer'].map(id => elements.get(id));
const graphBackground = ['graph-header','graph-stage','graph-footer'].map(id => elements.get(id));
document.querySelectorAll = selector => selector.startsWith('main > header,') ? pageBackground : [];
document.exitFullscreen = () => { throw new Error('Native fullscreen must not be used'); };
for (const id of ['graph-zoom-in','graph-zoom-out','graph-readable','graph-fit','graph-reset','graph-fullscreen']) elements.get(id).parentElement = elements.get('graph-header');
elements.get('graph-motion').parentElement = elements.get('graph-footer');
elements.get('graph-nodes').parentElement = elements.get('graph-stage');
elements.get('reader-close').parentElement = elements.get('note-reader');
const context = vm.createContext({document, window: {open() { throw new Error('Unexpected navigation'); }}});
for (const match of scripts.filter(match => !match[1].includes('application/json'))) vm.runInContext(match[2], context, {filename: 'generated-overview.js', timeout: 1500});
assert.equal(vm.runInContext('renderNote("# Title\\n## Section\\n### Detail")', context),
  '<h1>Title</h1><h2>Section</h2><h3>Detail</h3>', 'Generated Markdown headings retain their hierarchy');
const nodes = elements.get('graph-nodes').children;
const svg = elements.get('graph');
assert.equal(nodes.length, data.graph.nodes.length);
assert.deepEqual(svg.attrs.viewBox.split(/\s+/).map(Number), [0, 0, data.graph.width, data.graph.height]);
assert.equal(elements.get('graph-edges').children.length, data.graph.edges.length);
const edges = elements.get('graph-edges').children;
edges.forEach((edge, index) => {
  assert.equal(edge.tagName, 'g');
  assert.equal(edge.children.length, 2, 'Each connection keeps a fixed thread plus a moving highlight');
  const [thread, flow] = edge.children;
  assert(thread.classList.contains('edge-thread') && flow.classList.contains('edge-flow'));
  const source = data.graph.nodes.find(node => node.id === data.graph.edges[index].source);
  const target = data.graph.nodes.find(node => node.id === data.graph.edges[index].target);
  for (const [key, value] of Object.entries({x1:source.x, y1:source.y, x2:target.x, y2:target.y})) {
    assert.equal(Number(thread.attrs[key]), value);
    assert.equal(flow.attrs[key], thread.attrs[key], 'Flow follows the existing connection exactly');
  }
  assert.equal(flow.attrs.pathLength, '100');
});
const transforms = nodes.map(node => node.attrs.transform);
const titles = nodes.map(node => node.children[1].textContent);
const labelPlacements = nodes.map(node => node.children[1].children.map(span => [span.attrs.x, span.attrs.y]));
function verifyAllTitles() {
  nodes.forEach((node, index) => {
    const original = data.graph.nodes[index], label = node.children[1];
    assert.equal(label.tagName, 'text');
    assert.equal(label.textContent, original.label, 'Every title is complete, with no truncation');
    assert(label.children.length > 0);
    assert(label.children.every(child => child.tagName === 'tspan'));
    assert.equal(Number(label.attrs['font-size']), data.graph.font_size);
    assert.equal(node.attrs.transform, `translate(${original.x} ${original.y})`);
    assert(!node.classList.contains('hidden') && !label.hidden);
    const star = node.children[0];
    assert.equal(star.tagName, 'g');
    assert(star.children.some(child => child.tagName === 'path' && child.classList.contains('star-rays') && child.attrs.d.includes('L')),
      'Each visible node needs star rays, not an outlined circle');
    assert(star.children.some(child => child.classList.contains('star-core')));
    assert.equal(Number(node.children[2].attrs.r), original.hit_radius);
    assert.equal(original.hit_radius, 11, 'The larger target matches the reserved layout space');
    assert(original.radius * 1.1 + .35 <= original.hit_radius, 'Every star ray and focus stroke fits inside the click target');
    const titleHit = node.children[3];
    assert.equal(titleHit.tagName, 'rect');
    assert.equal(Number(titleHit.attrs.x), original.label_x);
    assert.equal(Number(titleHit.attrs.y), original.label_y - data.graph.font_size);
    assert.equal(Number(titleHit.attrs.width), original.label_width);
    assert.equal(Number(titleHit.attrs.height), original.label_height);
  });
  assert.deepEqual(nodes.map(node => node.children[1].textContent), titles);
  assert.deepEqual(nodes.map(node => node.children[1].children.map(span => [span.attrs.x, span.attrs.y])), labelPlacements,
    'Hover and zoom must not rearrange or remove titles');
  assert.deepEqual(nodes.map(node => node.attrs.transform), transforms, 'Nodes remain stationary within the graph');
}
verifyAllTitles();
function verifyReadableView() {
  const [scale, dx, dy] = vm.runInContext('[scale, offsetX, offsetY]', context);
  const unit = Math.min(viewportWidth / data.graph.width, viewportHeight / data.graph.height);
  assert(data.graph.font_size * unit * scale >= 12 - 1e-8, 'Clear view opens with legible small titles');
  assert(Math.abs(dx + data.graph.width * (scale - 1) / 2) < 1e-8, 'Clear view zooms toward the horizontal center');
  assert(Math.abs(dy + data.graph.height * (scale - 1) / 2) < 1e-8, 'Clear view zooms toward the vertical center');
  verifyAllTitles();
}
verifyReadableView();
const motionButton = elements.get('graph-motion');
const edgeGeometry = edges.map(edge => edge.children.map(line => ({...line.attrs})));
motionButton.emit('click');
assert(elements.get('graph-edges').classList.contains('motion-paused'));
assert.equal(motionButton.textContent, '开启动效');
motionButton.emit('click');
assert(!elements.get('graph-edges').classList.contains('motion-paused'));
assert.equal(motionButton.textContent, '暂停动效');
assert.deepEqual(edges.map(edge => edge.children.map(line => ({...line.attrs}))), edgeGeometry);
verifyAllTitles();
assert(nodes.some(node => node.classes.has('tone-blue')) && nodes.some(node => node.classes.has('tone-white')));
svg.emit('pointermove', {clientX: 350, clientY: 240}); verifyAllTitles();
const noteIndex = data.graph.nodes.findIndex(node => node.kind === 'note' && node.degree > 0);
const note = data.graph.nodes[noteIndex];
nodes[noteIndex].emit('pointerenter');
const related = new Set([note.id]);
for (const edge of data.graph.edges) { if (edge.source === note.id) related.add(edge.target); if (edge.target === note.id) related.add(edge.source); }
nodes.forEach((node, index) => {
  assert.equal(node.classList.contains('muted'), !related.has(data.graph.nodes[index].id));
  assert.equal(node.classList.contains('related'), related.has(data.graph.nodes[index].id));
});
edges.forEach((edge, index) => {
  const connection = data.graph.edges[index];
  const connected = connection.source === note.id || connection.target === note.id;
  assert.equal(edge.classList.contains('related'), connected);
  assert.equal(edge.classList.contains('muted'), !connected);
});
verifyAllTitles();
nodes[noteIndex].emit('pointerleave');
assert(nodes.every(node => !node.classList.contains('muted') && !node.classList.contains('related')));
assert(edges.every(edge => !edge.classList.contains('muted') && !edge.classList.contains('related')));
nodes.forEach((node, index) => {
  if (data.graph.nodes[index].kind === 'note') return;
  node.emit('click'); assert(!elements.get('note-reader').classList.contains('visible')); verifyAllTitles(); node.emit('pointerleave');
});
svg.emit('pointerdown', {target:nodes[noteIndex].children[3], clientX:350, clientY:240, pointerId:1});
assert.equal(vm.runInContext('dragging', context), false, 'Clicking a title must not start background dragging');
nodes[noteIndex].emit('click', {target:nodes[noteIndex].children[3]});
assert(elements.get('note-reader').classList.contains('visible'));
assert.equal(elements.get('reader-title').textContent, note.label);
assert(elements.get('reader-content').innerHTML.length > 0);
assert(elements.get('graph-stage').inert && elements.get('search').inert);
assert.equal(document.activeElement, elements.get('reader-close'));
let preventedTab = false;
document.emit('keydown', {key: 'Tab', shiftKey: true, preventDefault() { preventedTab = true; }});
assert(preventedTab && document.activeElement === elements.get('reader-close'));
elements.get('reader-close').emit('click');
assert(!elements.get('note-reader').classList.contains('visible'));
assert.equal(document.activeElement, nodes[noteIndex]);
assert(!elements.get('graph-stage').inert && !elements.get('search').inert);
nodes[noteIndex].emit('focus'); assert.equal(nodes[noteIndex].attrs.role, 'button');
assert.equal(nodes[noteIndex].attrs.tabindex, '0');
nodes[noteIndex].emit('keydown', {key: 'Enter'});
assert(elements.get('note-reader').classList.contains('visible')); elements.get('reader-close').emit('click');
document.body.style.overflow = 'scroll';
const expandedPanel = elements.get('graph-panel');
const fullscreenButton = elements.get('graph-fullscreen');
function verifyExpandedControls() {
  assert(graphBackground.every(element => !element.inert), 'Expanded graph controls remain interactive');
  elements.get('graph-fit').emit('click');
  const before = vm.runInContext('scale', context);
  elements.get('graph-zoom-in').emit('click'); assert(vm.runInContext('scale', context) > before);
  elements.get('graph-zoom-out').emit('click'); assert(vm.runInContext('scale', context) < before * 1.22);
  elements.get('graph-readable').emit('click'); verifyReadableView();
  nodes[noteIndex].emit('pointerenter'); elements.get('graph-reset').emit('click');
  assert(nodes.every(node => !node.classList.contains('related')));
  const paused = elements.get('graph-edges').classList.contains('motion-paused');
  motionButton.emit('click'); assert.equal(elements.get('graph-edges').classList.contains('motion-paused'), !paused);
  motionButton.emit('click');
}
for (let pass = 0; pass < 2; pass++) {
  fullscreenButton.emit('click');
  assert(expandedPanel.classList.contains('is-expanded'));
  assert.equal(fullscreenButton.textContent, '退出全屏');
  assert.equal(fullscreenButton.attrs['aria-expanded'], 'true');
  assert(pageBackground.every(element => element.inert));
  assert.equal(document.body.style.overflow, 'hidden');
  verifyExpandedControls();
  nodes[noteIndex].emit('click');
  assert(!elements.get('note-reader').hidden);
  assert(graphBackground.every(element => element.inert));
  const readingScale = vm.runInContext('scale', context);
  elements.get('graph-zoom-in').emit('click'); assert.equal(vm.runInContext('scale', context), readingScale);
  if (pass === 0) elements.get('reader-close').emit('click');
  else document.emit('keydown', {key:'Escape'});
  assert(elements.get('note-reader').hidden);
  assert(expandedPanel.classList.contains('is-expanded'), 'Closing a note retains expanded graph');
  assert.equal(document.body.style.overflow, 'hidden');
  assert.equal(document.activeElement, nodes[noteIndex]);
  verifyExpandedControls();
  if (pass === 0) fullscreenButton.emit('click');
  else document.emit('keydown', {key:'Escape'});
  assert(!expandedPanel.classList.contains('is-expanded'));
  assert.equal(fullscreenButton.textContent, '全屏查看');
  assert.equal(fullscreenButton.attrs['aria-expanded'], 'false');
  assert(pageBackground.every(element => !element.inert));
  assert.equal(document.body.style.overflow, 'scroll');
  assert.equal(document.activeElement, fullscreenButton);
}
nodes[noteIndex].emit('click');
document.emit('keydown', {key:'Escape'});
assert(elements.get('note-reader').hidden);
assert.equal(document.body.style.overflow, 'scroll', 'Ordinary note reading also restores scrolling');
const viewBeforeClear = elements.get('graph-viewport').attrs.transform;
elements.get('graph-reset').emit('click'); verifyAllTitles();
assert.equal(elements.get('graph-viewport').attrs.transform, viewBeforeClear, 'Clearing selection preserves the reading view');
assert(nodes.every(node => !node.classList.contains('muted') && !node.classList.contains('related')));
elements.get('graph-fit').emit('click');
elements.get('graph-zoom-in').emit('click');
assert.match(elements.get('graph-viewport').attrs.transform, /scale\(1\.22\)/); verifyAllTitles();
function worldUnder(clientX, clientY) {
  const [scale, dx, dy] = vm.runInContext('[scale, offsetX, offsetY]', context);
  const w = data.graph.width, h = data.graph.height, unit = Math.min(viewportWidth / w, viewportHeight / h);
  return [((clientX - (viewportWidth - w * unit) / 2) / unit - dx) / scale,
    ((clientY - (viewportHeight - h * unit) / 2) / unit - dy) / scale];
}
function wheelScale(deltas, deltaMode = 0) {
  elements.get('graph-fit').emit('click');
  deltas.forEach(deltaY => svg.emit('wheel', {clientX:400, clientY:250, deltaY, deltaMode}));
  return vm.runInContext('scale', context);
}
const microStep = wheelScale([-1]);
assert(microStep > 1 && microStep < 1.002, 'A tiny trackpad motion must be a fine adjustment');
assert(Math.abs(wheelScale(Array(16).fill(-1)) - wheelScale([-16])) < 1e-10,
  'Equal scroll distances behave equally regardless of event frequency');
assert(Math.abs(wheelScale([-1], 1) - wheelScale([-16])) < 1e-10, 'Line mode is normalized');
assert(wheelScale([-10000]) < 1.05, 'A large wheel jump is capped below five percent');
assert(wheelScale([-1], 2) < 1.05, 'Page-mode wheel jumps are also bounded');
assert.equal(wheelScale([0]), 1, 'Horizontal-only scroll does not zoom');
assert.equal(wheelScale([NaN, Infinity]), 1, 'Invalid wheel input leaves the viewport intact');
assert(Math.abs(wheelScale([-20,20]) - 1) < 1e-10, 'Opposite gestures restore the same scale');
for (const [width, height] of [[1200,600],[480,420],[320,360],[1400,900]]) {
  viewportWidth = width; viewportHeight = height;
  elements.get('graph-readable').emit('click'); verifyReadableView();
  const px = width * .63, py = height * .42, before = worldUnder(px, py);
  svg.emit('wheel', {clientX: px, clientY: py, deltaY: -1});
  const after = worldUnder(px, py);
  assert(before.every((value, index) => Math.abs(value - after[index]) < 1e-8), 'Wheel zoom stays anchored under the cursor for dynamic bounds');
  verifyAllTitles();
  nodes[noteIndex].emit('pointerenter'); verifyAllTitles(); nodes[noteIndex].emit('pointerleave');
}
const zoomed = elements.get('graph-viewport').attrs.transform;
svg.emit('pointerdown', {clientX: 20, clientY: 20, pointerId: 1}); svg.emit('pointermove', {clientX: 60, clientY: 40}); svg.emit('pointerup');
assert.notEqual(elements.get('graph-viewport').attrs.transform, zoomed); verifyAllTitles();
elements.get('graph-fit').emit('click');
assert.equal(elements.get('graph-viewport').attrs.transform, 'translate(0 0) scale(1)'); verifyAllTitles();
viewportWidth = 320; viewportHeight = 360;
for (let index = 0; index < 60; index++) elements.get('graph-zoom-in').emit('click');
const maximumScale = vm.runInContext('scale', context);
const fitUnit = Math.min(viewportWidth / data.graph.width, viewportHeight / data.graph.height);
assert(data.graph.font_size * fitUnit * maximumScale >= 18 - 1e-8, 'Even a narrow screen can zoom full titles up to a readable size');
verifyAllTitles();
viewportWidth = 1400; viewportHeight = 900;
fullscreenButton.emit('click');
elements.get('graph-zoom-in').emit('click');
assert(vm.runInContext('scale', context) >= maximumScale, 'Zooming in after enlarging the viewport must never zoom out');
verifyAllTitles();
console.log(JSON.stringify({nodes:nodes.length, permanentTitles:titles.length}));
"""
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, config = self.make_knowledge_home(temporary)
            output = temporary / "runtime.html"
            for size in (0, 60):
                with self.subTest(extra_notes=size):
                    for index in range(size):
                        (root / f"projects/demo/note-{index}.md").write_text(
                            f"# 第 {index} 篇：关于生活与学习的长标题以及个人感受记录\n\n"
                            f"[[00_Overview]] [[note-{(index + 1) % size}]] #共同主题 [[Missing Note]]\n",
                            encoding="utf-8",
                        )
                    generated = self.run_generator("--config", str(config), "--output", str(output))
                    self.assertEqual(generated.returncode, 0, generated.stderr)
                    completed = subprocess.run(
                        [shutil.which("node"), "-e", runtime_check],
                        input=output.read_text(encoding="utf-8"),
                        capture_output=True, text=True, check=False, timeout=10,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_graph_resolves_relative_markdown_links_from_source_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            (root / "projects/demo/guides").mkdir()
            (root / "projects/demo/guides/start.md").write_text(
                "# Start\n\nA nested note.\n", encoding="utf-8"
            )
            (root / "projects/demo/second.md").write_text(
                "# Second\n\nRead [Start](guides/start.md).\n",
                encoding="utf-8",
            )
            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML_UNRESOLVED=2", completed.stdout)
            output = root / ".hanos/knowledge-overview.html"
            rendered = output.read_text(encoding="utf-8")
            self.assertIn('"source":"note:projects/demo/second.md","target":"note:projects/demo/guides/start.md"', rendered)

    def test_graph_rejects_malformed_repository_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            registry = root / ".hanos/repositories.json"
            document = json.loads(registry.read_text(encoding="utf-8"))
            document["repositories"][0]["status"] = None
            registry.write_text(json.dumps(document), encoding="utf-8")

            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 2)
            self.assertIn("HANOS_HTML_ERROR=repository registry entry has an invalid status", completed.stderr)

    def test_default_output_is_inside_control_directory_and_is_ignored_on_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, config = self.make_knowledge_home(temporary)
            first = self.run_generator("--config", str(config))
            second = self.run_generator("--config", str(config))

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue((root / ".hanos/knowledge-overview.html").is_file())
            self.assertIn("HANOS_HTML_NOTES=2", second.stdout)

    def test_output_rejects_markdown_and_preserves_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.make_knowledge_home(Path(directory))
            note = root / "global/00_Overview.md"
            original = note.read_bytes()

            completed = self.run_generator("--config", str(config), "--output", str(note))

            self.assertEqual(completed.returncode, 2, completed.stdout)
            self.assertIn("HANOS_HTML_ERROR=", completed.stderr)
            self.assertEqual(note.read_bytes(), original)

    def test_output_rejects_config_and_registry_with_html_names(self) -> None:
        for authority in ("config", "registry"):
            with self.subTest(authority=authority), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                root, config = self.make_knowledge_home(temporary)
                if authority == "config":
                    renamed = temporary / "config.html"
                    config.rename(renamed)
                    config = renamed
                else:
                    registry = root / ".hanos/repositories.json"
                    renamed = root / ".hanos/registry.html"
                    registry.rename(renamed)
                    registry.symlink_to(renamed)
                original = renamed.read_bytes()

                completed = self.run_generator("--config", str(config), "--output", str(renamed))

                self.assertEqual(completed.returncode, 2, completed.stdout)
                self.assertIn("HANOS_HTML_ERROR=", completed.stderr)
                self.assertEqual(renamed.read_bytes(), original)

    def test_output_rejects_html_symlinks_to_authoritative_inputs(self) -> None:
        for authority in ("note", "config", "registry"):
            with self.subTest(authority=authority), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                root, config = self.make_knowledge_home(temporary)
                source = {
                    "note": root / "global/00_Overview.md",
                    "config": config,
                    "registry": root / ".hanos/repositories.json",
                }[authority]
                original = source.read_bytes()
                output = temporary / "overview.html"
                output.symlink_to(source)

                completed = self.run_generator("--config", str(config), "--output", str(output))

                self.assertEqual(completed.returncode, 2, completed.stdout)
                self.assertIn("HANOS_HTML_ERROR=", completed.stderr)
                self.assertTrue(output.is_symlink(), "A rejected output must preserve the source alias")
                self.assertEqual(source.read_bytes(), original)

    def test_output_rejects_existing_non_html_content(self) -> None:
        for original in (b"# Existing private note\n", b'{"existing": "config"}\n', b"binary\xff"):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                _root, config = self.make_knowledge_home(temporary)
                output = temporary / "overview.html"
                output.write_bytes(original)

                completed = self.run_generator("--config", str(config), "--output", str(output))

                self.assertEqual(completed.returncode, 2, completed.stdout)
                self.assertIn("HANOS_HTML_ERROR=", completed.stderr)
                self.assertEqual(output.read_bytes(), original)

    def test_explicit_external_html_output_can_be_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, config = self.make_knowledge_home(temporary)
            output = temporary / "exports/overview.htm"
            first = self.run_generator("--config", str(config), "--output", str(output))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertIn("HANOS_HTML_NOTES=2", first.stdout)
            (root / "global/new.md").write_text("# Newly recorded\n\nREFRESHED_NOTE_CONTENT\n", encoding="utf-8")

            second = self.run_generator("--config", str(config), "--output", str(output))

            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("HANOS_HTML_NOTES=3", second.stdout)
            self.assertIn("REFRESHED_NOTE_CONTENT", output.read_text(encoding="utf-8"))

    def test_markdown_symlinks_do_not_import_control_directory_content(self) -> None:
        for control in (".hanos", ".git", ".obsidian", "node_modules"):
            with self.subTest(control=control), tempfile.TemporaryDirectory() as directory:
                root, config = self.make_knowledge_home(Path(directory))
                target = root / control / "private.md"
                target.parent.mkdir(exist_ok=True)
                target.write_text("# Control file\n\nCONTROL_CONTENT_MUST_STAY_EXCLUDED\n", encoding="utf-8")
                (root / "global/shortcut.md").symlink_to(target)

                completed = self.run_generator("--config", str(config))

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("HANOS_HTML_NOTES=2", completed.stdout)
                rendered = (root / ".hanos/knowledge-overview.html").read_text(encoding="utf-8")
                self.assertNotIn("CONTROL_CONTENT_MUST_STAY_EXCLUDED", rendered)

    def test_markdown_symlinks_do_not_import_non_markdown_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.make_knowledge_home(Path(directory))
            target = root / "private.txt"
            target.write_text("# Private text\n\nNON_MARKDOWN_CONTENT_MUST_STAY_EXCLUDED\n", encoding="utf-8")
            (root / "global/shortcut.md").symlink_to(target)

            completed = self.run_generator("--config", str(config))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML_NOTES=2", completed.stdout)
            rendered = (root / ".hanos/knowledge-overview.html").read_text(encoding="utf-8")
            self.assertNotIn("NON_MARKDOWN_CONTENT_MUST_STAY_EXCLUDED", rendered)

    def test_markdown_symlink_to_an_allowed_in_home_note_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, config = self.make_knowledge_home(Path(directory))
            target = root / "linked-note.md"
            target.write_text("# Linked note\n\nALLOWED_LINKED_NOTE\n", encoding="utf-8")
            (root / "global/shortcut.md").symlink_to(target)

            completed = self.run_generator("--config", str(config))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML_NOTES=3", completed.stdout)
            rendered = (root / ".hanos/knowledge-overview.html").read_text(encoding="utf-8")
            self.assertIn("ALLOWED_LINKED_NOTE", rendered)

    def test_active_repository_cannot_escape_knowledge_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, config = self.make_knowledge_home(temporary)
            registry = root / ".hanos/repositories.json"
            document = json.loads(registry.read_text(encoding="utf-8"))
            document["repositories"][0]["path"] = str(temporary / "outside")
            (temporary / "outside").mkdir()
            registry.write_text(json.dumps(document), encoding="utf-8")

            completed = self.run_generator("--config", str(config))

            self.assertEqual(completed.returncode, 2)
            self.assertIn("HANOS_HTML_ERROR=repository global escapes", completed.stderr)
            self.assertFalse((root / ".hanos/knowledge-overview.html").exists())

    def test_default_output_rejects_a_control_directory_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            outside = temporary / "outside/control"
            outside.mkdir(parents=True)
            registry_copy = root / "registry.json"
            registry_copy.write_bytes((root / ".hanos/repositories.json").read_bytes())
            (root / ".hanos/repositories.json").unlink()
            (outside / "repositories.json").symlink_to(registry_copy)
            (root / ".hanos").rmdir()
            (root / ".hanos").symlink_to(outside, target_is_directory=True)

            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 2)
            self.assertIn("HANOS_HTML_ERROR=HTML output directory escapes", completed.stderr)
            self.assertFalse((outside / "knowledge-overview.html").exists())

    def test_control_directory_repository_is_not_scanned_as_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            (root / ".GIT").mkdir()
            (root / ".GIT/secret.md").write_text("# Should stay hidden\n", encoding="utf-8")
            document = json.loads((root / ".hanos/repositories.json").read_text(encoding="utf-8"))
            document["repositories"] = [
                {
                    "id": "control",
                    "name": "Control",
                    "type": "project",
                    "path": ".GIT",
                    "status": "active",
                }
            ]
            (root / ".hanos/repositories.json").write_text(
                json.dumps(document), encoding="utf-8"
            )

            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML_NOTES=0", completed.stdout)

    def test_malformed_repository_entry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            registry = root / ".hanos/repositories.json"
            document = json.loads(registry.read_text(encoding="utf-8"))
            document["repositories"] = [None]
            registry.write_text(json.dumps(document), encoding="utf-8")

            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 2)
            self.assertIn("HANOS_HTML_ERROR=repository registry contains a non-object entry", completed.stderr)

    def test_legacy_yaml_registry_is_supported_without_external_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            root, _config = self.make_knowledge_home(temporary)
            (root / ".hanos/repositories.json").unlink()
            (root / ".hanos/repositories.yaml").write_text(
                """version: 1

repositories:
  - id: global
    name: Global
    type: global
    path: global
    status: active
    aliases:
      - shared
""",
                encoding="utf-8",
            )

            completed = self.run_generator("--knowledge-home", str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("HANOS_HTML_REPOSITORIES=1", completed.stdout)
            self.assertIn("HANOS_HTML_NOTES=1", completed.stdout)


if __name__ == "__main__":
    unittest.main()
