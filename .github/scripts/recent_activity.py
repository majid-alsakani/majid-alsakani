#!/usr/bin/env python3
"""Render public GitHub events inside the README activity markers."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

START = "<!--START_SECTION:activity-->"
END = "<!--END_SECTION:activity-->"
README = Path("README.md")


def escape(value: object) -> str:
    """Prevent event text from creating Markdown links or HTML in the README."""
    return re.sub(r"([\\`*_{}\[\]<>()!|])", r"\\\1", str(value)).replace("\n", " ")


def event_line(event: dict) -> str | None:
    repository = event.get("repo", {}).get("name", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        return None
    repo_url = f"https://github.com/{repository}"
    label = f"[{escape(repository)}]({repo_url})"
    kind = event.get("type")
    payload = event.get("payload") or {}
    if kind == "PushEvent":
        return f"- Pushed commits to {label}"
    if kind == "PullRequestEvent" and payload.get("action") in ("opened", "closed"):
        number = (payload.get("pull_request") or {}).get("number")
        if isinstance(number, int) and number > 0:
            return f"- {escape(payload['action'].title())} [PR #{number}]({repo_url}/pull/{number}) in {label}"
    if kind == "IssuesEvent" and payload.get("action") in ("opened", "closed"):
        number = (payload.get("issue") or {}).get("number")
        if isinstance(number, int) and number > 0:
            return f"- {escape(payload['action'].title())} [issue #{number}]({repo_url}/issues/{number}) in {label}"
    if kind == "CreateEvent" and payload.get("ref_type") == "repository":
        return f"- Created {label}"
    return None


def render(events: list[dict], limit: int = 10) -> str:
    lines = []
    for event in events:
        line = event_line(event)
        if line:
            lines.append(line)
        if len(lines) == limit:
            break
    return "\n".join(lines) if lines else "No recent public activity."


def update_readme(readme: str, activity: str) -> str:
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError("README must contain exactly one pair of activity markers")
    prefix, tail = readme.split(START, 1)
    _, suffix = tail.split(END, 1)
    return f"{prefix}{START}\n{activity}\n{END}{suffix}"


def main() -> None:
    login = os.environ["PROFILE_LOGIN"]
    token = os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/users/{urllib.parse.quote(login, safe='')}/events/public?per_page=100"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "majid-profile-activity",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        events = json.load(response)
    if not isinstance(events, list):
        raise ValueError("GitHub events response is not a list")
    current = README.read_text(encoding="utf-8")
    updated = update_readme(current, render(events))
    if updated != current:
        README.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
