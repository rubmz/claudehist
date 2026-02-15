#!/usr/bin/env python3
"""Setup script for Claude Code Session Diff Tracker.

Adds the PreToolUse hook to ~/.claude/settings.json (Linux/macOS/Windows).
Safe to run multiple times — skips if hook is already configured.
"""

import json
import os
import platform
import sys


def get_claude_settings_path():
    system = platform.system()
    if system == "Windows":
        home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    else:
        home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "settings.json")


def get_hook_command():
    hook_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_snapshot.py")
    system = platform.system()
    if system == "Windows":
        return f"python \"{hook_script}\""
    else:
        return f"python3 \"{hook_script}\""


def main():
    settings_path = get_claude_settings_path()
    hook_command = get_hook_command()

    print(f"Platform:      {platform.system()}")
    print(f"Settings file: {settings_path}")
    print(f"Hook command:  {hook_command}")
    print()

    # Load existing settings or start fresh
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
        print("Found existing settings.json")
    else:
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        settings = {}
        print("No settings.json found, creating new one")

    # Check if hook already exists
    hooks = settings.get("hooks", {})
    pre_tool_use = hooks.get("PreToolUse", [])

    for matcher_group in pre_tool_use:
        for hook in matcher_group.get("hooks", []):
            if "hook_snapshot.py" in hook.get("command", ""):
                print("Hook already configured — nothing to do.")
                return

    # Add the hook
    new_matcher = {
        "matcher": "Write|Edit",
        "hooks": [{
            "type": "command",
            "command": hook_command,
        }],
    }
    pre_tool_use.append(new_matcher)
    hooks["PreToolUse"] = pre_tool_use
    settings["hooks"] = hooks

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    print("Hook added successfully.")
    print()
    print("Restart Claude Code for the hook to take effect.")


if __name__ == "__main__":
    main()
