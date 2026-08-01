#!/usr/bin/env python3
"""Create a *signed* (Verified) commit on a branch using the GitHub GraphQL API.

Local `git commit` inside Actions produces unsigned commits, which are rejected
when a branch requires signed commits. Commits created through the GitHub API
with the workflow token are signed by GitHub automatically.

Usage:
    python .github/scripts/signed_commit.py "commit message" [path ...]

Paths default to the whole worktree. Requires GITHUB_TOKEN and GITHUB_REPOSITORY.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com/graphql"

MUTATION = """
mutation ($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) {
    commit { oid url }
  }
}
"""


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def changed_paths(paths: list[str]) -> tuple[list[str], list[str]]:
    run("git", "add", "-A", "--", *(paths or ["."]))
    out = run("git", "diff", "--cached", "--name-status", "-z")
    additions: list[str] = []
    deletions: list[str] = []
    tokens = [t for t in out.split("\0") if t]
    i = 0
    while i < len(tokens):
        status = tokens[i]
        if status.startswith("R"):  # rename: old, new
            deletions.append(tokens[i + 1])
            additions.append(tokens[i + 2])
            i += 3
            continue
        path = tokens[i + 1]
        (deletions if status == "D" else additions).append(path)
        i += 2
    return additions, deletions


def graphql(token: str, variables: dict) -> dict:
    body = json.dumps({"query": MUTATION, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "majid-alsakani-signed-commit",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network failure path
        sys.exit(f"GitHub API error {exc.code}: {exc.read().decode()[:500]}")
    if payload.get("errors"):
        sys.exit(f"GraphQL error: {json.dumps(payload['errors'])[:500]}")
    return payload["data"]["createCommitOnBranch"]["commit"]


def main() -> int:
    if len(sys.argv) < 2:
        return sys.exit("usage: signed_commit.py <message> [path ...]")
    message = sys.argv[1]
    paths = sys.argv[2:]

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return sys.exit("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    branch = os.environ.get("GITHUB_REF_NAME", "main")

    additions, deletions = changed_paths(paths)
    if not additions and not deletions:
        print("Nothing changed - no signed commit needed.")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                fh.write("published=false\n")
        return 0

    head = run("git", "rev-parse", "HEAD").strip()
    variables = {
        "input": {
            "branch": {
                "repositoryNameWithOwner": repo,
                "branchName": branch,
            },
            "message": {"headline": message},
            "expectedHeadOid": head,
            "fileChanges": {
                "additions": [
                    {
                        "path": p,
                        "contents": base64.b64encode(open(p, "rb").read()).decode(),
                    }
                    for p in additions
                ],
                "deletions": [{"path": p} for p in deletions],
            },
        }
    }
    commit = graphql(token, variables)
    print(f"Signed commit created: {commit['oid'][:8]} -> {commit['url']}")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write("published=true\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
