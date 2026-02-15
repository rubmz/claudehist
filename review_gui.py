#!/usr/bin/env python3
"""Tkinter GUI to browse Claude Code session history and open PyCharm diffs.

Shows a table of all sessions with snapshot status. Double-click a session
with snapshots to open a PyCharm directory diff (before vs current).
"""

import json
import os
import shutil
import subprocess
import tempfile
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

SNAPSHOTS_DIR = os.path.expanduser("~/.claude/session-snapshots")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")


def load_sessions():
    """Merge session metadata from all projects with snapshot file counts."""

    # 1. Load all session metadata from projects
    sessions = {}
    for project_dir in os.scandir(PROJECTS_DIR):
        if not project_dir.is_dir():
            continue
        index_path = os.path.join(project_dir.path, "sessions-index.json")
        if not os.path.exists(index_path):
            continue
        with open(index_path) as f:
            data = json.load(f)
        for entry in data.get("entries", []):
            sid = entry.get("sessionId", "")
            if not sid:
                continue
            sessions[sid] = {
                "session_id": sid,
                "created": entry.get("created", ""),
                "summary": entry.get("summary", ""),
                "first_prompt": entry.get("firstPrompt", ""),
                "message_count": entry.get("messageCount", 0),
                "project_path": entry.get("projectPath", ""),
                "snapshot_count": 0,
            }

    # 2. Count snapshot files per session
    if os.path.isdir(SNAPSHOTS_DIR):
        for snap_dir in os.scandir(SNAPSHOTS_DIR):
            if not snap_dir.is_dir() or snap_dir.name.startswith("."):
                continue
            sid = snap_dir.name
            files_dir = os.path.join(snap_dir.path, "files")
            count = 0
            if os.path.isdir(files_dir):
                for _root, _dirs, files in os.walk(files_dir):
                    count += len(files)

            if sid in sessions:
                sessions[sid]["snapshot_count"] = count
            else:
                # Snapshot exists but no session metadata (orphan)
                meta_path = os.path.join(snap_dir.path, "meta.json")
                created = ""
                project = ""
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        meta = json.load(f)
                    created = meta.get("created", "")
                    project = meta.get("project_cwd", "")
                sessions[sid] = {
                    "session_id": sid,
                    "created": created,
                    "summary": "(no session metadata)",
                    "first_prompt": "",
                    "message_count": 0,
                    "project_path": project,
                    "snapshot_count": count,
                }

    return list(sessions.values())


def format_date(iso_str):
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str[:16]


def format_project(path):
    if not path:
        return ""
    return os.path.basename(path)


def find_pycharm():
    for name in ("pycharm", "pycharm-professional"):
        path = shutil.which(name)
        if path:
            return path
    return None


def open_diff(session_id):
    """Open PyCharm diff: snapshot (before) vs current file versions."""
    snap_files_dir = os.path.join(SNAPSHOTS_DIR, session_id, "files")
    if not os.path.isdir(snap_files_dir):
        messagebox.showinfo("No snapshots", "This session has no file snapshots.")
        return

    pycharm = find_pycharm()
    if not pycharm:
        messagebox.showerror("PyCharm not found",
                             "Could not find 'pycharm' or 'pycharm-professional' on PATH.")
        return

    # Collect snapshotted file paths (absolute originals)
    snapshotted = []
    for root, _dirs, files in os.walk(snap_files_dir):
        for fname in files:
            snap_path = os.path.join(root, fname)
            rel = os.path.relpath(snap_path, snap_files_dir)
            original_abs = "/" + rel
            snapshotted.append((rel, original_abs))

    if not snapshotted:
        messagebox.showinfo("No files", "Snapshot directory is empty.")
        return

    # Build temp dir with current versions
    tmp_dir = tempfile.mkdtemp(prefix="claude_diff_current_")
    for rel, original_abs in snapshotted:
        dest = os.path.join(tmp_dir, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(original_abs):
            shutil.copy2(original_abs, dest)
        else:
            # File was deleted since snapshot — create empty marker
            with open(dest, "w") as f:
                f.write("")

    # Launch PyCharm diff: left=before, right=current
    subprocess.Popen([pycharm, "diff", snap_files_dir, tmp_dir])


class ReviewApp:
    def __init__(self, root):
        self.root = root
        root.title("Claude Code Session Diff Reviewer")
        root.geometry("1200x600")

        # Filter bar
        filter_frame = ttk.Frame(root)
        filter_frame.pack(fill=tk.X, padx=8, pady=(8, 0))

        ttk.Label(filter_frame, text="Filter:").pack(side=tk.LEFT, padx=(0, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.apply_filter())
        filter_entry = ttk.Entry(filter_frame, textvariable=self.filter_var, width=60)
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Treeview
        columns = ("date", "files", "msgs", "project", "summary")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", selectmode="browse")

        self.tree.heading("date", text="Date", command=lambda: self.sort_column("date"))
        self.tree.heading("files", text="Files", command=lambda: self.sort_column("files"))
        self.tree.heading("msgs", text="Msgs", command=lambda: self.sort_column("msgs"))
        self.tree.heading("project", text="Project", command=lambda: self.sort_column("project"))
        self.tree.heading("summary", text="Summary", command=lambda: self.sort_column("summary"))

        self.tree.column("date", width=130, minwidth=100)
        self.tree.column("files", width=50, minwidth=40, anchor=tk.CENTER)
        self.tree.column("msgs", width=50, minwidth=40, anchor=tk.CENTER)
        self.tree.column("project", width=120, minwidth=80)
        self.tree.column("summary", width=600, minwidth=200)

        scrollbar = ttk.Scrollbar(root, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        scrollbar.place(relx=1.0, rely=0, relheight=1.0, anchor=tk.NE)

        # Tags for coloring
        self.tree.tag_configure("has_snapshot", foreground="#2e7d32")
        self.tree.tag_configure("no_snapshot", foreground="#9e9e9e")

        # Bindings
        self.tree.bind("<Double-1>", lambda _: self.on_activate())
        self.tree.bind("<Return>", lambda _: self.on_activate())

        # Sort state
        self.sort_col = "date"
        self.sort_reverse = True

        # Load data
        self.all_sessions = load_sessions()
        self.populate()

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        filter_text = self.filter_var.get().lower()

        filtered = []
        for s in self.all_sessions:
            if filter_text:
                searchable = " ".join([
                    s.get("summary", ""),
                    s.get("first_prompt", ""),
                    s.get("project_path", ""),
                ]).lower()
                if filter_text not in searchable:
                    continue
            filtered.append(s)

        # Sort
        def sort_key(s):
            if self.sort_col == "date":
                return s.get("created", "")
            elif self.sort_col == "files":
                return s.get("snapshot_count", 0)
            elif self.sort_col == "msgs":
                return s.get("message_count", 0)
            elif self.sort_col == "project":
                return format_project(s.get("project_path", ""))
            else:
                return s.get("summary", "").lower()

        filtered.sort(key=sort_key, reverse=self.sort_reverse)

        for s in filtered:
            tag = "has_snapshot" if s["snapshot_count"] > 0 else "no_snapshot"
            files_display = str(s["snapshot_count"]) if s["snapshot_count"] > 0 else ""
            self.tree.insert("", tk.END, iid=s["session_id"], values=(
                format_date(s["created"]),
                files_display,
                s["message_count"] or "",
                format_project(s["project_path"]),
                s["summary"],
            ), tags=(tag,))

    def apply_filter(self):
        self.populate()

    def sort_column(self, col):
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = col
            self.sort_reverse = col == "date"  # Default descending for date
        self.populate()

    def on_activate(self):
        sel = self.tree.selection()
        if not sel:
            return
        session_id = sel[0]
        # Find session
        session = next((s for s in self.all_sessions if s["session_id"] == session_id), None)
        if not session or session["snapshot_count"] == 0:
            messagebox.showinfo("No snapshots", "This session has no file snapshots to diff.")
            return
        open_diff(session_id)


def main():
    root = tk.Tk()
    ReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
