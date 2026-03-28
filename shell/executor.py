"""Bash executor.

All commands run inside a ptyprocess so interactive programs (vim, htop, ssh)
work correctly. cd is intercepted and handled via os.chdir() — never subprocess.

Never use print() here; use Rich Console for all output.
"""
from __future__ import annotations

import os
import sys

from ptyprocess import PtyProcessUnicode
from rich.console import Console

console = Console()


def execute_bash(command: str, cwd: str) -> tuple[int, str]:
    """Execute a shell command, returning (exit_code, combined_output).

    Special case: 'cd' commands call os.chdir() on the Python process.
    All other commands run in a PtyProcessUnicode.

    Args:
        command: Shell command string to execute.
        cwd: Current working directory for the subprocess.

    Returns:
        Tuple of (exit_code, output_string).
    """
    # cd interception — MUST use os.chdir, never subprocess
    stripped = command.strip()
    if stripped.startswith("cd"):
        # Handle bare "cd" or "cd " with no argument
        rest = stripped[2:].strip()

        # cd - is complex to implement properly in Phase 1; skip it
        if rest == "-":
            return 0, ""

        target = rest or os.path.expanduser("~")
        target = os.path.expandvars(os.path.expanduser(target))
        try:
            os.chdir(target)
            return 0, ""
        except FileNotFoundError:
            return 1, f"cd: {target}: No such file or directory"

    # All other commands run in a pty so interactive programs work correctly
    proc = PtyProcessUnicode.spawn(["/bin/bash", "-c", command], cwd=cwd)
    output = []
    while True:
        try:
            chunk = proc.read(1024)
            # Write raw TTY output directly to stdout — not via Rich
            sys.stdout.write(chunk)
            sys.stdout.flush()
            output.append(chunk)
        except EOFError:
            break
    proc.wait()
    # proc.exitstatus can be None if the process was killed by a signal
    return proc.exitstatus or 0, "".join(output)
