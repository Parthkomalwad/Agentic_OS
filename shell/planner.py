"""Multi-step plan execution.

When the LLM returns a plan array, this module executes steps sequentially,
displaying progress and pausing on failures.
"""
from __future__ import annotations

import os
import sys

from shell.executor import execute_bash
from shell.safety import is_destructive, confirm_destructive


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def execute_plan(plan: list[str], cwd: str, description: str = "") -> int:
    """Execute a list of shell commands sequentially as a plan.

    Displays all steps upfront.
    Updates step markers: ○ → ✓ (success) or ✗ (failure).
    On failure, prompts: [c]ontinue [r]etry [a]bort.

    Args:
        plan: Ordered list of shell command strings.
        cwd: Starting working directory.
        description: Optional human-readable description of the plan.

    Returns:
        Exit code of the last executed step.
    """
    if not plan:
        return 0

    # Show all steps upfront
    label = f"plan: {description}" if description else "plan"
    _out(f"\n{label}")
    for i, cmd in enumerate(plan, 1):
        _out(f"  o  {i}. {cmd}")
    _out("")

    # Confirm before executing
    try:
        answer = input("confirm all steps? [Enter] cancel [q]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _out("cancelled")
        return 1
    if answer == "q":
        _out("cancelled")
        return 1

    last_exit = 0
    current_cwd = cwd

    for i, cmd in enumerate(plan):
        # Safety check per step
        if is_destructive(cmd):
            if not confirm_destructive(cmd):
                _out(f"step {i+1} skipped")
                continue

        exit_code, _ = execute_bash(cmd, current_cwd)
        # Update cwd after each step (cd may have changed it)
        current_cwd = os.getcwd()
        last_exit = exit_code

        if exit_code == 0:
            _out(f"  v  step {i+1} done")
        else:
            _out(f"\n  x  step {i+1} failed (exit {exit_code})\n")
            try:
                choice = input("  [c]ontinue  [r]etry  [a]bort: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "a"

            if choice == "a":
                _out("plan aborted")
                return exit_code
            elif choice == "r":
                # Retry the same step
                exit_code2, _ = execute_bash(cmd, current_cwd)
                current_cwd = os.getcwd()
                last_exit = exit_code2
                if exit_code2 == 0:
                    _out(f"  v  step {i+1} done (retry)")
                else:
                    _out(f"  x  step {i+1} still failed — continuing")
            # "c" or anything else: continue to next step

    return last_exit
