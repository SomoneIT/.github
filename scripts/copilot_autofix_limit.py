#!/usr/bin/env python3
"""Decide whether Copilot may attempt another automatic fix on a pull request.

Counts the PR comments carrying the autofix marker and compares it to a limit.
Inputs come from the environment: GH_TOKEN, REPOSITORY, PR_NUMBER, AUTOFIX_LIMIT
and optionally MARKER. Writes `allowed=true|false` and `attempts=N` to
$GITHUB_OUTPUT (or stdout when unset).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

DEFAULT_MARKER = "<!-- copilot-autofix -->"
API = "https://api.github.com"


def count_attempts(comments: list[dict], marker: str) -> int:
    return sum(1 for comment in comments if marker in (comment.get("body") or ""))


def is_allowed(attempts: int, limit: int) -> bool:
    return attempts < limit


def fetch_comments(repository: str, pr_number: int, token: str) -> list[dict]:
    comments: list[dict] = []
    page = 1
    while True:
        url = f"{API}/repos/{repository}/issues/{pr_number}/comments?per_page=100&page={page}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            batch = json.load(response)
        comments.extend(batch)
        if len(batch) < 100:
            return comments
        page += 1


def write_outputs(values: dict[str, str]) -> None:
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(lines)
    else:
        print(lines, end="")


def main() -> int:
    try:
        limit = int(os.environ.get("AUTOFIX_LIMIT", "3"))
        pr_number = int(os.environ["PR_NUMBER"])
        repository = os.environ["REPOSITORY"]
        token = os.environ["GH_TOKEN"]
    except (KeyError, ValueError) as err:
        print(f"error: invalid or missing environment: {err}", file=sys.stderr)
        return 2
    marker = os.environ.get("MARKER", DEFAULT_MARKER)
    attempts = count_attempts(fetch_comments(repository, pr_number, token), marker)
    write_outputs({"allowed": str(is_allowed(attempts, limit)).lower(), "attempts": str(attempts)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
