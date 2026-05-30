#!/usr/bin/env python3
import datetime as dt
import json
import math
import os
import pathlib
import random
import re
import urllib.error
import urllib.request
from typing import Any

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def fetch_contribution_calendar(login: str, token: str) -> dict[str, Any]:
    payload = json.dumps({"query": QUERY, "variables": {"login": login}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "pacman-contrib-generator",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)

    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    user = data.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{login}' not found or not accessible.")

    return user["contributionsCollection"]["contributionCalendar"]


def level_for_count(count: int, max_count: int) -> int:
    if count <= 0:
        return 0
    if max_count <= 1:
        return 4
    ratio = count / max_count
    if ratio < 0.25:
        return 1
    if ratio < 0.5:
        return 2
    if ratio < 0.75:
        return 3
    return 4


def build_mock_calendar(login: str) -> dict[str, Any]:
    rng = random.Random(login)
    start = dt.date.today() - dt.timedelta(days=370)
    start = start - dt.timedelta(days=(start.weekday() + 1) % 7)

    weeks = []
    total = 0
    for week_idx in range(53):
        days = []
        for day_idx in range(7):
            date = start + dt.timedelta(days=(week_idx * 7 + day_idx))
            band = 0.12 + (week_idx / 70.0)
            active = rng.random() < min(0.62, band)
            count = rng.randint(1, 10) if active else 0
            total += count
            days.append({"date": date.isoformat(), "contributionCount": count})
        weeks.append({"contributionDays": days})

    return {"totalContributions": total, "weeks": weeks}


def detect_owner_from_git_remote() -> str:
    config_path = pathlib.Path(".git/config")
    if not config_path.exists():
        return ""

    content = config_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"url\s*=\s*(.+)", content)
    if not match:
        return ""

    url = match.group(1).strip()
    https_match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", url)
    if https_match:
        return https_match.group(1)
    return ""


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def trim_targets(cells: list[dict[str, Any]], max_targets: int) -> list[dict[str, Any]]:
    if len(cells) <= max_targets:
        return cells
    step = len(cells) / max_targets
    return [cells[int(i * step)] for i in range(max_targets)]


def render_svg(login: str, calendar: dict[str, Any], out_path: pathlib.Path) -> None:
    weeks = calendar.get("weeks", [])
    total = int(calendar.get("totalContributions", 0))

    cell = 11
    gap = 4
    grid_x = 118
    grid_y = 118
    grid_w = max(len(weeks), 52) * (cell + gap)
    grid_h = 7 * (cell + gap)

    width = grid_x + grid_w + 46
    height = grid_y + grid_h + 106
    panel_bg = "#091324"
    palette = ["#17243d", "#264c7d", "#3177b8", "#59a7e8", "#8fd1ff"]

    cells: list[dict[str, Any]] = []
    active_cells: list[dict[str, Any]] = []
    max_count = 0

    for wi, week in enumerate(weeks):
        days = week.get("contributionDays", [])
        for di, day in enumerate(days):
            count = int(day.get("contributionCount", 0))
            max_count = max(max_count, count)
            x = grid_x + wi * (cell + gap)
            y = grid_y + di * (cell + gap)
            item = {
                "x": x,
                "y": y,
                "count": count,
                "date": str(day.get("date", "")),
            }
            cells.append(item)
            if count > 0:
                active_cells.append(item)

    if not active_cells:
        active_cells = cells[:1]

    # Build a horizontal snake path over rows to keep movement Pac-Man-like.
    rows: dict[int, list[dict[str, Any]]] = {}
    for item in active_cells:
        rows.setdefault(int(item["y"]), []).append(item)

    targets: list[dict[str, Any]] = []
    for row_index, y in enumerate(sorted(rows.keys())):
        row_items = sorted(rows[y], key=lambda item: int(item["x"]))
        if row_index % 2 == 1:
            row_items.reverse()
        targets.extend(row_items)
    avg_active = sum(int(item["count"]) for item in active_cells) / max(len(active_cells), 1)
    target_keys = {(item["x"], item["y"]) for item in targets}

    route_points = [(grid_x - 24.0, grid_y + grid_h / 2)]
    impact_lengths = []
    total_length = 0.0

    for target in targets:
        px = target["x"] + cell / 2
        py = target["y"] + cell / 2
        last_x, last_y = route_points[-1]
        # Constrain path to orthogonal moves so auto-rotation stays Pac-Man-like.
        if abs(px - last_x) > 0.001:
            total_length += abs(px - last_x)
            route_points.append((px, last_y))
            last_x, last_y = route_points[-1]
        if abs(py - last_y) > 0.001:
            total_length += abs(py - last_y)
            route_points.append((px, py))
        elif route_points[-1] != (px, py):
            route_points.append((px, py))
        impact_lengths.append(total_length)

    if total_length <= 0:
        total_length = 1.0
        route_points = [route_points[0], (route_points[0][0] + 1.0, route_points[0][1])]
        impact_lengths = [1.0]

    impact_keys = [length / total_length for length in impact_lengths]

    growth_values = [1.0]
    current_scale = 1.0
    for target in targets:
        ratio = clamp(float(target["count"]) / max(avg_active, 1.0), 0.15, 3.2)
        current_scale = clamp(current_scale + 0.012 + 0.02 * (ratio / 3.2), 1.0, 1.78)
        growth_values.append(current_scale)

    growth_key_times = [0.0] + impact_keys
    if growth_key_times[-1] < 1.0:
        growth_key_times.append(1.0)
        growth_values.append(growth_values[-1])

    path_data = " ".join(
        [f"M {route_points[0][0]:.1f} {route_points[0][1]:.1f}"]
        + [f"L {x:.1f} {y:.1f}" for x, y in route_points[1:]]
    )

    title = f"{login}'s Pac-Man Contribution Run"
    generated_on = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    cycle = max(18.0, len(targets) * 0.33)

    pieces = []
    pieces.append(
        f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" role="img" aria-label="{title}">
  <defs>
    <linearGradient id="shell" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#07111f" />
      <stop offset="100%" stop-color="#0d1930" />
    </linearGradient>
    <linearGradient id="lane" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#132744" stop-opacity="0.88" />
      <stop offset="100%" stop-color="#102036" stop-opacity="0.82" />
    </linearGradient>
    <style>
      .t-main {{ font: 700 21px 'Segoe UI', 'Trebuchet MS', sans-serif; fill: #edf6ff; }}
      .t-sub {{ font: 500 12px 'Segoe UI', 'Trebuchet MS', sans-serif; fill: #a8c4ec; }}
      .t-mini {{ font: 500 10px 'Consolas', 'Courier New', monospace; fill: #7fa5d6; }}
      .grid-cell {{ rx: 2; ry: 2; }}
      .grid-bg {{ fill: #1a2743; }}
      .pacman-shell {{ fill: #ffd54a; }}
      .pacman-mouth {{ fill: {panel_bg}; }}
      .pacman-eye {{ fill: #0b1220; }}
      .chomp {{ fill: #fff0a6; opacity: 0; }}
    </style>
  </defs>

  <rect width="{width}" height="{height}" fill="url(#shell)" rx="18" />
  <rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="13" stroke="#29466f" stroke-opacity="0.7" />

  <text x="28" y="42" class="t-main">{title}</text>
  <text x="{width - 205}" y="{height - 20}" class="t-mini">auto-generated: {generated_on}</text>

  <rect x="{grid_x - 28}" y="{grid_y - 34}" width="{grid_w + 38}" height="{grid_h + 58}" fill="url(#lane)" rx="14" stroke="#355784" stroke-opacity="0.48"/>
  <text x="{grid_x - 4}" y="{grid_y - 14}" class="t-sub">Total contributions: {total}</text>
"""
    )

    for c in cells:
        pieces.append(
            f'  <rect class="grid-cell grid-bg" x="{c["x"]}" y="{c["y"]}" width="{cell}" height="{cell}" />\n'
        )

    for c in active_cells:
        if (c["x"], c["y"]) in target_keys:
            continue
        fill = palette[level_for_count(int(c["count"]), max_count)]
        pieces.append(
            f'  <rect class="grid-cell" x="{c["x"]}" y="{c["y"]}" width="{cell}" height="{cell}" fill="{fill}" />\n'
        )

    for idx, target in enumerate(targets):
        impact = impact_keys[idx]
        fade_a = clamp(impact - 0.010, 0.0, 1.0)
        fade_b = clamp(impact - 0.0015, 0.0, 1.0)
        fade_c = clamp(impact + 0.015, 0.0, 1.0)
        tx = target["x"] + cell / 2
        ty = target["y"] + cell / 2
        cell_fill = palette[level_for_count(int(target["count"]), max_count)]
        pieces.append(
            f"""  <rect x="{target["x"]}" y="{target["y"]}" width="{cell}" height="{cell}" fill="{cell_fill}" opacity="1">
    <animate attributeName="opacity" values="1;1;0;0;0;1" keyTimes="0;{fade_a:.5f};{fade_b:.5f};{impact:.5f};{fade_c:.5f};1" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </rect>
  <circle class="chomp" cx="{tx:.1f}" cy="{ty:.1f}" r="1.2">
    <animate attributeName="r" values="1.2;1.2;4.1;1.2" keyTimes="0;{fade_b:.5f};{impact:.5f};{fade_c:.5f}" dur="{cycle:.2f}s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0;0;0.95;0" keyTimes="0;{fade_b:.5f};{impact:.5f};{fade_c:.5f}" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </circle>
"""
        )

    pieces.append(
        f"""  <path id="pac-route" d="{path_data}" fill="none" stroke="none" />
  <g>
    <g>
      <g>
        <circle class="pacman-shell" cx="0" cy="0" r="12" />
        <polygon class="pacman-mouth" points="0,0 13,-2.6 13,2.6">
          <animate attributeName="points" values="0,0 13,-2.6 13,2.6;0,0 13,-9.8 13,9.8;0,0 13,-2.6 13,2.6" dur="0.32s" repeatCount="indefinite"/>
        </polygon>
        <circle class="pacman-eye" cx="-2.8" cy="-5.2" r="1.7" />
        <animateTransform attributeName="transform" type="scale" values="{';'.join(f'{value:.4f}' for value in growth_values)}" keyTimes="{';'.join(f'{value:.5f}' for value in growth_key_times)}" dur="{cycle:.2f}s" repeatCount="indefinite"/>
      </g>
      <animateMotion dur="{cycle:.2f}s" repeatCount="indefinite" rotate="auto">
        <mpath href="#pac-route" />
      </animateMotion>
    </g>
  </g>
</svg>
"""
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(pieces), encoding="utf-8")


def render_error_svg(login: str, error_text: str, out_path: pathlib.Path) -> None:
    safe_error = error_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="220" viewBox="0 0 1100 220" fill="none" role="img" aria-label="Pac-Man contribution graphic unavailable">
  <rect width="1100" height="220" rx="16" fill="#0c1528"/>
  <rect x="14" y="14" width="1072" height="192" rx="12" stroke="#385b90" stroke-opacity="0.5"/>
  <text x="30" y="56" style="font:700 24px 'Segoe UI',sans-serif;fill:#e7f0ff;">{login}'s Pac-Man Contribution Run</text>
  <text x="30" y="95" style="font:500 14px 'Segoe UI',sans-serif;fill:#abc2e8;">Could not load contribution data right now.</text>
  <text x="30" y="128" style="font:500 12px 'Consolas',monospace;fill:#7fa0d3;">{safe_error}</text>
</svg>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(svg, encoding="utf-8")


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner = repository.split("/", 1)[0] if "/" in repository else ""
    detected_owner = detect_owner_from_git_remote()
    login = os.environ.get("PROFILE_USERNAME", owner or detected_owner or "octocat")
    token = os.environ.get("GITHUB_TOKEN", "")
    out_file = pathlib.Path("assets/pacman-contrib.svg")

    if not token:
        render_svg(login, build_mock_calendar(login), out_file)
        return

    try:
        calendar = fetch_contribution_calendar(login, token)
        render_svg(login, calendar, out_file)
    except (RuntimeError, urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        render_svg(login, build_mock_calendar(login), out_file)
        render_error_svg(login, str(exc), pathlib.Path("assets/pacman-contrib-error.svg"))


if __name__ == "__main__":
    main()
