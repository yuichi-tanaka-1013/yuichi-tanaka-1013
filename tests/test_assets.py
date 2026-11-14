import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_assets as ba  # noqa: E402
from svgcheck import XMLNS, external_references, find_all, local  # noqa: E402

ASSETS = ROOT / "assets"

MIN_CONTRAST = 4.5  # WCAG AA for normal-size text; the badge text is 13px

# The same ten badges, in the same order, as the README had before.
EXPECTED_BADGES = [
    ("AWS", "#232F3E"), ("Terraform", "#844FBA"), ("Go", "#00ADD8"), ("Python", "#3776AB"),
    ("TypeScript", "#3178C6"), ("FastAPI", "#009688"), ("Next.js", "#000000"),
    ("PostgreSQL", "#4169E1"), ("Docker", "#2496ED"), ("OpenTelemetry", "#000000"),
]


class StaticAssetsTest(unittest.TestCase):
    def test_badge_list_keeps_the_original_order_and_colors(self):
        self.assertEqual([(label, fill.upper()) for label, _slug, fill in ba.BADGES],
                         EXPECTED_BADGES)

    def test_committed_files_match_the_generator(self):
        expected = ba.build_all()
        self.assertEqual(len(expected), 12)  # 2 headers + 10 badges
        for rel, svg in expected.items():
            with self.subTest(file=rel):
                path = ASSETS / rel
                self.assertTrue(path.is_file(), f"{path} is missing; run scripts/build_assets.py")
                self.assertEqual(path.read_text(encoding="utf-8"), svg,
                                 f"{rel} is stale; run scripts/build_assets.py")

    def test_no_stray_files_in_assets(self):
        on_disk = {p.relative_to(ASSETS).as_posix() for p in ASSETS.rglob("*") if p.is_file()}
        self.assertEqual(on_disk, set(ba.build_all()))

    def test_well_formed_and_self_contained(self):
        for rel, svg in ba.build_all().items():
            with self.subTest(file=rel):
                self.assertEqual(local(ET.fromstring(svg).tag), "svg")
                self.assertIn(XMLNS, svg)
                self.assertEqual(external_references(svg), [])

    def test_headers_carry_the_text_and_theme_colors(self):
        light = ba.build_all()["header-light.svg"]
        dark = ba.build_all()["header-dark.svg"]
        for svg in (light, dark):
            root = ET.fromstring(svg)
            texts = [t.text for t in find_all(root, "text")]
            self.assertEqual(texts, ["Yuichi Tanaka",
                                     "Product manager · AWS infrastructure",
                                     "Simple designs, clear trade-offs, and things you can measure."])
        self.assertIn("#ffffff", light)
        self.assertIn("#1f2328", light)
        self.assertIn("#0d1117", dark)
        self.assertIn("#e6edf3", dark)
        self.assertNotIn("#0d1117", light)

    def test_badge_text_stays_inside_its_box(self):
        for label, slug, fill in ba.BADGES:
            with self.subTest(badge=label):
                root = ET.fromstring(ba.build_all()[f"badges/{slug}.svg"])
                width = float(root.get("width"))
                text = find_all(root, "text")[0]
                self.assertEqual(text.text, label)
                # textLength pins the text to its width whatever font the viewer has.
                self.assertEqual(text.get("lengthAdjust"), "spacingAndGlyphs")
                self.assertLessEqual(float(text.get("textLength")) + 2 * ba.BADGE_PAD, width + 1)
                rect = find_all(root, "rect")[0]
                self.assertEqual(rect.get("fill").upper(), fill.upper())

    def test_contrast_ratio_matches_known_values(self):
        self.assertAlmostEqual(ba.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(ba.contrast_ratio("#ffffff", "#ffffff"), 1.0, places=2)
        # The two grays on either side of the 4.5:1 line, and the old white-on-Go badge.
        self.assertAlmostEqual(ba.contrast_ratio("#767676", "#ffffff"), 4.54, places=2)
        self.assertAlmostEqual(ba.contrast_ratio("#777777", "#ffffff"), 4.48, places=2)
        self.assertAlmostEqual(ba.contrast_ratio("#00ADD8", "#ffffff"), 2.64, places=2)

    def test_every_badge_text_is_readable_against_its_fill(self):
        for label, slug, _fill in ba.BADGES:
            root = ET.fromstring((ASSETS / "badges" / f"{slug}.svg").read_text(encoding="utf-8"))
            fill = find_all(root, "rect")[0].get("fill")
            color = find_all(root, "text")[0].get("fill")
            other = ba.TEXT_DARK if color == ba.TEXT_LIGHT else ba.TEXT_LIGHT
            ratio = ba.contrast_ratio(fill, color)
            with self.subTest(badge=label, fill=fill, text=color, ratio=round(ratio, 2)):
                self.assertIn(color, (ba.TEXT_LIGHT, ba.TEXT_DARK))
                self.assertGreaterEqual(ratio, MIN_CONTRAST)
                # It is the better of the two, not just a pass.
                self.assertGreaterEqual(ratio, ba.contrast_ratio(fill, other))

    def test_every_badge_has_a_ring_that_shows_on_a_dark_page(self):
        for label, slug, _fill in ba.BADGES:
            root = ET.fromstring(ba.build_all()[f"badges/{slug}.svg"])
            rect = find_all(root, "rect")[0]
            with self.subTest(badge=label):
                self.assertEqual(rect.get("stroke"), "#8b949e")


if __name__ == "__main__":
    unittest.main()
