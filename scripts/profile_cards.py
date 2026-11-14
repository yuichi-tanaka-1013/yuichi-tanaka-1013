#!/usr/bin/env python3
"""Draw the profile cards (stats and grass) as self-contained SVG files.

Reads the contribution calendar from GitHub and writes four files:
stats-light.svg, stats-dark.svg, grass-light.svg and grass-dark.svg.

Input, pick one:
  --input FILE   JSON written by `gh api graphql` (local use).
  GITHUB_TOKEN   environment variable; the script asks api.github.com itself
                 (GitHub Actions).

Only counts and calendar dates are read. The query never asks for repository
or language fields, so nothing about private work can reach the output.

Standard library only. Runs on Python 3.10 or later.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API_URL = "https://api.github.com/graphql"
DEFAULT_LOGIN = "yuichi-tanaka-1013"

# The only fields this script ever asks for. tests/ checks the field list.
QUERY = """\
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            weekday
            contributionCount
            contributionLevel
          }
        }
      }
    }
  }
}
"""

LEVELS = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # GitHub: 0 = Sunday

FONT_STACK = '-apple-system,"Segoe UI",Helvetica,Arial,sans-serif'


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    border: str
    text: str
    muted: str
    levels: tuple[str, str, str, str, str]


THEMES = {
    "light": Theme(
        name="light",
        bg="#ffffff",
        border="#d1d9e0",
        text="#1f2328",
        muted="#59636e",
        levels=("#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"),
    ),
    "dark": Theme(
        name="dark",
        bg="#0d1117",
        border="#30363d",
        text="#e6edf3",
        muted="#9198a1",
        levels=("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"),
    ),
}


class CardError(Exception):
    """Raised when the calendar cannot be read or fetched."""


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Day:
    date: datetime.date
    weekday: int  # 0 = Sunday ... 6 = Saturday
    count: int
    level: int  # 0 .. 4


@dataclass(frozen=True)
class Calendar:
    total: int  # totalContributions as reported by GitHub
    weeks: tuple[tuple[Day, ...], ...]

    @property
    def days(self) -> list[Day]:
        return [day for week in self.weeks for day in week]


def parse_calendar(payload: object) -> Calendar:
    """Turn a GraphQL response (the `gh api graphql` output) into a Calendar."""
    if not isinstance(payload, dict):
        raise CardError("the input is not a JSON object")
    errors = payload.get("errors")
    if errors:
        messages = "; ".join(
            str(e.get("message", "unknown error")) if isinstance(e, dict) else str(e)
            for e in errors
        )
        raise CardError(f"GraphQL returned errors: {messages}")
    try:
        raw = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        total = int(raw["totalContributions"])
        weeks = []
        for raw_week in raw["weeks"]:
            days = tuple(
                Day(
                    date=datetime.date.fromisoformat(item["date"]),
                    weekday=int(item["weekday"]),
                    count=int(item["contributionCount"]),
                    level=LEVELS[item["contributionLevel"]],
                )
                for item in raw_week["contributionDays"]
            )
            weeks.append(days)
    except (KeyError, TypeError, ValueError) as exc:
        raise CardError(f"unexpected GraphQL response: {exc!r}") from exc
    if not weeks or not any(weeks):
        raise CardError("the calendar has no days")
    for day in (d for week in weeks for d in week):
        if not 0 <= day.weekday <= 6 or day.count < 0:
            raise CardError(f"invalid day in the calendar: {day.date}")
    return Calendar(total=total, weeks=tuple(weeks))


def sum_of_days(cal: Calendar) -> int:
    return sum(day.count for day in cal.days)


def monthly_totals(cal: Calendar) -> list[tuple[str, int]]:
    """Counts per calendar month, oldest first, as ('YYYY-MM', count)."""
    totals: dict[str, int] = {}
    for day in cal.days:
        key = f"{day.date.year:04d}-{day.date.month:02d}"
        totals[key] = totals.get(key, 0) + day.count
    return sorted(totals.items())


def weekday_totals(cal: Calendar) -> list[int]:
    """Counts per weekday, Sunday first."""
    totals = [0] * 7
    for day in cal.days:
        totals[day.weekday] += day.count
    return totals


def weekday_level(value: int, lowest: int, highest: int) -> int:
    """Shade 0..4 for a weekday total.

    0 is only for an empty weekday. The quietest busy weekday gets 1 and the
    busiest gets 4, so the shades show the rhythm even when the totals are close.
    """
    if value <= 0:
        return 0
    if highest <= lowest:
        return 4
    return 1 + min(3, int(4 * (value - lowest) / (highest - lowest)))


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


def load_payload(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CardError(f"cannot read {path}: {exc}") from exc


def fetch_payload(token: str, login: str = DEFAULT_LOGIN, *,
                  attempts: int = 3, timeout: float = 30.0) -> object:
    """Ask api.github.com for the contribution calendar. Retries on 5xx and network errors."""
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "profile-cards",
        },
    )
    last_error = "unknown error"
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raise CardError(f"GitHub API returned HTTP {exc.code}") from exc
            last_error = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
        except ValueError as exc:
            raise CardError(f"GitHub API returned invalid JSON: {exc}") from exc
        if attempt < attempts:
            time.sleep(2 ** attempt)
    raise CardError(f"GitHub API request failed after {attempts} attempts: {last_error}")


# --------------------------------------------------------------------------
# SVG helpers
# --------------------------------------------------------------------------


def _esc(text: object) -> str:
    return html.escape(str(text), quote=True)


def _base_css(theme: Theme) -> str:
    rules = [
        f"text{{font-family:{FONT_STACK}}}",
        f".bg{{fill:{theme.bg};stroke:{theme.border}}}",
        f".t{{fill:{theme.text}}}",
        f".m{{fill:{theme.muted}}}",
        f".axis{{stroke:{theme.border}}}",
    ]
    rules += [f".l{i}{{fill:{color}}}" for i, color in enumerate(theme.levels)]
    return "\n".join(rules)


def _svg(width: int, height: int, title: str, css: str, body: list[str]) -> str:
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">\n'
        f'<title id="title">{_esc(title)}</title>\n'
        f"<style>\n{css}\n</style>\n"
        f'<rect class="bg" x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="12"/>'
    )
    return head + "\n" + "\n".join(body) + "\n</svg>\n"


def _text(x: float, y: float, content: object, *, cls: str, size: int,
          weight: int = 400, anchor: str = "start") -> str:
    return (
        f'<text class="{cls}" x="{x:g}" y="{y:g}" font-size="{size}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{_esc(content)}</text>'
    )


# --------------------------------------------------------------------------
# Stats card
# --------------------------------------------------------------------------

CARD_WIDTH = 848
STATS_HEIGHT = 252


def render_stats(cal: Calendar, theme: Theme) -> str:
    months = monthly_totals(cal)
    weekdays = weekday_totals(cal)
    days = sorted(cal.days, key=lambda d: d.date)
    first, last = days[0].date, days[-1].date
    span = f"{MONTHS[first.month - 1]} {first.year} to {MONTHS[last.month - 1]} {last.year}"

    body: list[str] = []

    # Left panel: total and weekday shades.
    body.append(_text(28, 38, "Contributions in the last year", cls="m", size=14, weight=600))
    body.append(_text(28, 92, f"{cal.total:,}", cls="t", size=48, weight=700))
    body.append(_text(28, 116, span, cls="m", size=13))
    body.append(_text(28, 150, "By weekday", cls="m", size=12, weight=600))

    lowest, highest = min(weekdays), max(weekdays)
    cell_w, cell_gap = 38, 6
    for i, value in enumerate(weekdays):
        x = 28 + i * (cell_w + cell_gap)
        mid = x + cell_w / 2
        body.append(_text(mid, 170, WEEKDAYS[i], cls="m", size=11, anchor="middle"))
        body.append(
            f'<rect class="l{weekday_level(value, lowest, highest)}" x="{x}" y="177" '
            f'width="{cell_w}" height="28" rx="4"/>'
        )
        body.append(_text(mid, 222, f"{value:,}", cls="t", size=11, anchor="middle"))

    # Right panel: one bar per month.
    left, right = 388, CARD_WIDTH - 28
    base, top = 205, 92
    body.append(_text(left, 38, "By month", cls="m", size=14, weight=600))
    body.append(
        f'<line class="axis" x1="{left}" y1="{base + 0.5}" x2="{right}" y2="{base + 0.5}" '
        'stroke-width="1"/>'
    )
    slot = (right - left) / len(months)
    bar_w = round(slot * 0.62, 1)
    most = max(count for _, count in months)
    for i, (key, count) in enumerate(months):
        year, month = int(key[:4]), int(key[5:])
        mid = left + slot * (i + 0.5)
        height = 0 if most == 0 or count == 0 else max(2, round((base - top) * count / most))
        if height:
            body.append(
                f'<rect class="l3" x="{mid - bar_w / 2:.1f}" y="{base - height}" '
                f'width="{bar_w:g}" height="{height}" rx="3"/>'
            )
        body.append(_text(mid, base - height - 6, f"{count:,}", cls="t", size=10, anchor="middle"))
        body.append(_text(mid, 222, MONTHS[month - 1], cls="m", size=11, anchor="middle"))
        if i == 0 or month == 1:
            body.append(_text(mid, 237, year, cls="m", size=10, anchor="middle"))

    title = (
        f"{cal.total:,} contributions in the last year, "
        "with totals by month and by weekday"
    )
    return _svg(CARD_WIDTH, STATS_HEIGHT, title, _base_css(theme), body)


# --------------------------------------------------------------------------
# Grass animation
# --------------------------------------------------------------------------

CELL, GAP = 12, 3
PITCH = CELL + GAP
GRASS_LEFT, GRASS_RIGHT = 40, 16
GRASS_TOP = 30
GRASS_HEIGHT = 168
COLUMN_DELAY_MS = 45
GROW_MS = 600


def _month_label_columns(cal: Calendar) -> list[tuple[int, int]]:
    """(column, month) pairs where a new month starts, without crowded labels."""
    candidates: list[tuple[int, int]] = []
    previous = None
    for col, week in enumerate(cal.weeks):
        if not week:
            continue
        month = min(week, key=lambda d: d.date).date.month
        if month != previous:
            candidates.append((col, month))
            previous = month
    kept = []
    for i, (col, month) in enumerate(candidates):
        # Drop a label that would collide with the next one (less than 3 columns away).
        if i + 1 < len(candidates) and candidates[i + 1][0] - col < 3:
            continue
        kept.append((col, month))
    return kept


def render_grass(cal: Calendar, theme: Theme) -> str:
    n_weeks = len(cal.weeks)
    width = GRASS_LEFT + n_weeks * PITCH - GAP + GRASS_RIGHT

    css = _base_css(theme) + "\n".join([
        "",
        f".w{{animation:grow {GROW_MS}ms cubic-bezier(.2,.7,.3,1) both}}",
        "@keyframes grow{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}",
        "@media (prefers-reduced-motion: reduce){.w{animation:none}}",
    ])

    body: list[str] = []
    for col, month in _month_label_columns(cal):
        body.append(_text(GRASS_LEFT + col * PITCH, 20, MONTHS[month - 1], cls="m", size=11))
    for row in (1, 3, 5):
        body.append(
            _text(GRASS_LEFT - 8, GRASS_TOP + row * PITCH + 10, WEEKDAYS[row],
                  cls="m", size=10, anchor="end")
        )

    for col, week in enumerate(cal.weeks):
        cells = [
            f'<rect class="l{day.level}" x="{GRASS_LEFT + col * PITCH}" '
            f'y="{GRASS_TOP + day.weekday * PITCH}" width="{CELL}" height="{CELL}" rx="2"/>'
            for day in week
        ]
        body.append(f'<g class="w" style="animation-delay:{col * COLUMN_DELAY_MS}ms">')
        body.extend(cells)
        body.append("</g>")

    legend_y = GRASS_TOP + 7 * PITCH + 18
    right_edge = width - GRASS_RIGHT
    body.append(_text(right_edge, legend_y + 10, "More", cls="m", size=10, anchor="end"))
    squares_end = right_edge - 32
    squares_start = squares_end - (5 * PITCH - GAP)
    for level in range(5):
        body.append(
            f'<rect class="l{level}" x="{squares_start + level * PITCH}" y="{legend_y}" '
            f'width="{CELL}" height="{CELL}" rx="2"/>'
        )
    body.append(_text(squares_start - 6, legend_y + 10, "Less", cls="m", size=10, anchor="end"))

    title = f"Daily contributions over the last year, drawn as {n_weeks} weeks of grass"
    return _svg(width, GRASS_HEIGHT, title, css, body)


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def write_cards(cal: Calendar, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for theme in THEMES.values():
        for kind, render in (("stats", render_stats), ("grass", render_grass)):
            path = out_dir / f"{kind}-{theme.name}.svg"
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(render(cal, theme))
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draw the profile cards as SVG files.")
    parser.add_argument("--input", type=Path, metavar="FILE",
                        help="JSON written by `gh api graphql`; without it GITHUB_TOKEN is used")
    parser.add_argument("--out-dir", type=Path, metavar="DIR",
                        help="directory for the four SVG files")
    parser.add_argument("--login", default=DEFAULT_LOGIN,
                        help=f"GitHub login to read (default: {DEFAULT_LOGIN})")
    parser.add_argument("--print-query", action="store_true",
                        help="print the GraphQL query and exit, for `gh api graphql -f query=...`")
    args = parser.parse_args(argv)

    if args.print_query:
        sys.stdout.write(QUERY)
        return 0
    if args.out_dir is None:
        parser.error("--out-dir is required")

    try:
        if args.input is not None:
            payload = load_payload(args.input)
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise CardError("set GITHUB_TOKEN or pass --input FILE")
            payload = fetch_payload(token, args.login)
        cal = parse_calendar(payload)
    except CardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if sum_of_days(cal) != cal.total:
        print(
            f"warning: totalContributions is {cal.total} but the days add up to "
            f"{sum_of_days(cal)}",
            file=sys.stderr,
        )
    for path in write_cards(cal, args.out_dir):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
