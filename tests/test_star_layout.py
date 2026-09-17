"""Behavior checks for complete, non-overlapping star-map titles."""

import importlib.util
import math
from pathlib import Path
import random
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "hanos" / "scripts" / "star_layout.py"
)
SPEC = importlib.util.spec_from_file_location("star_layout", MODULE_PATH)
star_layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(star_layout)


def bounds(node, font_size):
    """Include the clickable circle, text block, and three units of air."""
    return (
        node["x"] - 14,
        node["y"] + min(-11, node["label_y"] - font_size) - 3,
        node["x"] + max(11, node["label_x"] + node["label_width"]) + 3,
        node["y"] + max(11, node["label_y"] - font_size + node["label_height"]) + 3,
    )


class StarLayoutTests(unittest.TestCase):
    def assert_clear(self, atlas):
        rectangles = [bounds(node, atlas["font_size"]) for node in atlas["nodes"].values()]
        for index, first in enumerate(rectangles):
            self.assertGreaterEqual(first[0], 20 - 1e-6)
            self.assertGreaterEqual(first[1], 20 - 1e-6)
            self.assertLessEqual(first[2], atlas["width"] - 20 + 1e-6)
            self.assertLessEqual(first[3], atlas["height"] - 20 + 1e-6)
            for second in rectangles[index + 1:]:
                overlap_x = min(first[2], second[2]) - max(first[0], second[0])
                overlap_y = min(first[3], second[3]) - max(first[1], second[1])
                self.assertFalse(overlap_x > 1e-6 and overlap_y > 1e-6)

    def test_complete_titles_wrap_without_losing_characters(self):
        titles = [
            "这是一个很长但必须让普通人完整读到的中文笔记标题以及第二部分",
            "A mixed 中英标题 with spaces, e\u0301 and an emoji 🌱",
            "", "短标题",
        ]
        nodes = [{"id": str(index), "label": title, "kind": "note", "degree": index}
                 for index, title in enumerate(titles)]
        atlas = star_layout.prepare_star_atlas(nodes, {})
        for node in nodes:
            placed = atlas["nodes"][node["id"]]
            self.assertEqual("".join(placed["label_lines"]), node["label"])
            self.assertLessEqual(placed["label_width"], 14 * atlas["font_size"] + 1e-6)
            self.assertEqual(placed["label_height"], len(placed["label_lines"]) * atlas["line_height"])
        self.assertGreater(len(atlas["nodes"]["0"]["label_lines"]), 1)
        self.assert_clear(atlas)

    def test_coincident_nodes_have_separate_click_and_title_areas(self):
        nodes = [{"id": f"note-{index:02d}", "label": "每个标题都需要自己的阅读空间" + str(index),
                  "kind": "note", "degree": index % 12} for index in range(30)]
        atlas = star_layout.prepare_star_atlas(nodes, {node["id"]: (500, 280) for node in nodes})
        self.assert_clear(atlas)

    def test_emoji_sequences_stay_on_one_line(self):
        for emoji in ("👩‍💻", "👍🏽", "🇨🇳", "👨‍👩‍👧‍👦"):
            title = "中" * 13 + emoji + "工作笔记"
            atlas = star_layout.prepare_star_atlas(
                [{"id": "emoji", "label": title, "kind": "note", "degree": 1}], {},
            )
            lines = atlas["nodes"]["emoji"]["label_lines"]
            self.assertEqual("".join(lines), title)
            self.assertTrue(any(emoji in line for line in lines))

    def test_large_atlas_and_search_fallback_remain_two_dimensional(self):
        rng = random.Random(7)
        nodes = [{"id": f"note-{index:03d}", "label": f"第{index}篇关于学习生活和知识整理的完整笔记标题",
                  "kind": "note", "degree": index % 18} for index in range(500)]
        positions = {node["id"]: (rng.uniform(90, 910), rng.uniform(40, 520)) for node in nodes}
        original_limit = star_layout.MAX_SEARCH_STEPS
        try:
            # Exercise the fallback itself, rather than relying on an incidental
            # collision pattern to exhaust the normal nearby search.
            star_layout.MAX_SEARCH_STEPS = 1
            atlas = star_layout.prepare_star_atlas(nodes, positions)
        finally:
            star_layout.MAX_SEARCH_STEPS = original_limit
        self.assertLess(atlas["width"], 6000)
        self.assertLess(atlas["height"], 4000)
        self.assertLess(atlas["width"] / atlas["height"], 3)
        self.assert_clear(atlas)

    def test_medium_atlas_is_finite_stable_and_reasonably_compact(self):
        rng = random.Random(7)
        nodes = [{"id": f"note-{index:03d}", "label": f"第{index}篇关于学习生活和知识整理的完整笔记标题",
                  "kind": "note", "degree": index % 18} for index in range(99)]
        positions = {node["id"]: (rng.uniform(90, 910), rng.uniform(40, 520)) for node in nodes}
        atlas = star_layout.prepare_star_atlas(nodes, positions)
        self.assertEqual(atlas, star_layout.prepare_star_atlas(list(reversed(nodes)), positions))
        self.assertEqual(len(atlas["nodes"]), 99)
        self.assertLess(atlas["width"], 1600)
        self.assertLess(atlas["height"], 1100)
        for node in atlas["nodes"].values():
            self.assertTrue(all(math.isfinite(node[key]) for key in (
                "x", "y", "label_x", "label_y", "label_width", "label_height", "radius")))
            self.assertGreaterEqual(node["radius"], 4.8)
            self.assertLessEqual(node["radius"], 9.6)
            self.assertEqual(node["hit_radius"], 11)
            self.assertLess(node["radius"] * 1.1 + .35, node["hit_radius"])
        self.assert_clear(atlas)

    def test_empty_and_single_node(self):
        empty = star_layout.prepare_star_atlas([], {})
        self.assertEqual(empty["nodes"], {})
        self.assertGreater(empty["width"], 0)
        self.assertGreater(empty["height"], 0)
        single = star_layout.prepare_star_atlas(
            [{"id": "single", "label": "今天的一点思考", "kind": "note", "degree": 0}],
            {"single": (-40, -20)},
        )
        self.assert_clear(single)


if __name__ == "__main__":
    unittest.main()
