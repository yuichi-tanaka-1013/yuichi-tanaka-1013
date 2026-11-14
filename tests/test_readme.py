import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from svgcheck import HTTP, XMLNS  # noqa: E402

README = ROOT / "README.md"
RAW = "https://raw.githubusercontent.com/yuichi-tanaka-1013/yuichi-tanaka-1013"
CARDS = {"stats-light.svg", "stats-dark.svg", "grass-light.svg", "grass-dark.svg"}
ALLOWED_HOSTS = re.compile(
    r"^(github\.com|raw\.githubusercontent\.com|api\.github\.com|users\.noreply\.github\.com"
    r"|[\w-]+\.github\.io)$"
)
URL = re.compile(HTTP + r"s?://([^/\s\"'<>)\]]+)[^\s\"'<>)\]]*")
AWS_CATEGORIES = [
    "Compute", "Containers", "Data", "Networking & Edge", "Security & Identity",
    "Observability", "Delivery / CI-CD", "Messaging & Integration", "IaC",
]
TABLE_ROW = re.compile(r"^\|([^|\n]+)\|([^|\n]+)\|$", re.MULTILINE)
# Text that would publish an AWS account ID, an ARN, an AWS endpoint or an IPv4 address.
IDENTIFIERS = [
    re.compile(r"(?<!\d)\d{12}(?!\d)"),
    re.compile(r"\barn:"),
    re.compile(r"amazonaws"),
    re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
]


def repo_text_files():
    names = ["README.md"]
    for folder in ("assets", ".github", "scripts", "tests"):
        names += [
            p.relative_to(ROOT).as_posix()
            for p in sorted((ROOT / folder).rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        ]
    return names


class ReadmeTest(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_no_external_badge_service(self):
        self.assertNotIn("shields.io", self.text)

    def test_every_image_is_an_absolute_raw_url_with_alt_text(self):
        markdown = re.findall(r"!\[([^\]]*)\]\(([^)\s]+)\)", self.text)
        html = [
            (re.search(r'alt="([^"]*)"', tag), re.search(r'src="([^"]*)"', tag))
            for tag in re.findall(r"<img\b[^>]*>", self.text)
        ]
        images = markdown + [(a.group(1) if a else "", s.group(1) if s else "") for a, s in html]
        self.assertGreaterEqual(len(images), 12)  # header, 10 badges, 2 cards
        for alt, src in images:
            with self.subTest(src=src):
                self.assertTrue(alt.strip(), "alt text is empty")
                self.assertRegex(src, "^" + re.escape(RAW) + r"/(main/assets|output)/")

    def test_dark_variants_come_from_picture_sources(self):
        sources = re.findall(r'<source media="\(prefers-color-scheme: dark\)" srcset="([^"]+)"', self.text)
        self.assertEqual(len(sources), 3)  # header, stats, grass
        self.assertTrue(all("-dark.svg" in s for s in sources))

    def test_static_images_exist_in_the_repo(self):
        for rel in re.findall(re.escape(RAW) + r"/main/(assets/[\w./-]+\.svg)", self.text):
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).is_file())

    def test_card_images_are_the_four_files_on_the_output_branch(self):
        names = set(re.findall(re.escape(RAW) + r"/output/([\w.-]+)", self.text))
        self.assertEqual(names, CARDS)

    def test_tech_badges_keep_their_order(self):
        order = re.findall(r"!\[([^\]]+)\]\(", self.text)
        self.assertEqual(order, ["AWS", "Terraform", "Go", "Python", "TypeScript", "FastAPI",
                                 "Next.js", "PostgreSQL", "Docker", "OpenTelemetry"])

    def test_mermaid_diagram_is_outside_details(self):
        start = self.text.index("```mermaid")
        self.assertEqual(self.text[:start].count("<details>"), self.text[:start].count("</details>"))

    def test_no_account_or_network_identifiers(self):
        for pattern in IDENTIFIERS:
            with self.subTest(pattern=pattern.pattern):
                self.assertIsNone(pattern.search(self.text))


class AwsSectionTest(unittest.TestCase):
    def setUp(self):
        self.text = README.read_text(encoding="utf-8")

    def test_section_is_after_the_diagram_and_before_tech(self):
        diagram_end = self.text.index("\n```\n", self.text.index("```mermaid"))
        aws = self.text.index("\n## AWS\n")
        self.assertLess(diagram_end, aws)
        self.assertLess(aws, self.text.index("\n## Tech\n"))

    def test_table_has_the_nine_categories_in_order(self):
        start = self.text.index("\n## AWS\n")
        section = self.text[start : self.text.index("\n## Tech\n", start)]
        rows = [(a.strip(), b.strip()) for a, b in TABLE_ROW.findall(section)]
        self.assertEqual(rows[0], ("Category", "Services"))
        self.assertEqual([name for name, _ in rows[2:]], AWS_CATEGORIES)  # rows[1] is the separator


class ExternalHostsTest(unittest.TestCase):
    """The rule of the whole project: nothing is loaded from outside GitHub."""

    def test_only_github_hosts_and_the_svg_namespace_appear(self):
        for name in repo_text_files():
            text = (ROOT / name).read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                for host in URL.findall(line.replace(XMLNS, "")):
                    with self.subTest(file=name, line=lineno):
                        self.assertRegex(host, ALLOWED_HOSTS)


if __name__ == "__main__":
    unittest.main()
