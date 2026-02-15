#!/usr/bin/env python3
"""PyQt6 GUI to browse Claude Code session history and open PyCharm diffs.

Shows a table of all user prompts across sessions. Double-click a prompt
that has file edits to open a PyCharm diff of what changed during that prompt.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

SNAPSHOTS_DIR = os.path.expanduser("~/.claude/session-snapshots")
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$"
)

# Patterns that indicate a non-human user message (system-injected noise)
_NOISE_PATTERNS = (
    "[Request interrupted",
    "<command-message>",
    "<command-name>",
    "<task-notification>",
    "<system-reminder>",
)


def _extract_user_text(msg):
    """Extract plain text from a user message's content field."""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""


def _is_noise(text):
    """Return True if the message text is system-injected noise."""
    stripped = text.strip()
    if not stripped:
        return True
    for pattern in _NOISE_PATTERNS:
        if stripped.startswith(pattern):
            return True
    return False


def _read_jsonl(jsonl_path):
    """Read a JSONL file and return a list of parsed JSON objects."""
    lines = []
    try:
        with open(jsonl_path) as f:
            for raw in f:
                try:
                    lines.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return lines


def _find_meaningful_prompts(lines):
    """Return list of (line_index, text, cwd, timestamp) for meaningful user prompts."""
    prompts = []
    for i, obj in enumerate(lines):
        if obj.get("type") != "user":
            continue
        text = _extract_user_text(obj.get("message", {}))
        if _is_noise(text):
            continue
        prompts.append((i, text, obj.get("cwd", ""), obj.get("timestamp", "")))
    return prompts


def _extract_tool_calls(lines):
    """Return list of (line_index, tool_name, tool_input) for Write/Edit calls."""
    calls = []
    for i, obj in enumerate(lines):
        if obj.get("type") != "assistant":
            continue
        content = obj.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            if name in ("Write", "Edit"):
                calls.append((i, name, block.get("input", {})))
    return calls


def _parse_jsonl_prompts(jsonl_path):
    """Parse a JSONL session file into individual user prompts with their file edits."""
    session_id = os.path.basename(jsonl_path).removesuffix(".jsonl")
    lines = _read_jsonl(jsonl_path)
    if not lines:
        return []

    meaningful = _find_meaningful_prompts(lines)
    if not meaningful:
        return []

    tool_calls = _extract_tool_calls(lines)
    prompt_line_indices = [m[0] for m in meaningful]

    prompts = []
    for idx, (line_i, text, cwd, timestamp) in enumerate(meaningful):
        # Find next prompt boundary
        next_line = prompt_line_indices[idx + 1] if idx + 1 < len(meaningful) else len(lines)

        # Attribute tool calls between this prompt and the next
        files_edited = []
        for tc_line, tc_name, tc_input in tool_calls:
            if line_i <= tc_line < next_line:
                fp = tc_input.get("file_path", "")
                if fp and fp not in files_edited:
                    files_edited.append(fp)

        prompts.append({
            "session_id": session_id,
            "jsonl_path": jsonl_path,
            "prompt_index": idx,
            "timestamp": timestamp,
            "prompt_text": text,
            "project_path": cwd,
            "files_edited": files_edited,
        })

    return prompts


def _reconstruct_prompt_diff(jsonl_path, prompt_index):
    """Reconstruct before/after file states for a specific prompt.

    Walks the JSONL from the start, tracking file states through Write/Edit calls.
    Uses session snapshots as the initial state for files edited for the first time.

    Returns (before_files, after_files) where each is {filepath: content_string}.
    Files that didn't exist before are included with empty string in before_files.
    """
    session_id = os.path.basename(jsonl_path).removesuffix(".jsonl")
    lines = _read_jsonl(jsonl_path)
    meaningful = _find_meaningful_prompts(lines)
    tool_calls = _extract_tool_calls(lines)

    if prompt_index >= len(meaningful):
        return {}, {}

    target_line = meaningful[prompt_index][0]
    next_line = meaningful[prompt_index + 1][0] if prompt_index + 1 < len(meaningful) else len(lines)

    # Load initial file states from session snapshots
    file_states = {}
    snap_files_dir = os.path.join(SNAPSHOTS_DIR, session_id, "files")
    if os.path.isdir(snap_files_dir):
        for root, _dirs, files in os.walk(snap_files_dir):
            for fname in files:
                snap_path = os.path.join(root, fname)
                rel = os.path.relpath(snap_path, snap_files_dir)
                original_abs = "/" + rel
                try:
                    with open(snap_path) as f:
                        file_states[original_abs] = f.read()
                except OSError:
                    pass

    # Walk all tool calls, tracking file states and capturing before/after
    before_files = {}
    files_in_prompt = set()

    for tc_line, tc_name, tc_input in tool_calls:
        fp = tc_input.get("file_path", "")
        if not fp:
            continue

        # If this tool call is in our target prompt and it's the first edit
        # to this file in this prompt, capture the "before" state
        if target_line <= tc_line < next_line:
            if fp not in files_in_prompt:
                before_files[fp] = file_states.get(fp, "")
                files_in_prompt.add(fp)

        # Apply the edit to track state
        if tc_name == "Write":
            file_states[fp] = tc_input.get("content", "")
        elif tc_name == "Edit":
            old = tc_input.get("old_string", "")
            new = tc_input.get("new_string", "")
            if fp in file_states and old:
                if tc_input.get("replace_all"):
                    file_states[fp] = file_states[fp].replace(old, new)
                else:
                    file_states[fp] = file_states[fp].replace(old, new, 1)
            elif fp not in file_states:
                # File exists on disk but we don't have its initial state
                # (no snapshot). Skip this edit — we can't reconstruct.
                pass

        # Stop processing once we're past the target prompt
        if tc_line >= next_line:
            break

    # Collect "after" states
    after_files = {}
    for fp in files_in_prompt:
        after_files[fp] = file_states.get(fp, "")

    return before_files, after_files


def _projects_dir_mtime():
    """Return a quick fingerprint of the projects directory: {subdir: mtime}."""
    mtimes = {}
    if not os.path.isdir(PROJECTS_DIR):
        return mtimes
    try:
        for project_dir in os.scandir(PROJECTS_DIR):
            if project_dir.is_dir():
                mtimes[project_dir.path] = project_dir.stat().st_mtime
    except OSError:
        pass
    return mtimes


def load_prompts(prev_fingerprint=None):
    """Load all user prompts from all session JSONL files.

    Returns (prompts_list, fingerprint). If prev_fingerprint is provided and
    no directories have changed, returns (None, prev_fingerprint).
    """
    current_fp = _projects_dir_mtime()

    if prev_fingerprint is not None and current_fp == prev_fingerprint:
        return None, prev_fingerprint

    all_prompts = []

    for project_path in current_fp:
        for entry in os.scandir(project_path):
            if not entry.is_file() or not _UUID_RE.match(entry.name):
                continue
            all_prompts.extend(_parse_jsonl_prompts(entry.path))

    return all_prompts, current_fp


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


def open_diff(before_files, after_files, parent=None):
    """Open PyCharm diff between before and after file states.

    before_files/after_files: {absolute_path: content_string}
    """
    pycharm = find_pycharm()
    if not pycharm:
        QMessageBox.critical(parent, "PyCharm not found",
                             "Could not find 'pycharm' or 'pycharm-professional' on PATH.")
        return

    if not before_files and not after_files:
        QMessageBox.information(parent, "No changes", "No file changes to display.")
        return

    all_paths = set(before_files) | set(after_files)
    before_dir = tempfile.mkdtemp(prefix="claude_diff_before_")
    after_dir = tempfile.mkdtemp(prefix="claude_diff_after_")

    for filepath in all_paths:
        rel = filepath.lstrip("/")

        dest_before = os.path.join(before_dir, rel)
        os.makedirs(os.path.dirname(dest_before), exist_ok=True)
        with open(dest_before, "w") as f:
            f.write(before_files.get(filepath, ""))

        dest_after = os.path.join(after_dir, rel)
        os.makedirs(os.path.dirname(dest_after), exist_ok=True)
        with open(dest_after, "w") as f:
            f.write(after_files.get(filepath, ""))

    subprocess.Popen([pycharm, "diff", before_dir, after_dir])


class NumericTableItem(QTableWidgetItem):
    """Table item that sorts numerically instead of lexicographically."""

    def __lt__(self, other):
        try:
            return int(self.text() or "0") < int(other.text() or "0")
        except ValueError:
            return super().__lt__(other)


class ReviewApp(QMainWindow):
    def __init__(self, last_project=None):
        super().__init__()
        self._last_project = last_project
        self.setWindowTitle("Claude Code Session Diff Reviewer")
        self.resize(1200, 600)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)

        # Filter bar
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Type to filter by prompt text or project...")
        self.filter_input.textChanged.connect(self.populate)
        filter_layout.addWidget(self.filter_input)
        filter_layout.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.addItem("All")
        self.project_combo.currentIndexChanged.connect(self.populate)
        filter_layout.addWidget(self.project_combo)
        self.edits_only_cb = QCheckBox("With file edits only")
        self.edits_only_cb.setChecked(True)
        self.edits_only_cb.stateChanged.connect(self.populate)
        filter_layout.addWidget(self.edits_only_cb)
        layout.addLayout(filter_layout)

        # Table
        self.columns = ["Date", "Files", "Project", "Prompt", ""]
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 30)

        self.table.doubleClicked.connect(self.on_activate)
        layout.addWidget(self.table)

        # Load data
        self.all_prompts, self._fingerprint = load_prompts()
        self._update_project_combo()
        self.populate()

        # Sort by date descending initially
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)

        # Auto-refresh every 5 seconds (skips re-parse if no files changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._check_refresh)
        self._refresh_timer.start(5000)

        # If launched with --last, auto-open the most recent diff after the event loop starts
        if self._last_project:
            QTimer.singleShot(100, lambda: self.open_last_for_project(self._last_project, refresh=False))

    def open_last_for_project(self, project_path, refresh=True):
        """Find the most recent file-editing prompt for project_path and open its diff."""
        if refresh:
            # Force-refresh data (bypass fingerprint cache) — needed when
            # called via socket from a second instance, but not on first launch
            # where data was just loaded in __init__.
            result, fp = load_prompts()
            if result is not None:
                self.all_prompts = result
                self._fingerprint = fp
                self._update_project_combo()
                self.populate()

        # Filter to prompts matching this project with file edits
        candidates = [
            p for p in self.all_prompts
            if p.get("files_edited") and p.get("project_path", "").rstrip("/") == project_path.rstrip("/")
        ]
        if not candidates:
            QMessageBox.information(self, "No changes found",
                                    f"No file-editing prompts found for project:\n{project_path}")
            return

        # Sort by timestamp descending, pick the most recent
        candidates.sort(key=lambda p: p.get("timestamp", ""), reverse=True)
        prompt = candidates[0]

        before_files, after_files = _reconstruct_prompt_diff(
            prompt["jsonl_path"], prompt["prompt_index"]
        )
        if not before_files and not after_files:
            QMessageBox.information(self, "Cannot reconstruct",
                                    "Could not reconstruct file states for the most recent prompt.")
            return
        open_diff(before_files, after_files, parent=self)

    def _update_project_combo(self):
        projects = sorted({format_project(p["project_path"]) for p in self.all_prompts if p["project_path"]})
        current = self.project_combo.currentText()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("All")
        self.project_combo.addItems(projects)
        # Restore previous selection if it still exists
        idx = self.project_combo.findText(current)
        self.project_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.project_combo.blockSignals(False)

    def _check_refresh(self):
        result, new_mtimes = load_prompts(prev_fingerprint=self._fingerprint)
        if result is None:
            return  # No changes
        self._fingerprint = new_mtimes
        self.all_prompts = result
        self._update_project_combo()
        # Preserve current sort column/order
        header = self.table.horizontalHeader()
        sort_col = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        self.populate()
        self.table.sortItems(sort_col, sort_order)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.table.hasFocus():
            self.on_activate()
        else:
            super().keyPressEvent(event)

    def populate(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        filter_text = self.filter_input.text().lower()
        edits_only = self.edits_only_cb.isChecked()
        selected_project = self.project_combo.currentText()

        green = QColor("#2e7d32")
        grey = QColor("#9e9e9e")

        for p in self.all_prompts:
            has_edits = len(p["files_edited"]) > 0
            if edits_only and not has_edits:
                continue
            if selected_project != "All" and format_project(p["project_path"]) != selected_project:
                continue
            if filter_text:
                searchable = " ".join([
                    p.get("prompt_text", ""),
                    p.get("project_path", ""),
                ]).lower()
                if filter_text not in searchable:
                    continue

            row = self.table.rowCount()
            self.table.insertRow(row)

            color = green if has_edits else grey

            date_item = QTableWidgetItem(format_date(p["timestamp"]))
            files_display = str(len(p["files_edited"])) if has_edits else ""
            files_item = NumericTableItem(files_display)
            files_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            project_item = QTableWidgetItem(format_project(p["project_path"]))

            prompt_display = p["prompt_text"].replace("\n", " ").strip()
            prompt_item = QTableWidgetItem(prompt_display)

            items = [date_item, files_item, project_item, prompt_item]
            for col, item in enumerate(items):
                item.setForeground(color)
                item.setData(Qt.ItemDataRole.UserRole, id(p))
                self.table.setItem(row, col, item)

            # "..." button to view full prompt
            btn = QPushButton("...")
            btn.setFixedWidth(26)
            full_text = p["prompt_text"]
            btn.clicked.connect(lambda _, t=full_text: self._show_prompt_dialog(t))
            self.table.setCellWidget(row, 4, btn)

        self.table.setSortingEnabled(True)

    def _show_prompt_dialog(self, text):
        dlg = QDialog(self)
        dlg.setWindowTitle("Full Prompt")
        dlg.resize(700, 400)
        layout = QVBoxLayout(dlg)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text)
        layout.addWidget(text_edit)
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(dlg.close)
        layout.addWidget(btn_box)
        dlg.show()

    def on_activate(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        prompt_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        prompt = next((p for p in self.all_prompts if id(p) == prompt_id), None)
        if not prompt:
            return
        if not prompt["files_edited"]:
            QMessageBox.information(self, "No file edits",
                                    "No files were edited during this prompt.")
            return

        before_files, after_files = _reconstruct_prompt_diff(
            prompt["jsonl_path"], prompt["prompt_index"]
        )
        if not before_files and not after_files:
            QMessageBox.information(self, "Cannot reconstruct",
                                    "Could not reconstruct file states for this prompt.")
            return
        open_diff(before_files, after_files, parent=self)


_SOCKET_NAME = "claude_session_diff_reviewer"


def _parse_last_arg():
    """Return the project path if --last <path> was passed, else None."""
    try:
        idx = sys.argv.index("--last")
        return sys.argv[idx + 1]
    except (ValueError, IndexError):
        return None


def _raise_window(window):
    """Bring the window to front on all platforms."""
    try:
        import pywinctl as pwc
        wins = pwc.getWindowsWithTitle(window.windowTitle())
        if wins:
            wins[0].minimize()
            wins[0].restore()
            return
    except Exception:
        pass

    window.setWindowState(
        window.windowState() & ~Qt.WindowState.WindowMinimized
    )
    window.show()
    window.raise_()
    window.activateWindow()


def main():
    app = QApplication(sys.argv)
    last_project = _parse_last_arg()

    # Check if another instance is already running
    socket = QLocalSocket()
    socket.connectToServer(_SOCKET_NAME)
    if socket.waitForConnected(500):
        # Another instance exists — send message so it can act
        if last_project:
            msg = f"LAST:{last_project}"
        else:
            msg = os.environ.get("XDG_ACTIVATION_TOKEN", "")
        socket.write(msg.encode())
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        sys.exit(0)

    # We're the first instance — start the local server
    QLocalServer.removeServer(_SOCKET_NAME)
    server = QLocalServer()
    server.listen(_SOCKET_NAME)

    window = ReviewApp(last_project=last_project)
    window.show()

    def on_new_connection():
        client = server.nextPendingConnection()
        if not client:
            return
        client.waitForReadyRead(1000)
        data = bytes(client.readAll()).decode()
        client.disconnectFromServer()

        if data.startswith("LAST:"):
            project_path = data[5:]
            _raise_window(window)
            window.open_last_for_project(project_path)
            return

        if data:
            os.environ["XDG_ACTIVATION_TOKEN"] = data

        _raise_window(window)

    server.newConnection.connect(on_new_connection)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
