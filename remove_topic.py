#!/usr/bin/env python3
"""
Remove a tracked topic by id from config/topics.yml.

Text-based block removal so the file's comments and formatting survive (a YAML
round-trip would strip them). Reads the id from the issue body (`remove: <id>`)
via ISSUE_BODY, or from REMOVE_ID. Observations stay in the DB but `pool` only
emits active topics, so the removed one drops off the board on the next pool.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
ID_RE = re.compile(r"^\s*-\s+id:\s*(.+?)\s*$")


def wanted_id() -> str:
    body = os.environ.get("ISSUE_BODY", "")
    for line in body.splitlines():
        m = re.match(r"^\s*remove:\s*(\S+)\s*$", line)
        if m:
            return m.group(1).strip()
    return (os.environ.get("REMOVE_ID") or "").strip()


def main() -> int:
    tid = wanted_id().strip().strip("\"'")
    if not tid:
        print("::warning::no topic id given")
        print("REASON=No topic id was provided.")
        return 2

    path = ROOT / "config" / "topics.yml"
    text = path.read_text()
    ids = [t.get("id") for t in (yaml.safe_load(text) or {}).get("topics", [])]
    if tid not in ids:
        print(f"NOT_FOUND={tid}")
        print(f"REASON=No topic '{tid}' is on the board.")
        return 0

    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        m = ID_RE.match(ln)
        if m and m.group(1).strip().strip("\"'") == tid:
            start = i
            break
    if start is None:
        print(f"NOT_FOUND={tid}")
        return 0

    end = len(lines)
    for j in range(start + 1, len(lines)):
        if ID_RE.match(lines[j]):
            end = j
            break
    # Also swallow a "# ..." comment line immediately preceding the block.
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1

    del lines[start:end]
    path.write_text("".join(lines))
    print(f"::notice::Removed topic {tid}")
    print(f"REMOVED_TOPIC_ID={tid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
