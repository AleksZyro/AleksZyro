#!/usr/bin/env python3
import json
import os
import pathlib
import urllib.parse
import urllib.request
from typing import Any


LANGUAGE_COLORS = {
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "C#": "#6b4bcc",
    "HTML": "#e34c26",
    "CSS": "#663399",
    "Java": "#b07219",
    "Jupyter Notebook": "#DA5B0B",
    "SQL": "#336791",
    "Shell": "#89e051",
    "PowerShell": "#012456",
}


GRAPHQL_QUERY = """
query($login: String!) {
  user(login: $login) {
    followers {
      totalCount
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
      }
    }
  }
}
"""


def github_request(url: str, token: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-cards-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def github_graphql(login: str, token: str) -> dict[str, Any]:
    payload = json.dumps({"query": GRAPHQL_QUERY, "variables": {"login": login}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-cards-generator",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    if "errors" in data:
        raise RuntimeError(str(data["errors"]))
    user = data.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user '{login}' not found.")
    return user


def fetch_public_repos(login: str, token: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/users/{urllib.parse.quote(login)}/repos"
            f"?per_page=100&page={page}&type=owner&sort=updated"
        )
        batch = github_request(url, token)
        if not batch:
            break
        repos.extend(repo for repo in batch if not repo.get("fork"))
        if len(batch) < 100:
            break
        page += 1
    return repos


def aggregate_languages(repos: list[dict[str, Any]], token: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repo in repos:
        languages_url = repo.get("languages_url")
        if not languages_url:
            continue
        data = github_request(languages_url, token)
        for language, amount in data.items():
            totals[language] = totals.get(language, 0) + int(amount)
    return totals


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_languages_card(login: str, languages: dict[str, int], out_path: pathlib.Path) -> None:
    width = 530
    height = 230
    card_bg = "#0d1117"
    border = "#30363d"
    title = "#e6edf3"
    text = "#9fb3c8"

    sorted_languages = sorted(languages.items(), key=lambda item: item[1], reverse=True)[:6]
    total = sum(amount for _, amount in sorted_languages) or 1

    bar_x = 48
    bar_y = 92
    bar_w = 330
    bar_h = 14
    legend_start_y = 138
    legend_gap_y = 34
    left_x = 52
    right_x = 280

    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" role="img" aria-label="{xml_escape(login)} language usage">',
        f'<rect width="{width}" height="{height}" rx="16" fill="{card_bg}"/>',
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="15" stroke="{border}"/>',
        f'<text x="48" y="54" style="font:700 20px Segoe UI, sans-serif; fill:{title};">Most used languages</text>',
        f'<rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="7" fill="#161b22"/>',
    ]

    cursor = bar_x
    for language, amount in sorted_languages:
        segment = round(bar_w * (amount / total), 2)
        color = LANGUAGE_COLORS.get(language, "#58a6ff")
        pieces.append(
            f'<rect x="{cursor:.2f}" y="{bar_y}" width="{segment:.2f}" height="{bar_h}" rx="7" fill="{color}"/>'
        )
        cursor += segment

    for idx, (language, amount) in enumerate(sorted_languages):
        column_x = left_x if idx % 2 == 0 else right_x
        row_y = legend_start_y + (idx // 2) * legend_gap_y
        color = LANGUAGE_COLORS.get(language, "#58a6ff")
        percentage = amount / total * 100
        label = xml_escape(f"{language} {percentage:.2f}%")
        pieces.append(f'<circle cx="{column_x}" cy="{row_y - 4}" r="6" fill="{color}"/>')
        pieces.append(
            f'<text x="{column_x + 14}" y="{row_y}" style="font:500 12px Segoe UI, sans-serif; fill:{text};">{label}</text>'
        )

    pieces.append("</svg>")
    out_path.write_text("".join(pieces), encoding="utf-8")


def render_stats_card(login: str, user: dict[str, Any], repos: list[dict[str, Any]], out_path: pathlib.Path) -> None:
    width = 530
    height = 230
    card_bg = "#0d1117"
    border = "#30363d"
    title = "#e6edf3"
    text = "#9fb3c8"
    accent = "#58a6ff"

    total_stars = sum(int(repo.get("stargazers_count", 0)) for repo in repos)
    public_repos = int(user.get("repositories", {}).get("totalCount", 0))
    followers = int(user.get("followers", {}).get("totalCount", 0))
    yearly_contribs = int(
        user.get("contributionsCollection", {})
        .get("contributionCalendar", {})
        .get("totalContributions", 0)
    )
    top_repo = max(repos, key=lambda repo: int(repo.get("stargazers_count", 0)), default=None)
    top_repo_name = top_repo.get("name", "-") if top_repo else "-"

    rows = [
        ("Last year contributions", str(yearly_contribs)),
        ("Public repositories", str(public_repos)),
        ("Followers", str(followers)),
        ("Stars earned", str(total_stars)),
        ("Top starred repo", top_repo_name),
    ]

    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" fill="none" role="img" aria-label="{xml_escape(login)} GitHub stats">',
        f'<rect width="{width}" height="{height}" rx="16" fill="{card_bg}"/>',
        f'<rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="15" stroke="{border}"/>',
        f'<text x="48" y="54" style="font:700 20px Segoe UI, sans-serif; fill:{title};">{xml_escape(login)} GitHub stats</text>',
    ]

    for idx, (label, value) in enumerate(rows):
        y = 98 + idx * 31
        pieces.append(
            f'<text x="48" y="{y}" style="font:600 13px Segoe UI, sans-serif; fill:{text};">{xml_escape(label)}</text>'
        )
        pieces.append(
            f'<text x="328" y="{y}" style="font:700 14px Segoe UI, sans-serif; fill:{title};">{xml_escape(value)}</text>'
        )

    pieces.extend(
        [
            f'<circle cx="448" cy="118" r="46" fill="#161b22" stroke="#6e7681" stroke-width="5"/>',
            f'<path d="M432 95c0-7 6-13 13-13h6c7 0 13 6 13 13v10h-8v-10c0-3-2-5-5-5h-6c-3 0-5 2-5 5v10h-8V95z" fill="{accent}"/>',
            f'<rect x="429" y="104" width="38" height="34" rx="7" fill="{accent}"/>',
            f'<path d="M437 112h22v6h-22zm0 11h22v6h-22z" fill="#0d1117"/>',
            f'<circle cx="448" cy="118" r="2.7" fill="#0d1117"/>',
            "</svg>",
        ]
    )

    out_path.write_text("".join(pieces), encoding="utf-8")


def main() -> None:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    owner = repository.split("/", 1)[0] if "/" in repository else ""
    login = os.environ.get("PROFILE_USERNAME", owner or "octocat")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("GITHUB_TOKEN missing - skipping profile cards generation.")
        return

    user = github_graphql(login, token)
    repos = fetch_public_repos(login, token)
    languages = aggregate_languages(repos, token)

    assets_dir = pathlib.Path("assets")
    assets_dir.mkdir(parents=True, exist_ok=True)
    render_languages_card(login, languages, assets_dir / "profile-languages.svg")
    render_stats_card(login, user, repos, assets_dir / "profile-stats.svg")
    print("Generated profile-languages.svg and profile-stats.svg")


if __name__ == "__main__":
    main()
