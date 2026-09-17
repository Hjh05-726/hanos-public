"""Deterministic star-and-title placement without browser font measurements.

The returned positions, font metrics, and dimensions share one world coordinate
system. Draw each label line at ``(x + label_x, y + label_y + i * line_height)``.
``label_y`` is the first baseline; ``label_height`` includes all line boxes.
Use a transparent hit circle of radius 11: its space is reserved by this layout.
"""

from __future__ import annotations

import heapq
import math
import unicodedata


FONT_SIZE = 11.0
LINE_HEIGHT = 15.0
MAX_LABEL_WIDTH = 14 * FONT_SIZE
HIT_RADIUS = 11.0
PADDING = 3.0
MARGIN = 20.0
EPSILON = 0.00001
MAX_SEARCH_STEPS = 1800


def _character_width(character):
    category = unicodedata.category(character)
    if category in {"Mn", "Me", "Cf", "Cc"}:
        return 0.0
    if unicodedata.east_asian_width(character) in {"W", "F", "A"}:
        return FONT_SIZE
    if character.isspace():
        return FONT_SIZE * 0.4
    if character in "MWmw@%&":
        return FONT_SIZE
    if character.isupper():
        return FONT_SIZE * 0.8
    # A little wider than common sans-serif Latin glyphs, so text stays clear.
    return FONT_SIZE * 0.7


def _title_units(title):
    """Keep combining marks and common emoji sequences with their base glyph.

    Python's standard library has no grapheme-segmentation API. These units
    cover combining marks, ZWJ emoji, modifiers, and paired flag indicators.
    """
    current = ""
    for character in title:
        codepoint = ord(character)
        regional = 0x1F1E6 <= codepoint <= 0x1F1FF
        paired_flag = regional and len(current) == 1 and 0x1F1E6 <= ord(current) <= 0x1F1FF
        extension = (
            unicodedata.category(character).startswith("M")
            or 0x1F3FB <= codepoint <= 0x1F3FF
            or 0xE0020 <= codepoint <= 0xE007F
            or character == "\u200d"
        )
        if not current or extension or current.endswith("\u200d") or paired_flag:
            current += character
        else:
            yield current
            current = character
    if current:
        yield current


def _wrap_title(title):
    lines = []
    current = ""
    width = 0.0
    widths = []
    for unit in _title_units(title):
        advance = sum(_character_width(character) for character in unit)
        if current and width + advance > MAX_LABEL_WIDTH + EPSILON:
            lines.append(current)
            widths.append(width)
            current, width = "", 0.0
        current += unit
        width += advance
    lines.append(current)
    widths.append(width)
    return lines, max(widths)


def _finite_number(value, default):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _bounds(x, y, local):
    return (x + local[0], y + local[1], x + local[2], y + local[3])


def _overlaps(first, second):
    return (
        min(first[2], second[2]) - max(first[0], second[0]) > EPSILON / 2
        and min(first[3], second[3]) - max(first[1], second[1]) > EPSILON / 2
    )


class _OccupiedSpace:
    """A small spatial index keeps collision work local even for larger maps."""

    CELL_SIZE = 128.0

    def __init__(self):
        self.rectangles = []
        self.cells = {}
        self.max_width = 0.0
        self.max_height = 0.0

    def _keys(self, rectangle):
        left, top, right, bottom = rectangle
        for column in range(math.floor(left / self.CELL_SIZE), math.floor(right / self.CELL_SIZE) + 1):
            for row in range(math.floor(top / self.CELL_SIZE), math.floor(bottom / self.CELL_SIZE) + 1):
                yield column, row

    def add(self, rectangle):
        index = len(self.rectangles)
        self.rectangles.append(rectangle)
        self.max_width = max(self.max_width, rectangle[2] - rectangle[0])
        self.max_height = max(self.max_height, rectangle[3] - rectangle[1])
        for key in self._keys(rectangle):
            self.cells.setdefault(key, []).append(index)

    def first_collision(self, rectangle):
        candidates = set()
        for key in self._keys(rectangle):
            candidates.update(self.cells.get(key, ()))
        for index in sorted(candidates):
            existing = self.rectangles[index]
            if _overlaps(rectangle, existing):
                return existing
        return None


def _grid_clear_position(origin_x, origin_y, local, occupied):
    """Find a nearby free two-dimensional cell after the fine search budget.

    Each existing rectangle can obstruct at most four candidate cells, since
    the cell steps exceed every rectangle's width and height. More than four
    cells per existing rectangle therefore guarantees a clear candidate.
    """
    cell_width = max(local[2] - local[0], occupied.max_width) + EPSILON
    cell_height = max(local[3] - local[1], occupied.max_height) + EPSILON
    count = 4 * len(occupied.rectangles) + 1
    columns = max(1, math.ceil(math.sqrt(count * cell_height / cell_width * 1.6)))
    rows = math.ceil(count / columns)
    candidates = []
    for column in range(columns):
        x = origin_x + (column - (columns - 1) / 2) * cell_width
        for row in range(rows):
            y = origin_y + (row - (rows - 1) / 2) * cell_height
            distance = ((x - origin_x) / 1.45) ** 2 + (y - origin_y) ** 2
            candidates.append((distance, x, y))
    for _, x, y in sorted(candidates):
        if occupied.first_collision(_bounds(x, y, local)) is None:
            return x, y
    raise RuntimeError("Star atlas grid did not contain the guaranteed free cell")


def _nearest_clear_position(origin_x, origin_y, local, occupied):
    """Try nearby rectangle edges in distance order, with a bounded fallback."""
    queue = []
    seen = set()

    def offer(x, y):
        key = (round(x, 5), round(y, 5))
        if key in seen:
            return
        seen.add(key)
        # A wide search ellipse fits the atlas shape without forcing a ring.
        distance = ((x - origin_x) / 1.45) ** 2 + (y - origin_y) ** 2
        heapq.heappush(queue, (distance, x, y))

    offer(origin_x, origin_y)
    for _ in range(MAX_SEARCH_STEPS):
        if not queue:
            break
        _, x, y = heapq.heappop(queue)
        collision = occupied.first_collision(_bounds(x, y, local))
        if collision is None:
            return x, y
        left, top, right, bottom = collision
        offer(left - local[2] - EPSILON, y)
        offer(right - local[0] + EPSILON, y)
        offer(x, top - local[3] - EPSILON)
        offer(x, bottom - local[1] + EPSILON)

    return _grid_clear_position(origin_x, origin_y, local, occupied)


def prepare_star_atlas(nodes, positions):
    """Return complete title lines and a collision-free static star atlas.

    ``nodes`` contains unique string IDs, string labels, and optional degrees;
    ``positions`` maps IDs to their existing ``(x, y)`` graph coordinates.
    Input collections are never modified. Node kinds do not change visibility.
    """
    placed = {}
    occupied = _OccupiedSpace()
    # Keep the initial density similar as collections grow beyond one atlas.
    spread = math.sqrt(max(1.0, len(nodes) / 99))
    for node in sorted(nodes, key=lambda item: item["id"]):
        node_id = node["id"]
        if node_id in placed:
            raise ValueError("Star atlas node IDs must be unique")
        title = node["label"]
        if not isinstance(title, str):
            raise ValueError("Star atlas labels must be strings")
        lines, width = _wrap_title(title)
        degree = max(0.0, _finite_number(node.get("degree", 0), 0.0))
        radius = (4.0 + min(4.0, math.sqrt(degree) * 0.6)) * 1.2
        label_x = radius + 7.0
        height = len(lines) * LINE_HEIGHT
        label_y = -height / 2 + FONT_SIZE
        local = (
            -HIT_RADIUS - PADDING,
            min(-HIT_RADIUS, -height / 2) - PADDING,
            max(HIT_RADIUS, label_x + width) + PADDING,
            max(HIT_RADIUS, height / 2) + PADDING,
        )
        point = positions.get(node_id, (500.0, 280.0))
        origin_x = _finite_number(point[0], 500.0) * 1.1 * spread
        origin_y = _finite_number(point[1], 280.0) * 1.15 * spread
        x, y = _nearest_clear_position(origin_x, origin_y, local, occupied)
        placed[node_id] = {
            "x": x, "y": y, "label_lines": lines,
            "label_x": label_x, "label_y": label_y,
            "label_width": width, "label_height": height, "radius": radius,
            "hit_radius": HIT_RADIUS,
        }
        occupied.add(_bounds(x, y, local))

    if not placed:
        return {"nodes": {}, "width": MARGIN * 2, "height": MARGIN * 2,
                "font_size": FONT_SIZE, "line_height": LINE_HEIGHT}

    left = min(rectangle[0] for rectangle in occupied.rectangles)
    top = min(rectangle[1] for rectangle in occupied.rectangles)
    right = max(rectangle[2] for rectangle in occupied.rectangles)
    bottom = max(rectangle[3] for rectangle in occupied.rectangles)
    for node in placed.values():
        node["x"] += MARGIN - left
        node["y"] += MARGIN - top
    return {
        "nodes": placed, "width": right - left + MARGIN * 2,
        "height": bottom - top + MARGIN * 2,
        "font_size": FONT_SIZE, "line_height": LINE_HEIGHT,
    }
