#!/usr/bin/env python3
"""Copy detector.

Searches GitHub for content carrying this profile's hidden fingerprints and
opens a single, continuously updated issue whenever a copy is found.

Zero third-party dependencies — stdlib only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
OWNER = os.environ.get("OWNER", "majid-alsakani")
REPO = os.environ.get("REPO", "majid-alsakani/majid-alsakani")
SCAN_TOKEN = os.environ["SCAN_TOKEN"]
ISSUE_TOKEN = os.environ.get("GITHUB_TOKEN", SCAN_TOKEN)
ISSUE_TITLE = "🚨 Copy Detector — unauthorized copies of my profile content"

# Fingerprints: unique strings that only exist in the original work.
FINGERPRINTS = [
    "MJDALSK-CANARY-9F4C2E7A1B",
    "majid-alsakani/majid-alsakani/main/Assets/Gif",
    "Backend Engineer · API Architect · Automation & AI Bots Specialist",
    "profile_engine",
]


def call(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(
        path if path.startswith("http") else API + path,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "majid-alsakani-copy-detector",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        data=json.dumps(body).encode() if body else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:400]


def search_code(fingerprint: str) -> list[dict]:
    """Return matches for one fingerprint, excluding my own repositories."""
    query = f'"{fingerprint}" -user:{OWNER}'
    status, data = call(
        "GET",
        "/search/code?" + urllib.parse.urlencode({"q": query, "per_page": 30}),
        SCAN_TOKEN,
    )
    if status != 200:
        print(f"  ! search unavailable for this fingerprint (HTTP {status}) — skipped")
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def find_issue() -> dict | None:
    status, data = call("GET", f"/repos/{REPO}/issues?state=open&per_page=100", ISSUE_TOKEN)
    if status != 200 or not isinstance(data, list):
        return None
    return next((i for i in data if i.get("title") == ISSUE_TITLE), None)


def main() -> None:
    hits: dict[str, set[str]] = {}
    for fingerprint in FINGERPRINTS:
        print(f"scanning: {fingerprint[:48]}")
        for item in search_code(fingerprint):
            repo = item.get("repository", {}).get("full_name", "?")
            if repo.lower().startswith(f"{OWNER.lower()}/"):
                continue
            hits.setdefault(repo, set()).add(item.get("html_url", ""))
        time.sleep(6)  # stay well under the code-search rate limit

    if not hits:
        print("✅ no copies detected")
        return

    lines = [
        "## 🚨 Unauthorized copies detected",
        "",
        "GitHub code search found content carrying the hidden fingerprints of",
        f"[`{REPO}`](https://github.com/{REPO}), which is licensed",
        "**CC BY-NC-ND 4.0** (no derivatives, no commercial use, attribution required).",
        "",
        "| Repository | Matching files |",
        "| --- | --- |",
    ]
    for repo, urls in sorted(hits.items()):
        files = " · ".join(f"[file]({u})" for u in sorted(urls) if u)
        lines.append(f"| [`{repo}`](https://github.com/{repo}) | {files} |")
    lines += [
        "",
        "### Next steps",
        "1. Verify the match is a real copy (not a legitimate quotation with attribution).",
        "2. Ask the author politely to add attribution or take it down.",
        "3. If ignored, file a DMCA notice: <https://github.com/contact/dmca-notice>",
        "   — see [`COPYRIGHT.md`](../blob/main/COPYRIGHT.md) for the ready-made wording.",
        "",
        f"_Automated scan · {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}_",
    ]
    body = "\n".join(lines)

    existing = find_issue()
    if existing:
        status, _ = call(
            "PATCH", f"/repos/{REPO}/issues/{existing['number']}", ISSUE_TOKEN, {"body": body}
        )
        print(f"updated issue #{existing['number']} (HTTP {status})")
    else:
        status, data = call(
            "POST",
            f"/repos/{REPO}/issues",
            ISSUE_TOKEN,
            {"title": ISSUE_TITLE, "body": body, "labels": ["copyright"]},
        )
        print(f"opened issue (HTTP {status})")


if __name__ == "__main__":
    main()
