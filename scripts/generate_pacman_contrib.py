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


def is_power_cell(count: int, max_count: int) -> bool:
    return max_count >= 8 and count >= max(8, math.ceil(max_count * 0.75))


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
    grid_x = 54
    grid_y = 58
    grid_w = max(len(weeks), 52) * (cell + gap)
    grid_h = 7 * (cell + gap)

    width = grid_x + grid_w + 38
    height = grid_y + grid_h + 52
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

    rows_all: dict[int, list[dict[str, Any]]] = {}
    for item in cells:
        rows_all.setdefault(int(item["y"]), []).append(item)
    for row_items in rows_all.values():
        row_items.sort(key=lambda cell_item: int(cell_item["x"]))

    # Fixed snake route from bottom-left:
    # row 1 -> right, row 2 -> left, row 3 -> right, ...
    row_keys = sorted(rows_all.keys(), reverse=True)
    sweep_cells: list[dict[str, Any]] = []
    for row_index, row_y in enumerate(row_keys):
        row_items = rows_all[row_y]
        sweep_cells.extend(row_items if row_index % 2 == 0 else reversed(row_items))

    targets = [item for item in sweep_cells if int(item["count"]) > 0]
    target_keys = {(item["x"], item["y"]) for item in targets}

    first_sweep = sweep_cells[0]
    route_start_y = float(first_sweep["y"]) + cell / 2
    route_start_x = float(first_sweep["x"]) + cell / 2 - (cell + gap)
    route_points = [(route_start_x, route_start_y)]
    impact_lengths = []
    total_length = 0.0

    def push_route_point(px: float, py: float) -> None:
        nonlocal total_length
        last_x, last_y = route_points[-1]
        if abs(px - last_x) < 0.001 and abs(py - last_y) < 0.001:
            return
        total_length += math.hypot(px - last_x, py - last_y)
        route_points.append((px, py))

    for sweep_cell in sweep_cells:
        px = float(sweep_cell["x"]) + cell / 2
        py = float(sweep_cell["y"]) + cell / 2
        last_x, last_y = route_points[-1]
        if abs(py - last_y) > 0.001:
            # Move in orthogonal segments (vertical then horizontal) to avoid diagonal jitter.
            push_route_point(last_x, py)
        push_route_point(px, py)
        if int(sweep_cell["count"]) > 0:
            impact_lengths.append(total_length)

    if total_length <= 0:
        total_length = 1.0
        route_points = [route_points[0], (route_points[0][0] + 1.0, route_points[0][1])]
        impact_lengths = [1.0]

    impact_keys = [length / total_length for length in impact_lengths]

    cycle = max(45.0, len(targets) * 0.82)

    counter_total = max(total, 0)
    popup_counter_starts: list[float] = []
    for impact in impact_keys:
        popup_rise = clamp(impact + 0.0015, 0.0, 1.0)
        popup_counter_starts.append(popup_rise)

    counter_steps: list[tuple[float, float, int]] = []
    if targets:
        counter_steps.append((0.0, popup_counter_starts[0], 0))
        running_total = 0
        target_sum = max(sum(int(item["count"]) for item in targets), 1)
        shown_total = 0
        for idx, target in enumerate(targets):
            running_total += int(target["count"])
            start = popup_counter_starts[idx]
            end = popup_counter_starts[idx + 1] if idx + 1 < len(targets) else 1.0
            mapped_value = int(round(counter_total * (running_total / target_sum)))
            shown_total = max(shown_total, min(mapped_value, counter_total))
            counter_steps.append((start, end, shown_total))
        if counter_steps[-1][2] != counter_total:
            last_start, _, _ = counter_steps[-1]
            counter_steps[-1] = (last_start, 1.0, counter_total)
    else:
        counter_steps.append((0.0, 1.0, counter_total))

    segment_angles: list[int] = []
    segment_flips: list[int] = []
    segment_end_keys: list[float] = []
    walked = 0.0
    for idx in range(1, len(route_points)):
        x0, y0 = route_points[idx - 1]
        x1, y1 = route_points[idx]
        dx = x1 - x0
        dy = y1 - y0
        seg_length = math.hypot(dx, dy)
        if seg_length <= 0.0:
            continue
        walked += seg_length
        if abs(dx) >= abs(dy):
            angle = 0
            flip = 1 if dx >= 0 else -1
        else:
            angle = 90 if dy > 0 else -90
            flip = 1
        segment_angles.append(angle)
        segment_flips.append(flip)
        segment_end_keys.append(walked / total_length)

    if not segment_angles:
        segment_angles = [0]
        segment_flips = [1]
        segment_end_keys = [1.0]

    rotation_key_times = [0.0] + segment_end_keys
    rotation_values = segment_angles + [segment_angles[-1]]
    flip_values = segment_flips + [segment_flips[-1]]

    path_data = " ".join(
        [f"M {route_points[0][0]:.1f} {route_points[0][1]:.1f}"]
        + [f"L {x:.1f} {y:.1f}" for x, y in route_points[1:]]
    )

    title = f"{login}'s Pac-Man Contribution Run"
    counter_badge_x = 44
    counter_badge_y = 22
    counter_badge_w = 188
    counter_badge_h = 18
    counter_label_x = counter_badge_x + 12
    counter_text_y = counter_badge_y + 13
    counter_value_x = counter_badge_x + 136
    counter_suffix_x = counter_value_x + 18
    progress_x = counter_badge_x + counter_badge_w + 18
    progress_y = counter_badge_y + 7
    progress_w = max(120, width - progress_x - 42)
    progress_h = 4
    # Robust GitHub-friendly Pac-Man: circle body + animated mouth wedge overlay.
    mouth_closed = "0,0 8.1,-1.8 8.1,1.8"
    mouth_open = "0,0 8.1,-5.3 8.1,5.3"

    pieces = []
    popup_pieces = []
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
      .t-sub {{ font: 500 12px 'Segoe UI', 'Trebuchet MS', sans-serif; fill: #a8c4ec; }}
      .t-counter {{ font: 700 12px 'Consolas', 'Courier New', monospace; fill: #dce9ff; text-anchor: middle; }}
      .grid-cell {{ rx: 2; ry: 2; }}
      .grid-bg {{ fill: #1a2743; }}
      .pacman-shell {{ fill: #ffd54a; }}
      .pacman-mouth {{ fill: #132744; }}
      .pacman-eye {{ fill: #0b1220; }}
      .score-pop {{ font: 800 11px 'Consolas', 'Courier New', monospace; fill: #ffe58a; stroke: #07111f; stroke-width: 1; paint-order: stroke fill; opacity: 0; text-anchor: middle; }}
      .progress-track {{ fill: #122340; }}
      .progress-fill {{ fill: #ffd54a; }}
      .power-cell {{ stroke: #ffd54a; stroke-width: 1; }}
    </style>
  </defs>

  <rect width="{width}" height="{height}" fill="url(#shell)" rx="18" />
  <rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="13" stroke="#29466f" stroke-opacity="0.7" />
  <rect x="{counter_badge_x}" y="{counter_badge_y}" width="{counter_badge_w}" height="{counter_badge_h}" rx="9" fill="#102036" stroke="#29466f" stroke-opacity="0.65" />

  <rect x="{grid_x - 18}" y="{grid_y - 18}" width="{grid_w + 24}" height="{grid_h + 36}" fill="url(#lane)" rx="14" stroke="#355784" stroke-opacity="0.48"/>
"""
    )

    pieces.append(
        f'  <text x="{counter_label_x}" y="{counter_text_y}" class="t-sub">Commit amount</text>\n'
    )
    pieces.append(
        f'  <text x="{counter_suffix_x}" y="{counter_text_y}" class="t-sub">/{counter_total}</text>\n'
    )
    pieces.append(
        f'  <rect x="{progress_x}" y="{progress_y}" width="{progress_w}" height="{progress_h}" rx="{progress_h / 2:.1f}" class="progress-track" />\n'
    )

    progress_times = [clamp(step[0], 0.0, 1.0) for step in counter_steps]
    progress_values = [
        progress_w * (clamp(value, 0, counter_total) / counter_total) if counter_total else 0
        for _, _, value in counter_steps
    ]
    if progress_times[0] != 0.0:
        progress_times.insert(0, 0.0)
        progress_values.insert(0, 0.0)
    if progress_times[-1] != 1.0:
        progress_times.append(1.0)
        progress_values.append(progress_values[-1])

    pieces.append(
        f"""  <rect x="{progress_x}" y="{progress_y}" width="0" height="{progress_h}" rx="{progress_h / 2:.1f}" class="progress-fill">
    <animate attributeName="width" values="{';'.join(f'{value:.2f}' for value in progress_values)}" keyTimes="{';'.join(f'{value:.5f}' for value in progress_times)}" calcMode="discrete" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </rect>
"""
    )

    for idx, (start, end, value) in enumerate(counter_steps):
        show_start = clamp(start, 0.0, 1.0)
        show_end = clamp(end, show_start, 1.0)
        if idx > 0:
            show_start = max(show_start, clamp(counter_steps[idx - 1][1], 0.0, 1.0))
        if show_end <= show_start:
            show_end = min(1.0, show_start + 0.0005)
        pieces.append(
            f"""  <text x="{counter_value_x}" y="{counter_text_y}" class="t-counter" opacity="0">{value}
    <animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;{show_start:.5f};{show_start:.5f};{show_end:.5f};{show_end:.5f};1" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </text>
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
        power_class = ' class="grid-cell power-cell"' if is_power_cell(int(c["count"]), max_count) else ' class="grid-cell"'
        pieces.append(
            f'  <rect{power_class} x="{c["x"]}" y="{c["y"]}" width="{cell}" height="{cell}" fill="{fill}" />\n'
        )

    for idx, target in enumerate(targets):
        impact = impact_keys[idx]
        fade_start = clamp(impact - 0.002, 0.0, 1.0)
        restore = clamp(impact + 0.030, 0.0, 1.0)
        cell_fill = palette[level_for_count(int(target["count"]), max_count)]
        power_class = ' class="power-cell"' if is_power_cell(int(target["count"]), max_count) else ""
        popup_hit = impact
        popup_rise = clamp(impact + 0.009, 0.0, 1.0)
        popup_mid = clamp(impact + 0.030, 0.0, 1.0)
        popup_end = clamp(impact + 0.048, 0.0, 1.0)
        if popup_end <= popup_rise:
            popup_rise = max(0.0, popup_end - 0.001)
        if popup_mid <= popup_rise:
            popup_mid = max(0.0, popup_end - 0.002)
        if popup_rise <= popup_hit:
            popup_hit = max(0.0, popup_rise - 0.001)
        tx = float(target["x"]) + cell / 2
        ty = float(target["y"]) + cell / 2
        popup_y = ty - 5.0
        popup_y_top = popup_y - 4.5
        pieces.append(
            f"""  <rect{power_class} x="{target["x"]}" y="{target["y"]}" width="{cell}" height="{cell}" fill="{cell_fill}" opacity="1">
    <animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;{fade_start:.5f};{impact:.5f};{restore:.5f};1" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </rect>
"""
        )
        popup_pieces.append(
            f"""  <text class="score-pop" x="{tx:.1f}" y="{popup_y:.1f}" opacity="0">+{int(target["count"])}
    <animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;{popup_hit:.5f};{popup_rise:.5f};{popup_mid:.5f};{popup_end:.5f};1" dur="{cycle:.2f}s" repeatCount="indefinite"/>
    <animate attributeName="y" values="{popup_y:.1f};{popup_y:.1f};{popup_y_top:.1f};{popup_y_top:.1f};{popup_y_top:.1f};{popup_y_top:.1f}" keyTimes="0;{popup_hit:.5f};{popup_rise:.5f};{popup_mid:.5f};{popup_end:.5f};1" dur="{cycle:.2f}s" repeatCount="indefinite"/>
  </text>
"""
        )

    pieces.append(
        f"""  <path id="pac-route" d="{path_data}" fill="none" stroke="none" />
  <g>
    <animateMotion dur="{cycle:.2f}s" repeatCount="indefinite" rotate="0" calcMode="linear">
      <mpath href="#pac-route" />
    </animateMotion>
    <g>
      <circle class="pacman-shell" cx="0" cy="0" r="7.3" />
      <circle class="pacman-shell" cx="0" cy="0" r="7.3" opacity="0.14">
        <animate attributeName="r" values="7.3;8.7;7.3" dur="0.42s" repeatCount="indefinite" />
        <animate attributeName="opacity" values="0.16;0.04;0.16" dur="0.42s" repeatCount="indefinite" />
      </circle>
      <polygon class="pacman-mouth" points="{mouth_closed}">
        <animate attributeName="points" values="{mouth_closed};{mouth_open};{mouth_closed}" dur="0.42s" repeatCount="indefinite" />
      </polygon>
      <circle class="pacman-eye" cx="-1.2" cy="-2.9" r="0.98" />
      <animateTransform attributeName="transform" type="rotate" values="{';'.join(str(angle) for angle in rotation_values)}" keyTimes="{';'.join(f'{value:.5f}' for value in rotation_key_times)}" calcMode="discrete" dur="{cycle:.2f}s" repeatCount="indefinite"/>
      <animateTransform attributeName="transform" type="scale" values="{';'.join(f'{value} 1' for value in flip_values)}" keyTimes="{';'.join(f'{value:.5f}' for value in rotation_key_times)}" calcMode="discrete" additive="sum" dur="{cycle:.2f}s" repeatCount="indefinite"/>
    </g>
  </g>
  <g id="score-overlay">
{''.join(popup_pieces)}  </g>
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
        # Safety: never overwrite the tracked profile SVG with mock data.
        # Local runs without token should leave the last real SVG untouched.
        print("GITHUB_TOKEN missing - keeping existing assets/pacman-contrib.svg unchanged.")
        return

    try:
        calendar = fetch_contribution_calendar(login, token)
        render_svg(login, calendar, out_file)
    except (RuntimeError, urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
        # Safety: if API fetch fails, keep the previous real SVG instead of
        # replacing it with random mock history.
        print(f"Contribution fetch failed - keeping existing SVG unchanged: {exc}")
        render_error_svg(login, str(exc), pathlib.Path("assets/pacman-contrib-error.svg"))


if __name__ == "__main__":
    main()
