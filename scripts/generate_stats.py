#!/usr/bin/env python3
"""Generate self-hosted GitHub contribution streak and activity SVGs."""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

API_URL = "https://api.github.com/graphql"
BG = "#0D1117"
PANEL = "#161B22"
BORDER = "#30363D"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
PURPLE = "#C77DFF"
PURPLE_DARK = "#3B1D55"


def fetch_contributions(username: str, token: str) -> dict:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                date
                contributionCount
                color
              }
            }
          }
        }
      }
    }
    """
    variables = {
        "login": username,
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{today.isoformat()}T23:59:59Z",
    }
    payload = json.dumps({"query": query, "variables": variables}).encode()
    request = Request(
        API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json",
            "User-Agent": "inkyzx-profile-stats-generator",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"GitHub GraphQL request failed: {exc}") from exc

    if result.get("errors"):
        messages = "; ".join(error.get("message", "Unknown GraphQL error") for error in result["errors"])
        raise RuntimeError(f"GitHub GraphQL returned errors: {messages}")
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{username}' was not found or is not accessible")

    calendar = user["contributionsCollection"]["contributionCalendar"]
    days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    return {"total": calendar["totalContributions"], "days": days}


def calculate_streaks(days: list[dict], today: date) -> tuple[int, int, int]:
    counts = {date.fromisoformat(item["date"]): int(item["contributionCount"]) for item in days}
    active = sorted(day for day, count in counts.items() if count > 0)

    longest = current = run = 0
    previous = None
    for day in sorted(counts):
        if counts[day] > 0:
            run = run + 1 if previous == day - timedelta(days=1) else 1
            longest = max(longest, run)
            previous = day
        else:
            run = 0
            previous = None

    # A streak remains current through today, or through yesterday if today
    # has not had a contribution yet (GitHub's usual streak convention).
    anchor = today if counts.get(today, 0) > 0 else today - timedelta(days=1)
    cursor = anchor
    while counts.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest, len(active)


def svg_document(width: int, height: int, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title>{body}</svg>\n'
    )


def generate_streak_svg(username: str, total: int, current: int, longest: int, active_days: int) -> str:
    width, height = 780, 190
    body = [f'<rect width="{width}" height="{height}" rx="14" fill="{BG}"/>',
            f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="13" fill="none" stroke="{BORDER}"/>',
            f'<text x="28" y="38" fill="{TEXT}" font-size="19" font-family="Segoe UI,Arial,sans-serif" font-weight="700">Contribution streak</text>',
            f'<text x="{width-28}" y="37" text-anchor="end" fill="{MUTED}" font-size="12" font-family="Segoe UI,Arial,sans-serif">@{escape(username)} · last 365 days</text>']
    metrics = [
        (28, "CURRENT STREAK", current, "days"),
        (278, "LONGEST STREAK", longest, "days"),
        (528, "ACTIVE DAYS", active_days, "days"),
    ]
    for x, label, value, suffix in metrics:
        body.extend([
            f'<rect x="{x}" y="60" width="224" height="102" rx="10" fill="{PANEL}"/>',
            f'<text x="{x+18}" y="88" fill="{MUTED}" font-size="10" letter-spacing="1.1" font-family="Segoe UI,Arial,sans-serif">{label}</text>',
            f'<text x="{x+18}" y="137" fill="{PURPLE}" font-size="37" font-weight="700" font-family="Segoe UI,Arial,sans-serif">{value}</text>',
            f'<text x="{x+82}" y="136" fill="{MUTED}" font-size="12" font-family="Segoe UI,Arial,sans-serif">{suffix}</text>',
        ])
    body.append(f'<text x="28" y="180" fill="{MUTED}" font-size="10" font-family="Segoe UI,Arial,sans-serif">{total:,} contributions in the last year</text>')
    return svg_document(width, height, "".join(body), f"{username} contribution streak")


def generate_graph_svg(username: str, days: list[dict], total: int) -> str:
    # Weekly bars preserve the activity-over-time feel of the original graph,
    # while avoiding third-party image services and their uptime limits.
    counts = {date.fromisoformat(item["date"]): int(item["contributionCount"]) for item in days}
    end = max(counts)
    start = end - timedelta(days=363)
    weeks: list[int] = []
    week_total = 0
    cursor = start
    while cursor <= end:
        week_total += counts.get(cursor, 0)
        if cursor.weekday() == 6 or cursor == end:
            weeks.append(week_total)
            week_total = 0
        cursor += timedelta(days=1)

    width, height = 1000, 270
    left, top, plot_w, plot_h = 54, 72, 910, 142
    max_value = max(weeks, default=1) or 1
    gap = 5
    bar_w = max(3, (plot_w - gap * (len(weeks) - 1)) / max(1, len(weeks)))
    body = [f'<rect width="{width}" height="{height}" rx="14" fill="{BG}"/>',
            f'<rect x="1" y="1" width="{width-2}" height="{height-2}" rx="13" fill="none" stroke="{BORDER}"/>',
            f'<text x="28" y="38" fill="{TEXT}" font-size="19" font-weight="700" font-family="Segoe UI,Arial,sans-serif">Contribution activity</text>',
            f'<text x="{width-28}" y="37" text-anchor="end" fill="{MUTED}" font-size="12" font-family="Segoe UI,Arial,sans-serif">@{escape(username)} · {total:,} contributions / year</text>']
    for fraction in (0, .5, 1):
        y = top + plot_h * fraction
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="{BORDER}" stroke-dasharray="3 5"/>')
    for index, value in enumerate(weeks):
        bar_h = max(2, (value / max_value) * plot_h)
        x = left + index * (bar_w + gap)
        y = top + plot_h - bar_h
        opacity = 0.35 + 0.65 * (value / max_value) if value else 0.18
        body.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" rx="2" fill="{PURPLE}" opacity="{opacity:.2f}"/>')
    body.extend([
        f'<text x="{left}" y="238" fill="{MUTED}" font-size="11" font-family="Segoe UI,Arial,sans-serif">{start.strftime("%b %Y")}</text>',
        f'<text x="{left+plot_w}" y="238" text-anchor="end" fill="{MUTED}" font-size="11" font-family="Segoe UI,Arial,sans-serif">{end.strftime("%b %Y")}</text>',
        f'<text x="{left}" y="258" fill="{MUTED}" font-size="10" font-family="Segoe UI,Arial,sans-serif">Weekly contributions · updated automatically by GitHub Actions</text>',
    ])
    return svg_document(width, height, "".join(body), f"{username} weekly contribution activity")


def main() -> None:
    username = os.environ.get("GITHUB_USERNAME", "inkyzx")
    token = os.environ.get("GITHUB_TOKEN")
    output_dir = Path(os.environ.get("OUTPUT_DIR", "dist"))
    if not token:
        raise RuntimeError("GITHUB_TOKEN is missing")

    data = fetch_contributions(username, token)
    today = datetime.now(timezone.utc).date()
    current, longest, active_days = calculate_streaks(data["days"], today)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "contribution-streak.svg").write_text(
        generate_streak_svg(username, data["total"], current, longest, active_days), encoding="utf-8"
    )
    (output_dir / "contribution-graph.svg").write_text(
        generate_graph_svg(username, data["days"], data["total"]), encoding="utf-8"
    )
    print(f"Generated stats for @{username}: {data['total']} contributions, {current}-day current streak, {longest}-day longest streak")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # Fail the workflow clearly; do not publish broken assets.
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
