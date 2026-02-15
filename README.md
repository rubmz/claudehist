# Claude Code Session /History

**See every change Claude made in a single diff — no git required, no digging through local history.**

When Claude Code edits your files across a session, it can be hard to get a clear picture of everything that changed. Local history is scattered, and you may not be using git (or don't want to clutter it with work-in-progress commits). This tool gives you a complete before-and-after view of all files Claude touched in any session, opened directly in PyCharm's diff viewer.

## How It Works

1. A **Hook** (`hook_snapshot.py`) runs automatically before every Write/Edit operation Claude performs. It silently saves a copy of each file's original state to `~/.claude/session-snapshots/`.
2. A **GUI** (`review_gui.py`) lists all your recent sessions, allowing you to select one and see what changed there.

## Installation

This will set up the hook and add the skill to Claude.

**Linux / macOS:**
```bash
./setup.sh
```

**Windows:**
```cmd
setup.bat
```

* Safe to re-run if not sure...
* Restart Claude Code after running it.

## Usage

From Claude Code's terminal, run:

```
/history
```

This opens the session diff reviewer GUI. From there:

- **Filter** sessions by keyword (searches summaries, prompts, and project names)
- **Sort** by clicking any column header
- **Double-click** a session (highlighted in green if it has snapshots) to launch PyCharm's diff view

## Requirements

- Python 3.<a lot>
- PyCharm (must be available on PATH as `pycharm` or `pycharm-professional`)
- Claude Code

## Platform Support

Windows, Linux, Mac and Cheese (Mac not tested... Should work, but I don't have a Mac...)

## How Snapshots Work

- Only the **first** version of each file is saved per session (the true "before" state)
- Snapshots are stored under `~/.claude/session-snapshots/{session_id}/files/`
- Old snapshots are automatically cleaned up after 7 days
- The hook is designed to never interfere with Claude — if anything goes wrong, it fails silently
