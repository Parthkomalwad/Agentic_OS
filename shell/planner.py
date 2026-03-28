"""Multi-step plan execution.

When the LLM returns a plan array, this module executes steps sequentially,
displaying progress via Rich Tree and pausing on failures.
"""
from __future__ import annotations

import os

from rich.console import Console
from rich.tree import Tree

from shell.executor import execute_bash
from shell.safety import is_destructive, confirm_destructive

console = Console()


def execute_plan(plan: list[str], cwd: str, description: str = "") -> int:
    """Execute a list of shell commands sequentially as a plan.

    Displays all steps upfront using Rich Tree.
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
    tree = Tree(f"[bold]{label}[/bold]")
    for i, cmd in enumerate(plan, 1):
        tree.add(f"[dim]○[/dim]  {i}. {cmd}")

    console.print()
    console.print(tree)
    console.print()

    # Confirm before executing
    try:
        answer = input("confirm all steps? [Enter] cancel [q]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print("[yellow]cancelled[/yellow]")
        return 1
    if answer == "q":
        console.print("[yellow]cancelled[/yellow]")
        return 1

    last_exit = 0
    current_cwd = cwd

    for i, cmd in enumerate(plan):
        # Safety check per step
        if is_destructive(cmd):
            if not confirm_destructive(cmd):
                console.print(f"[yellow]step {i+1} skipped[/yellow]")
                continue

        exit_code, _ = execute_bash(cmd, current_cwd)
        # Update cwd after each step (cd may have changed it)
        current_cwd = os.getcwd()
        last_exit = exit_code

        if exit_code == 0:
            console.print(f"  [green]✓[/green]  step {i+1} done")
        else:
            console.print(f"\n  [red]✗ step {i+1} failed (exit {exit_code})[/red]\n")
            try:
                choice = input("  [c]ontinue  [r]etry  [a]bort: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "a"

            if choice == "a":
                console.print("[yellow]plan aborted[/yellow]")
                return exit_code
            elif choice == "r":
                # Retry the same step
                exit_code2, _ = execute_bash(cmd, current_cwd)
                current_cwd = os.getcwd()
                last_exit = exit_code2
                if exit_code2 == 0:
                    console.print(f"  [green]✓[/green]  step {i+1} done (retry)")
                else:
                    console.print(f"  [red]✗[/red]  step {i+1} still failed — continuing")
            # "c" or anything else: continue to next step

    return last_exit
