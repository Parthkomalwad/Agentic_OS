"""Bash executor.

All commands run inside a ptyprocess so interactive programs (vim, htop, ssh)
work correctly. cd is intercepted and handled via os.chdir() — never subprocess.
Simple file-view commands (cat, head, tail of a single file) are intercepted and
rendered with Rich syntax highlighting for a better reading experience.

Never use print() here; use Rich Console for all output.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ptyprocess import PtyProcessUnicode
from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel

console = Console(highlight=False, width=120)

# Commands we intercept for Rich rendering: cat/head/tail with a single plain filepath
_VIEW_RE = re.compile(r'^(cat|head|tail)\s+(-n\s*\d+\s+)?([^\s|&;<>]+)$')


def _rich_cat(filepath: str, command: str) -> tuple[int, str]:
    """Render a file with syntax highlighting inside a panel."""
    path = Path(filepath).expanduser()
    if not path.exists():
        # Fall through to normal pty execution so error message is accurate
        return _pty_exec(command, os.getcwd())
    try:
        content = path.read_text(errors="replace")
    except (PermissionError, OSError):
        return _pty_exec(command, os.getcwd())

    # Detect language from extension for syntax highlighting
    suffix = path.suffix.lstrip(".").lower()
    lang_map = {
        "py": "python", "js": "javascript", "ts": "typescript",
        "sh": "bash", "bash": "bash", "zsh": "bash",
        "json": "json", "yaml": "yaml", "yml": "yaml",
        "toml": "toml", "md": "markdown", "html": "html",
        "css": "css", "sql": "sql", "go": "go", "rs": "rust",
        "c": "c", "cpp": "cpp", "h": "c", "java": "java",
        "xml": "xml", "ini": "ini", "cfg": "ini", "conf": "ini",
        "dockerfile": "dockerfile", "tf": "hcl",
    }
    lang = lang_map.get(suffix, "text")
    # Special case: files named Dockerfile, Makefile, etc.
    if path.name in ("Dockerfile", "Makefile", "Vagrantfile"):
        lang = path.name.lower()

    syn = Syntax(
        content, lang,
        theme="monokai",
        line_numbers=True,
        word_wrap=False,
    )
    title = f"[color(238)]{filepath}[/color(238)]"
    console.print(Panel(syn, title=title, border_style="color(55)", padding=(0, 1)))
    sys.stdout.flush()
    return 0, content


def _pty_exec(command: str, cwd: str) -> tuple[int, str]:
    """Run command in a pty, streaming output directly to stdout."""
    proc = PtyProcessUnicode.spawn(["/bin/bash", "-c", command], cwd=cwd)
    output = []
    while True:
        try:
            chunk = proc.read(1024)
            sys.stdout.write(chunk)
            sys.stdout.flush()
            output.append(chunk)
        except EOFError:
            break
    proc.wait()
    return proc.exitstatus or 0, "".join(output)


def execute_bash(command: str, cwd: str) -> tuple[int, str]:
    """Execute a shell command, returning (exit_code, combined_output).

    Special cases:
    - 'cd' calls os.chdir() on the Python process.
    - 'cat/head/tail <file>' renders with Rich syntax highlighting.
    - Everything else runs in a PtyProcessUnicode.

    Args:
        command: Shell command string to execute.
        cwd: Current working directory for the subprocess.

    Returns:
        Tuple of (exit_code, output_string).
    """
    stripped = command.strip()

    # cd interception — MUST use os.chdir, never subprocess
    if stripped.startswith("cd"):
        rest = stripped[2:].strip()
        if rest == "-":
            return 0, ""
        target = rest or os.path.expanduser("~")
        target = os.path.expandvars(os.path.expanduser(target))
        try:
            os.chdir(target)
            return 0, ""
        except FileNotFoundError:
            sys.stdout.write(f"cd: {target}: No such file or directory\n")
            sys.stdout.flush()
            return 1, ""

    # Rich file-view interception for cat/head/tail of a single plain file
    m = _VIEW_RE.match(stripped)
    if m:
        filepath = m.group(3)
        return _rich_cat(filepath, stripped)

    # All other commands run in a pty so interactive programs work correctly
    return _pty_exec(stripped, cwd)
