#!/usr/bin/env python3
"""PreToolUse hook: snapshots files before Claude Code edits them.

Receives JSON on stdin with session_id, tool_name, tool_input.
Copies the file to ~/.claude/session-snapshots/{session_id}/files/...
Only the first snapshot per file is kept (true "before" state).
"""

import json
import os
import shutil
import sys
import time

SNAPSHOTS_DIR = os.path.expanduser("~/.claude/session-snapshots")
CLEANUP_INTERVAL = 3600  # 1 hour
MAX_AGE = 7 * 24 * 3600  # 7 days


def cleanup_old_snapshots():
    marker = os.path.join(SNAPSHOTS_DIR, ".last_cleanup")
    now = time.time()

    if os.path.exists(marker):
        if now - os.path.getmtime(marker) < CLEANUP_INTERVAL:
            return

    for entry in os.scandir(SNAPSHOTS_DIR):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        meta_path = os.path.join(entry.path, "meta.json")
        if os.path.exists(meta_path):
            if now - os.path.getmtime(meta_path) > MAX_AGE:
                shutil.rmtree(entry.path, ignore_errors=True)

    # Touch marker
    with open(marker, "w") as f:
        f.write(str(now))


def main():
    data = json.load(sys.stdin)

    session_id = data.get("session_id", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    if tool_name not in ("Write", "Edit"):
        return

    file_path = tool_input.get("file_path", "")
    if not file_path or not os.path.isabs(file_path):
        return

    if not os.path.exists(file_path):
        return  # New file, nothing to snapshot

    session_dir = os.path.join(SNAPSHOTS_DIR, session_id)
    files_dir = os.path.join(session_dir, "files")

    # Strip leading slash to build relative path
    rel_path = file_path.lstrip("/")
    dest = os.path.join(files_dir, rel_path)

    if os.path.exists(dest):
        return  # First edit wins

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(file_path, dest)

    # Write meta.json once per session
    meta_path = os.path.join(session_dir, "meta.json")
    if not os.path.exists(meta_path):
        meta = {
            "session_id": session_id,
            "project_cwd": os.getcwd(),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    # Opportunistic cleanup
    try:
        cleanup_old_snapshots()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # Hook must never fail
