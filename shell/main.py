"""Entry point for the agentic shell.

SSH_ORIGINAL_COMMAND bypass MUST remain the first executable code.
Handles startup, config loading, session resume, and launches the REPL.
"""
import os
import sys

# --- SSH bypass: must be first executable lines, non-negotiable ---
_original_cmd = os.environ.get("SSH_ORIGINAL_COMMAND")
if _original_cmd:
    os.execvp("/bin/bash", ["/bin/bash", "-c", _original_cmd])
    sys.exit(0)
# -----------------------------------------------------------------


def main() -> None:
    """Shell entry point — called by the installed binary."""
    import json
    import uuid
    from pathlib import Path

    from rich.console import Console
    from rich.panel import Panel

    from shell.config.schema import ShellConfig

    console = Console()

    session_id = str(uuid.uuid4())

    config_path = Path.home() / ".config" / "agentic-shell" / "config.json"

    # --- Run first-run wizard if config missing or setup not complete ---
    if not config_path.exists():
        from shell.config.wizard import run_wizard
        run_wizard()
        # After wizard, re-check — wizard saves the file
        if not config_path.exists():
            sys.exit(0)

    # --- Load config ---
    try:
        raw = json.loads(config_path.read_text())
        config = ShellConfig.from_dict(raw)
        # Carry api_key through as a plain attribute (not in dataclass — avoids validation issues)
        if "api_key" in raw and raw["api_key"]:
            config.api_key = raw["api_key"]  # type: ignore[attr-defined]
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        console.print(f"[yellow]Warning:[/yellow] Failed to parse config ({exc}). Using defaults.")
        config = ShellConfig.defaults()

    # Re-run wizard if setup was not completed
    if not config.setup_complete:
        from shell.config.wizard import run_wizard
        run_wizard()
        try:
            raw = json.loads(config_path.read_text())
            config = ShellConfig.from_dict(raw)
        except Exception:
            config = ShellConfig.defaults()

    # --- Session resume: load compressed context if available ---
    username = os.environ.get("USER", os.environ.get("USERNAME", "user"))
    try:
        from shell.memory.store import load_session_context
        ctx = load_session_context(username)
        if ctx:
            console.print(Panel(
                f"[dim]Resuming session context ({len(ctx)} chars)[/dim]\n\n"
                + ctx[:300]
                + ("[dim]...[/dim]" if len(ctx) > 300 else ""),
                title="[bold cyan]session resumed[/bold cyan]",
                border_style="cyan",
            ))
    except Exception:
        pass  # Session resume is best-effort

    # --- Launch tmux session with sidebar (no-op if already in tmux or tmux unavailable) ---
    if False:  # tmux handled by wrapper script
        try:
            from shell.tui.layout import create_session
            create_session(username)
            # create_session calls os.execvp to attach — if we reach here, tmux unavailable
        except Exception:
            pass

    from shell import loop  # lazy import to avoid circular imports

    try:
        loop.start(config, session_id)
    except KeyboardInterrupt:
        console.print("\nbye")


if __name__ == "__main__":
    main()
