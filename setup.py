#!/usr/bin/env python3
"""Setup script for Claude Code Session Diff Tracker.

Adds the PreToolUse hook to ~/.claude/settings.json and installs the
/history and /last slash commands to ~/.claude/commands/.
Safe to run multiple times — skips if already configured.
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


def get_claude_commands_dir():
    system = platform.system()
    if system == "Windows":
        home = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    else:
        home = os.path.expanduser("~")
    return os.path.join(home, ".claude", "commands")


def _install_command(name, content):
    """Install a slash command to ~/.claude/commands/<name>.md."""
    commands_dir = get_claude_commands_dir()
    cmd_path = os.path.join(commands_dir, f"{name}.md")

    if os.path.exists(cmd_path):
        print(f"/{name} command already installed.")
        return

    os.makedirs(commands_dir, exist_ok=True)

    with open(cmd_path, "w") as f:
        f.write(content)

    print(f"/{name} command installed at: {cmd_path}")


def install_slash_commands():
    """Install the /history and /last slash commands."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    system = platform.system()

    if system == "Windows":
        venv_python = os.path.join(script_dir, ".venv", "Scripts", "python.exe")
    else:
        venv_python = os.path.join(script_dir, ".venv", "bin", "python3")

    gui_script = os.path.join(script_dir, "review_gui.py")

    _install_command("history", (
        "Launch the Claude Code Session Diff Reviewer GUI by running this command in the background:\n"
        "\n"
        "```\n"
        f"{venv_python} \"{gui_script}\"\n"
        "```\n"
        "\n"
        "Run it detached so it doesn't block the conversation. Tell the user the history viewer has been launched.\n"
    ))

    _install_command("last", (
        "Open the session history GUI and automatically show the diff for the most recent change in the current project. "
        "Run this command in the background:\n"
        "\n"
        "```\n"
        f"{venv_python} \"{gui_script}\" --last \"$(pwd)\"\n"
        "```\n"
        "\n"
        "Do not wait for it to finish. Just confirm it was launched.\n"
    ))


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

    hook_exists = False
    for matcher_group in pre_tool_use:
        for hook in matcher_group.get("hooks", []):
            if "hook_snapshot.py" in hook.get("command", ""):
                print("Hook already configured — skipping.")
                hook_exists = True
                break

    if not hook_exists:
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

    # Install slash commands
    print()
    install_slash_commands()

    print()
    print("Restart Claude Code for changes to take effect.")


if __name__ == "__main__":
    main()
