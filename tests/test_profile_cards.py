import contextlib
import dataclasses
import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import profile_cards as pc  # noqa: E402
from svgcheck import HTTP, XMLNS, external_references, find_all, local  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "small_calendar.json"


def fixture_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fixture_calendar():
    return pc.parse_calendar(fixture_payload())


class AggregationTest(unittest.TestCase):
    """The fixture: 5 weeks, 32 days, 2026-01-25 (Sun) to 2026-02-25 (Wed)."""

    def setUp(self):
        self.cal = fixture_calendar()

    def test_year_total(self):
        self.assertEqual(self.cal.total, 52)
        self.assertEqual(pc.sum_of_days(self.cal), 52)
        self.assertEqual(len(self.cal.days), 32)

    def test_monthly_totals(self):
        self.assertEqual(pc.monthly_totals(self.cal), [("2026-01", 10), ("2026-02", 42)])

    def test_weekday_totals_start_on_sunday(self):
        self.assertEqual(pc.weekday_totals(self.cal), [3, 5, 11, 15, 9, 7, 2])

    def test_weekday_levels(self):
        totals = pc.weekday_totals(self.cal)
        low, high = min(totals), max(totals)
        levels = [pc.weekday_level(v, low, high) for v in totals]
        self.assertEqual(levels, [1, 1, 3, 4, 3, 2, 1])

    def test_weekday_level_edges(self):
        self.assertEqual(pc.weekday_level(0, 0, 10), 0)
        self.assertEqual(pc.weekday_level(5, 5, 5), 4)  # every weekday is equal

    def test_contribution_level_maps_to_five_steps(self):
        by_date = {d.date.isoformat(): d for d in self.cal.days}
        self.assertEqual(by_date["2026-01-25"].level, 0)  # NONE
        self.assertEqual(by_date["2026-02-22"].level, 1)  # FIRST_QUARTILE
        self.assertEqual(by_date["2026-01-26"].level, 2)  # SECOND_QUARTILE
        self.assertEqual(by_date["2026-01-28"].level, 3)  # THIRD_QUARTILE
        self.assertEqual(by_date["2026-02-25"].level, 4)  # FOURTH_QUARTILE


class ParseTest(unittest.TestCase):
    def test_graphql_errors_are_reported(self):
        with self.assertRaises(pc.CardError):
            pc.parse_calendar({"errors": [{"message": "Bad credentials"}]})

    def test_missing_user_is_reported(self):
        with self.assertRaises(pc.CardError):
            pc.parse_calendar({"data": {"user": None}})

    def test_unknown_level_is_reported(self):
        payload = fixture_payload()
        day = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"][
            "weeks"][0]["contributionDays"][0]
        day["contributionLevel"] = "FIFTH_QUARTILE"
        with self.assertRaises(pc.CardError):
            pc.parse_calendar(payload)

    def test_not_an_object_is_reported(self):
        with self.assertRaises(pc.CardError):
            pc.parse_calendar([])

    def test_query_asks_only_for_calendar_counts(self):
        words = set(re.findall(r"[A-Za-z_]+", pc.QUERY))
        self.assertEqual(
            words,
            {"query", "login", "String", "user", "contributionsCollection",
             "contributionCalendar", "totalContributions", "weeks", "contributionDays",
             "date", "weekday", "contributionCount", "contributionLevel"},
        )
        for forbidden in ("repositor", "language", "commit", "issue", "pullRequest"):
            self.assertNotIn(forbidden, pc.QUERY.lower())


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.cal = fixture_calendar()

    def all_svgs(self):
        for theme in pc.THEMES.values():
            yield "stats", theme, pc.render_stats(self.cal, theme)
            yield "grass", theme, pc.render_grass(self.cal, theme)

    def test_every_svg_is_well_formed_xml(self):
        for kind, theme, svg in self.all_svgs():
            with self.subTest(kind=kind, theme=theme.name):
                root = ET.fromstring(svg)
                self.assertEqual(local(root.tag), "svg")
                self.assertIn(XMLNS, svg)

    def test_theme_changes_the_colors(self):
        light, dark = pc.THEMES["light"], pc.THEMES["dark"]
        for kind, render in (("stats", pc.render_stats), ("grass", pc.render_grass)):
            svg_light = render(self.cal, light)
            svg_dark = render(self.cal, dark)
            with self.subTest(kind=kind):
                self.assertNotEqual(svg_light, svg_dark)
                for color in ("#ffffff", "#1f2328", *light.levels):
                    self.assertIn(color, svg_light)
                for color in ("#0d1117", "#e6edf3", *dark.levels):
                    self.assertIn(color, svg_dark)
                self.assertNotIn("#0d1117", svg_light)
                self.assertNotIn("#ffffff", svg_dark)

    def test_palette_matches_the_spec(self):
        self.assertEqual(pc.THEMES["light"].levels,
                         ("#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"))
        self.assertEqual(pc.THEMES["dark"].levels,
                         ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"))

    def test_no_external_references(self):
        for kind, theme, svg in self.all_svgs():
            with self.subTest(kind=kind, theme=theme.name):
                self.assertEqual(external_references(svg), [])

    def test_the_reference_check_catches_violations(self):
        bad = {
            HTTP: f"<svg><a>{HTTP}s://example.com</a></svg>",
            "href": '<svg><a href="#x"/></svg>',
            "xlink": '<svg><use xlink:foo="#x"/></svg>',
            "@import": "<svg><style>@import 'a.css';</style></svg>",
            "@font-face": "<svg><style>@font-face{font-family:x}</style></svg>",
            "script": "<svg><script>1</script></svg>",
            "url() that is not #id": '<svg><rect fill="url(a.png)"/></svg>',
        }
        for label, svg in bad.items():
            with self.subTest(label=label):
                self.assertIn(label, external_references(svg))
        self.assertEqual(external_references(f"<svg {XMLNS}><rect fill=\"url(#g)\"/></svg>"), [])

    def test_fonts_are_system_fonts_only(self):
        for _kind, _theme, svg in self.all_svgs():
            self.assertIn('-apple-system,"Segoe UI",Helvetica,Arial,sans-serif', svg)

    def test_stats_shows_total_months_and_weekdays(self):
        svg = pc.render_stats(dataclasses.replace(self.cal, total=4748), pc.THEMES["light"])
        root = ET.fromstring(svg)
        texts = [t.text for t in find_all(root, "text")]
        self.assertIn("4,748", texts)  # thousands separator
        self.assertIn("Jan", texts)
        self.assertIn("Feb", texts)
        for name in pc.WEEKDAYS:
            self.assertIn(name, texts)
        for count in ("10", "42", "3", "5", "11", "15", "9", "7", "2"):
            self.assertIn(count, texts)
        self.assertIn("Jan 2026 to Feb 2026", texts)

    def test_stats_has_one_bar_per_month_and_one_cell_per_weekday(self):
        root = ET.fromstring(pc.render_stats(self.cal, pc.THEMES["light"]))
        rects = [r for r in find_all(root, "rect") if r.get("class", "").startswith("l")]
        bars = [r for r in rects if r.get("class") == "l3" and r.get("rx") == "3"]
        self.assertEqual(len(bars), 2)
        self.assertEqual(len(rects) - len(bars), 7)

    def test_grass_has_one_cell_per_day_in_one_group_per_week(self):
        root = ET.fromstring(pc.render_grass(self.cal, pc.THEMES["light"]))
        groups = [g for g in find_all(root, "g") if g.get("class") == "w"]
        self.assertEqual(len(groups), 5)
        self.assertEqual([len(g) for g in groups], [7, 7, 7, 7, 4])

    def test_grass_cells_sit_on_the_weekday_row_and_week_column(self):
        root = ET.fromstring(pc.render_grass(self.cal, pc.THEMES["light"]))
        groups = [g for g in find_all(root, "g") if g.get("class") == "w"]
        first_week_x = {r.get("x") for r in groups[0]}
        self.assertEqual(len(first_week_x), 1)
        ys = [int(r.get("y")) for r in groups[0]]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(ys[1] - ys[0], pc.PITCH)

    def test_grass_grows_week_by_week_from_the_left(self):
        svg = pc.render_grass(self.cal, pc.THEMES["light"])
        delays = [int(m) for m in re.findall(r"animation-delay:(\d+)ms", svg)]
        self.assertEqual(delays, [i * pc.COLUMN_DELAY_MS for i in range(5)])
        self.assertRegex(svg, r"@keyframes grow\{from\{opacity:0;")
        # Plays once and holds the last frame.
        self.assertRegex(svg, r"\.w\{animation:grow [^}]*\bboth\}")
        self.assertNotIn("infinite", svg)

    def test_grass_has_a_reduced_motion_branch(self):
        svg = pc.render_grass(self.cal, pc.THEMES["light"])
        self.assertIn("@media (prefers-reduced-motion: reduce){.w{animation:none}}", svg)

    def test_grass_uses_all_five_levels(self):
        svg = pc.render_grass(self.cal, pc.THEMES["dark"])
        for level in range(5):
            self.assertIn(f'class="l{level}"', svg)

    def test_rendering_is_deterministic(self):
        for kind, theme, svg in self.all_svgs():
            render = pc.render_stats if kind == "stats" else pc.render_grass
            with self.subTest(kind=kind, theme=theme.name):
                self.assertEqual(svg, render(fixture_calendar(), theme))


class FakeResponse(io.BytesIO):
    """What urllib.request.urlopen returns: a readable context manager."""


def response_for(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def error_response(code, reason):
    return urllib.error.HTTPError(pc.API_URL, code, reason, {}, io.BytesIO(b""))


class CommandLineTest(unittest.TestCase):
    EXPECTED = {"stats-light.svg", "stats-dark.svg", "grass-light.svg", "grass-dark.svg"}

    def run_main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=True):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = pc.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_file_input_writes_four_svgs(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, _err = self.run_main(["--input", str(FIXTURE), "--out-dir", tmp])
            self.assertEqual(code, 0)
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, self.EXPECTED)
            for path in Path(tmp).iterdir():
                ET.parse(path)

    def test_missing_token_and_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self.run_main(["--out-dir", tmp])
        self.assertEqual(code, 1)
        self.assertIn("GITHUB_TOKEN", err)

    def test_out_dir_is_required(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_main(["--input", str(FIXTURE)])
        self.assertEqual(raised.exception.code, 2)

    def test_print_query(self):
        code, out, _err = self.run_main(["--print-query"])
        self.assertEqual(code, 0)
        self.assertEqual(out, pc.QUERY)

    def test_unreadable_input_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _out, err = self.run_main(["--input", str(Path(tmp) / "none.json"), "--out-dir", tmp])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)

    def test_token_input_asks_the_github_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("urllib.request.urlopen",
                            return_value=response_for(fixture_payload())) as urlopen:
                code, _out, _err = self.run_main(["--out-dir", tmp], env={"GITHUB_TOKEN": "t0ken"})
            self.assertEqual(code, 0)
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, self.EXPECTED)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/graphql")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer t0ken")
        body = json.loads(request.data)
        self.assertEqual(body["query"], pc.QUERY)
        self.assertEqual(body["variables"], {"login": "yuichi-tanaka-1013"})

    def test_fetch_retries_on_server_errors(self):
        server_error = error_response(502, "Bad Gateway")
        self.addCleanup(server_error.close)
        with mock.patch("urllib.request.urlopen",
                        side_effect=[server_error, response_for(fixture_payload())]) as urlopen:
            with mock.patch("time.sleep") as sleep:
                payload = pc.fetch_payload("t0ken")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(pc.parse_calendar(payload).total, 52)

    def test_fetch_gives_up_on_client_errors(self):
        unauthorized = error_response(401, "Unauthorized")
        self.addCleanup(unauthorized.close)
        with mock.patch("urllib.request.urlopen", side_effect=unauthorized) as urlopen:
            with self.assertRaises(pc.CardError):
                pc.fetch_payload("bad")
        self.assertEqual(urlopen.call_count, 1)

    def test_fetch_gives_up_after_three_attempts(self):
        down = urllib.error.URLError("unreachable")
        with mock.patch("urllib.request.urlopen", side_effect=down) as urlopen:
            with mock.patch("time.sleep"):
                with self.assertRaises(pc.CardError):
                    pc.fetch_payload("t0ken")
        self.assertEqual(urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
