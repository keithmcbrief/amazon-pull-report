"""User preferences: file format and output location.

First run flow: when `config/preferences.json` doesn't exist, the SKILL.md
instructs Claude to call AskUserQuestion. The CLI also falls back to a
terminal prompt for users who run the script directly without Claude.

Both paths end with calling `save(...)` to persist the choices.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SKILL_ROOT = Path(__file__).resolve().parent.parent
PREFERENCES_PATH = SKILL_ROOT / "config" / "preferences.json"


def default_documents_dir() -> Path:
    """Cross-platform: ~/Documents/Amazon Reports.

    On Windows this resolves to C:\\Users\\<name>\\Documents\\Amazon Reports
    (Path.home() returns the user profile; Documents resolves through Windows API
    even when redirected to OneDrive).
    """
    home = Path.home()
    docs = home / "Documents"
    if not docs.exists():
        # Edge case: rare. Fall back to the home folder.
        return home / "Amazon Reports"
    return docs / "Amazon Reports"


def default_downloads_dir() -> Path:
    home = Path.home()
    downloads = home / "Downloads"
    if not downloads.exists():
        return home / "Amazon Reports"
    return downloads


def load() -> Optional[dict]:
    """Load preferences from disk. Returns None on first run (file missing)."""
    if not PREFERENCES_PATH.exists():
        return None
    try:
        return json.loads(PREFERENCES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save(format: str, output_dir: str | Path) -> dict:
    """Persist preferences. Creates parent directory if needed."""
    if format not in ("csv", "txt"):
        raise ValueError(f"format must be 'csv' or 'txt', got {format!r}")
    record = {
        "format": format,
        "output_dir": str(Path(output_dir).expanduser()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(json.dumps(record, indent=2))
    return record


def prompt_cli() -> dict:
    """Interactive CLI fallback when no preferences exist and Claude isn't driving.

    Used only when the user runs `uv run bin/run.py` directly from a terminal.
    Returns the saved preferences dict.
    """
    print("", file=sys.stderr)
    print("First-run setup — quick two-question setup.", file=sys.stderr)
    print("(You can change these anytime by editing config/preferences.json.)", file=sys.stderr)
    print("", file=sys.stderr)

    # Question 1: format
    print("Which file format do you prefer when opening reports in Excel/Numbers?", file=sys.stderr)
    print("  1) .csv  — comma-separated. Universal. (recommended)", file=sys.stderr)
    print("  2) .txt  — tab-delimited. Matches Amazon's default download.", file=sys.stderr)
    while True:
        choice = input("Choice [1]: ").strip() or "1"
        if choice == "1":
            fmt = "csv"
            break
        if choice == "2":
            fmt = "txt"
            break
        print("  Please enter 1 or 2.", file=sys.stderr)

    # Question 2: location
    docs = default_documents_dir()
    dls = default_downloads_dir()
    cwd = Path.cwd() / "amazon-reports"
    print("", file=sys.stderr)
    print("Where should reports be saved? (one flat folder, all reports land here)", file=sys.stderr)
    print(f"  1) {docs}  (recommended)", file=sys.stderr)
    print(f"  2) {dls}  (your Downloads folder — files land directly here)", file=sys.stderr)
    print(f"  3) {cwd}  (inside the project you ran this from)", file=sys.stderr)
    print("  4) Custom — type any folder path", file=sys.stderr)
    while True:
        choice = input("Choice [1]: ").strip() or "1"
        if choice == "1":
            out = docs
            break
        if choice == "2":
            out = dls
            break
        if choice == "3":
            out = cwd
            break
        if choice == "4":
            custom = input("Folder path: ").strip()
            if custom:
                out = Path(custom).expanduser()
                break
            continue
        print("  Please enter 1, 2, 3, or 4.", file=sys.stderr)

    record = save(fmt, out)
    print(f"\nSaved preferences to {PREFERENCES_PATH}", file=sys.stderr)
    print(f"  format:     {record['format']}", file=sys.stderr)
    print(f"  output_dir: {record['output_dir']}", file=sys.stderr)
    print("", file=sys.stderr)
    return record


def get_or_default(cli_format: Optional[str], cli_output_dir: Optional[str]) -> dict:
    """Resolve effective preferences for this run.

    Priority: CLI flags > preferences.json > built-in defaults.
    Does NOT prompt — the caller decides whether to prompt (Claude or CLI).
    """
    prefs = load() or {}
    return {
        "format": cli_format or prefs.get("format") or "csv",
        "output_dir": cli_output_dir or prefs.get("output_dir") or str(default_documents_dir()),
    }
